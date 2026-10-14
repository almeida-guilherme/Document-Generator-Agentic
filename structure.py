import json
import os
from typing import cast
from langchain_core.messages import HumanMessage, SystemMessage
from schemas import PDD, Step, ProcessOutline, OutlineStep, WindowRefinement, ExceptionItem, format_timestamp
from prompts.structure_prompt import OUTLINE_SYSTEM_PROMPT, REFINE_SYSTEM_PROMPT

# Narration starting this many seconds before a window is still sent with it, since people often
# explain an action right before doing it.
NARRATION_LEAD = 30.0
# How long after a step is narrated its frames are searched for, when the outline attached none.
NARRATION_WINDOW = 30.0
MAX_STEPS_PER_WINDOW = 10


def _observations_text(captions: list[dict], compact: bool = False) -> str:
    if compact:
        rows = [{"id": c["id"], "t": c["timestamp"], "screen": c["screen_or_system"], "action": c["observed_action"],
                 "text": c["visible_text"][:5]} for c in captions]
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    return json.dumps(captions, ensure_ascii=False, indent=2)


def _transcript_text(transcript: list[dict]) -> str:
    if not transcript:
        return "(no narration detected)"
    return "\n".join(f"[{t['start']:.1f}s] {t['text']}" for t in transcript)


def _dedupe_exceptions(items: list[ExceptionItem]) -> list[ExceptionItem]:
    seen, result = set(), []
    for item in items:
        key = item.name.strip().lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _clean_ids(ids: list[str], allowed: set[str], invalid: list[str]) -> list[str]:
    """Normalizes ids, drops duplicates and ids outside `allowed` (recording those in `invalid`)."""
    result = []
    for raw in ids:
        fid = raw.strip().upper()
        if fid not in allowed:
            invalid.append(raw)
        elif fid not in result:
            result.append(fid)
    return sorted(result)


def _guess_frames_from_narration(steps: list[OutlineStep], captions: list[dict]) -> list[int]:
    """
    Narrated steps often have no frames because the screen barely changes (e.g. deleting rows leaves an
    empty table that looks like any other). For those, use the frames shown while the narrator describes
    the step (up to NARRATION_WINDOW seconds, stopping where the next step's frames begin) as a first guess,
    which the refinement call then confirms or drops. Returns the numbers of the steps that got a guess.
    """
    by_id = {c["id"]: c for c in captions}
    guessed = []
    for i, step in enumerate(steps):
        if step.frame_ids or step.narrated_at is None:
            continue
        later = [by_id[f]["timestamp"] for s in steps[i + 1:] for f in s.frame_ids]
        end = min([step.narrated_at + NARRATION_WINDOW] + [t for t in later if t > step.narrated_at])
        step.frame_ids = [c["id"] for c in captions if step.narrated_at <= c["timestamp"] < end]
        if step.frame_ids:
            guessed.append(i + 1)
    return guessed


def _longest_ordered(values: list[int]) -> set[int]:
    """Indexes of a longest non-decreasing subsequence of `values` (O(n^2); a recording has few hundred frames)."""
    if not values:
        return set()
    best, prev = [1] * len(values), [-1] * len(values)
    for i in range(len(values)):
        for j in range(i):
            if values[j] <= values[i] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i, result = max(range(len(values)), key=best.__getitem__), set()
    while i != -1:
        result.add(i)
        i = prev[i]
    return result


def enforce_chronology(steps: list[Step], frame_by_id: dict[str, dict]) -> dict[int, list[str]]:
    """
    Steps are in the order they are performed, so their frames should move forward in time. The model
    sometimes attaches a frame from much later (e.g. a "save" screenshot taken minutes after, while the
    narrator explains something else). Taking every (step, frame) pair in time order, this keeps the
    largest set whose step numbers never go backwards, i.e. it drops the fewest frames needed to make
    time order and step order agree. A step left with no frames gets no screenshot rather than a
    misleading one. Modifies `steps` in place; returns the dropped frame ids by step number.
    """
    pairs = sorted(((frame_by_id[f]["timestamp"], i, f) for i, s in enumerate(steps) for f in s.frame_ids))
    ordered = _longest_ordered([i for _, i, _ in pairs])
    kept = {(i, f) for k, (_, i, f) in enumerate(pairs) if k in ordered}

    dropped = {}
    for i, step in enumerate(steps):
        keep = [f for f in step.frame_ids if (i, f) in kept]
        if keep == step.frame_ids:
            continue
        dropped[step.number] = [f for f in step.frame_ids if f not in keep]
        main = os.path.splitext(os.path.basename(step.main_frame_path or ""))[0]
        step.frame_ids = keep
        step.main_frame_path = frame_by_id[main if main in keep else keep[-1]]["path"] if keep else None
        step.time = format_timestamp(frame_by_id[keep[0]]["timestamp"]) if keep else ""
    return dropped


def make_windows(steps: list[OutlineStep], position: dict[str, int], max_frames: int) -> list[list[int]]:
    """
    Groups consecutive steps (by index) so each group's frames span at most `max_frames` observations,
    which is how much detail one refinement call receives.
    """
    windows: list[list[int]] = []
    span: list[int] = []  # positions of the frames cited by the current group
    for i, step in enumerate(steps):
        idx = [position[f] for f in step.frame_ids]
        wider = span + idx
        too_wide = bool(wider) and max(wider) - min(wider) + 1 > max_frames
        if windows and windows[-1] and not (too_wide or len(windows[-1]) >= MAX_STEPS_PER_WINDOW):
            windows[-1].append(i)
            span = wider
        else:
            windows.append([i])
            span = idx
    return windows


def structure_pdd(
    captions: list[dict],
    transcript: list[dict] | None,
    frames: list[dict],
    llm,
    max_frames_per_window: int = 30,
) -> tuple[PDD, dict]:
    """
    Builds the PDD in two passes so long recordings stay consistent:
      1. outline: one call sees the whole recording (compact observations + full narration) and decides
         the complete ordered list of steps, plus requirements and exceptions. Steps are decided once, so
         there are no duplicates or gaps at window boundaries.
      2. refine: one call per group of steps gets the detailed observations for those steps' frames and
         makes each instruction specific and picks its screenshot. It can't add, drop or reorder steps.
    Code then numbers the steps, takes their time from their first frame and maps ids to image paths.

    `llm` is a LangChain chat model (structured output is applied here).
    Returns the PDD and a report with the coverage checks.
    """
    transcript = transcript or []
    frame_by_id = {f["id"]: f for f in frames}
    position = {c["id"]: i for i, c in enumerate(captions)}
    invalid_refs: list[str] = []

    outline = cast(ProcessOutline, llm.with_structured_output(ProcessOutline).invoke([
        SystemMessage(content=OUTLINE_SYSTEM_PROMPT),
        HumanMessage(content=f"Screen observations:\n\n{_observations_text(captions, compact=True)}"
                             f"\n\nAudio narration:\n\n{_transcript_text(transcript)}"),
    ]))
    for step in outline.steps:
        step.frame_ids = _clean_ids(step.frame_ids, set(position), invalid_refs)
    framed_by_narration = _guess_frames_from_narration(outline.steps, captions)

    refine_llm = llm.with_structured_output(WindowRefinement)
    windows = make_windows(outline.steps, position, max_frames_per_window)
    steps: list[Step] = []
    fallbacks: list[int] = []

    for window in windows:
        cited = sorted({position[f] for i in window for f in outline.steps[i].frame_ids})
        if cited and cited[-1] - cited[0] + 1 <= max_frames_per_window:
            window_caps = captions[cited[0]:cited[-1] + 1]  # whole span, so uncited frames can be attached too
        else:
            window_caps = [captions[p] for p in cited][:max_frames_per_window]
        window_ids = {c["id"] for c in window_caps}

        refined = {}
        if window_caps:
            start, end = window_caps[0]["timestamp"], window_caps[-1]["timestamp"]
            narration = [t for t in transcript if t["end"] >= start - NARRATION_LEAD and t["start"] <= end + 5]
            numbered = "\n".join(
                f"{i + 1}. {outline.steps[i].instruction}  (first guess of frames: {outline.steps[i].frame_ids})"
                for i in window)
            result = cast(WindowRefinement, refine_llm.invoke([
                SystemMessage(content=REFINE_SYSTEM_PROMPT),
                HumanMessage(content=(
                    f"Process: {outline.process_name}\n\nSteps to refine:\n{numbered}\n\n"
                    f"Screen observations for this part:\n\n{_observations_text(window_caps)}\n\n"
                    f"Audio narration for this part:\n\n{_transcript_text(narration)}"
                )),
            ]))
            refined = {r.number: r for r in result.steps if r.number - 1 in window}

        for i in window:
            base = outline.steps[i]
            r = refined.get(i + 1)
            if r is None:
                fallbacks.append(i + 1)
                instruction, ids, main = base.instruction, base.frame_ids, None
            else:
                instruction = r.instruction
                ids = _clean_ids(r.frame_ids, window_ids, invalid_refs) or base.frame_ids
                main = r.main_frame_id.strip().upper()
            if main not in ids:
                if main and main not in window_ids:
                    invalid_refs.append(main)
                main = ids[-1] if ids else None  # the last state of the step is usually the most telling
            steps.append(Step(
                number=len(steps) + 1,
                time=format_timestamp(frame_by_id[ids[0]]["timestamp"]) if ids else "",
                instruction=instruction,
                short_label=base.short_label,
                frame_ids=ids,
                main_frame_path=frame_by_id[main]["path"] if main else None,
            ))

    out_of_order = enforce_chronology(steps, frame_by_id)

    pdd = PDD(
        process_name=outline.process_name,
        project_proposal=outline.project_proposal,
        as_is=steps,
        requirements=outline.requirements,
        business_exceptions=_dedupe_exceptions(outline.business_exceptions),
        system_exceptions=_dedupe_exceptions(outline.system_exceptions),
    )

    referenced = {i for s in steps for i in s.frame_ids}
    report = {
        "windows": len(windows),
        "steps": len(steps),
        "requirements": len(outline.requirements),
        "exceptions": len(pdd.business_exceptions) + len(pdd.system_exceptions),
        "steps_without_image": [s.number for s in steps if not s.main_frame_path],
        "steps_not_refined": fallbacks,
        "steps_framed_by_narration": framed_by_narration,
        "frames_dropped_out_of_order": out_of_order,
        "invalid_frame_refs": invalid_refs,
        "frames_referenced": len(referenced),
        "frames_not_used": [c["id"] for c in captions if c["id"] not in referenced],
    }
    return pdd, report
