import json
import os
import re
from difflib import SequenceMatcher
from typing import cast
from langchain_core.messages import HumanMessage, SystemMessage
from schemas import (ProcessModel, Step, ProcessOutline, OutlineStep, WindowRefinement, ExceptionItem, KeyName,
                     format_timestamp, repair_model)
from prompts.structure_prompt import OUTLINE_SYSTEM_PROMPT, REFINE_SYSTEM_PROMPT

# Narration starting this many seconds before a window is still sent with it, since people often
# explain an action right before doing it.
NARRATION_LEAD = 30.0
# How long after a step is narrated its frames are searched for, when the outline attached none.
NARRATION_WINDOW = 30.0
MAX_STEPS_PER_WINDOW = 10
# How many characters a misreading may differ from the correct name by, at most, and as a share of its length
# (so short names like "SAP" and "SAP BC" aren't taken for each other).
MAX_MISREAD_CHARS = 3
MAX_MISREAD_SHARE = 0.15


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


def _frame_range(step: OutlineStep, captions: list[dict], position: dict[str, int], invalid: list[str]) -> list[str]:
    """The ids from the step's first to its last frame. An unknown id is recorded and the other end used alone."""
    ends = []
    for raw in (step.first_frame_id, step.last_frame_id):
        if not raw:
            continue
        fid = raw.strip().upper()
        if fid in position:
            ends.append(position[fid])
        else:
            invalid.append(raw)
    if not ends:
        return []
    return [c["id"] for c in captions[min(ends):max(ends) + 1]]


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


def measure_durations(steps: list[Step], frame_by_id: dict[str, dict]) -> None:
    """
    Sets each step's start (its first frame) and duration (until the next step with frames starts; the
    last one ends at its last frame). Steps without frames get neither, and the time spent on them falls
    in the previous step's duration. Expects frames already in chronological order (enforce_chronology).
    """
    timed = [s for s in steps if s.frame_ids]
    for step, following in zip(timed, timed[1:] + [None]):
        step.start_seconds = frame_by_id[step.frame_ids[0]]["timestamp"]
        end = (frame_by_id[following.frame_ids[0]]["timestamp"] if following
               else frame_by_id[step.frame_ids[-1]]["timestamp"])
        step.duration_seconds = round(end - step.start_seconds, 2)


def _key_names_text(key_names: list[KeyName]) -> str:
    if not key_names:
        return ""
    return "Correct spelling of names (use exactly these):\n" + "\n".join(f"- {k.name}" for k in key_names) + "\n\n"


def is_misreading(variant: str, name: str) -> bool:
    """True if `variant` differs from `name` by a few characters (see MAX_MISREAD_CHARS)."""
    changed = sum(max(i2 - i1, j2 - j1)
                  for op, i1, i2, j1, j2 in SequenceMatcher(None, variant, name, autojunk=False).get_opcodes()
                  if op != "equal")
    return 0 < changed <= min(MAX_MISREAD_CHARS, MAX_MISREAD_SHARE * len(name))


def apply_key_names(model: ProcessModel) -> dict[str, str]:
    """
    Captions misread small text differently from frame to frame (e.g. a file dated "5.5.26" read as
    "5.3.26" in some frames), so the same file ends up with two names in the document. The outline lists
    each name's correct spelling and the misreadings it saw; this replaces the misreadings everywhere.
    Returns the replacements made.
    """
    # Misreadings differ from the name by a character or two (e.g. "5.3.26" for "5.5.26", or text cut off
    # at the end). The model sometimes also lists different things as variants, such as another view
    # ("My Views"), or another file whose name has a word more ("Report.xlsx" and "Report - Afternoon.xlsx"),
    # so variants that differ by more are ignored. A variant contained in the correct name (e.g.
    # "Blocks Report" for "AP Blocks Report") would also match inside correct text, so it's left alone too.
    replacements = {v.strip(): k.name.strip() for k in model.key_names for v in k.variants
                    if len(v.strip()) >= 3 and v.strip() not in k.name and is_misreading(v.strip(), k.name.strip())}
    return replace_names(model, replacements)


def replace_names(model: ProcessModel, replacements: dict[str, str]) -> dict[str, str]:
    """Replaces each key of `replacements` by its value in all the model's text; returns those it found."""
    if not replacements:
        return {}
    # Longest first, so a variant that contains a shorter one is replaced whole.
    pattern = re.compile("|".join(re.escape(v) for v in sorted(replacements, key=len, reverse=True)))
    used: dict[str, str] = {}

    # When the model hedged between two readings ("'5.5.26.xlsx' or '5.3.26.xlsx'"), replacing one leaves
    # the same name twice; those are collapsed to one.
    targets = list(dict.fromkeys(replacements.values()))
    repeated = re.compile("|".join(
        rf"(?P<q{i}>['\"]?){re.escape(name)}(?P=q{i})(?: or | ou | o |, |/| and | e | y )(?P=q{i}){re.escape(name)}(?P=q{i})"
        for i, name in enumerate(targets)))

    def fix(text: str) -> str:
        def sub(m):
            used[m.group(0)] = replacements[m.group(0)]
            return replacements[m.group(0)]

        def once(m):
            i, quote = next((int(k[1:]), v) for k, v in m.groupdict().items() if v is not None)
            return quote + targets[i] + quote
        return repeated.sub(once, pattern.sub(sub, text))

    model.process_name = fix(model.process_name)
    model.project_proposal = fix(model.project_proposal)
    for step in model.as_is:
        step.instruction, step.short_label, step.decision = fix(step.instruction), fix(step.short_label), fix(step.decision)
    for item in model.requirements:
        item.description = fix(item.description)
    for item in model.inputs:
        item.name, item.source = fix(item.name), fix(item.source)
    for item in model.business_exceptions + model.system_exceptions:
        item.action, item.parameters, item.action_to_be_taken = fix(item.action), fix(item.parameters), fix(item.action_to_be_taken)
    return used


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
    language: str | None = None,
    step_example: str | None = None,
) -> tuple[ProcessModel, dict]:
    """
    Builds the PDD in two passes so long recordings stay consistent:
      1. outline: one call sees the whole recording (compact observations + full narration) and decides
         the complete ordered list of steps, plus requirements and exceptions. Steps are decided once, so
         there are no duplicates or gaps at window boundaries.
      2. refine: one call per group of steps gets the detailed observations for those steps' frames and
         makes each instruction specific and picks its screenshot. It can't add, drop or reorder steps.
    Code then numbers the steps, takes their time from their first frame and maps ids to image paths,
    measures how long each step took in the recording, and fixes misread names using the outline's glossary.

    `llm` is a LangChain chat model (structured output is applied here). `language` (e.g. "Brazilian
    Portuguese", from a company template) is the language the text is written in; by default English.
    `step_example` is a step from the template, whose wording the instructions follow.
    Returns the process model and a report with the coverage checks.
    """
    transcript = transcript or []
    frame_by_id = {f["id"]: f for f in frames}
    position = {c["id"]: i for i, c in enumerate(captions)}
    invalid_refs: list[str] = []

    write_in = (f"\n\nWrite all text (process name, summary, steps, labels, decisions, requirements, exceptions) in "
                f"{language}. Names of applications, screens, files and buttons stay exactly as shown on screen."
                if language else "")
    if step_example:
        write_in += (f"\n\nWrite the step instructions in the same style as this example step from the company's "
                     f"documents (its wording, not its content): \"{step_example}\". This style replaces the "
                     "'You need to...' directive style above: one instruction per step, without a step number or "
                     "label in front (the document numbers the steps).")
    outline = repair_model(cast(ProcessOutline, llm.with_structured_output(ProcessOutline).invoke([
        SystemMessage(content=OUTLINE_SYSTEM_PROMPT + write_in),
        HumanMessage(content=f"Screen observations:\n\n{_observations_text(captions, compact=True)}"
                             f"\n\nAudio narration:\n\n{_transcript_text(transcript)}"),
    ])))
    for step in outline.steps:
        step.frame_ids = _frame_range(step, captions, position, invalid_refs)
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
            # A step spanning more frames than one call gets (a long stretch of a meeting on one screen) is
            # shown through frames spread evenly over its range, its first and last included.
            picks = sorted({cited[round(k * (len(cited) - 1) / (max_frames_per_window - 1))]
                            for k in range(max_frames_per_window)}) if cited else []
            window_caps = [captions[p] for p in picks]
        window_ids = {c["id"] for c in window_caps}

        refined = {}
        if window_caps:
            start, end = window_caps[0]["timestamp"], window_caps[-1]["timestamp"]
            narration = [t for t in transcript if t["end"] >= start - NARRATION_LEAD and t["start"] <= end + 5]
            numbered = "\n".join(
                f"{i + 1}. {outline.steps[i].instruction}  (first guess of frames: {outline.steps[i].frame_ids})"
                for i in window)
            result = repair_model(cast(WindowRefinement, refine_llm.invoke([
                SystemMessage(content=REFINE_SYSTEM_PROMPT + write_in),
                HumanMessage(content=(
                    f"Process: {outline.process_name}\n\n{_key_names_text(outline.key_names)}"
                    f"Steps to refine:\n{numbered}\n\n"
                    f"Screen observations for this part:\n\n{_observations_text(window_caps)}\n\n"
                    f"Audio narration for this part:\n\n{_transcript_text(narration)}"
                )),
            ])))
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
                application=base.application,
                decision=base.decision,
                frame_ids=ids,
                main_frame_path=frame_by_id[main]["path"] if main else None,
            ))

    out_of_order = enforce_chronology(steps, frame_by_id)
    measure_durations(steps, frame_by_id)

    pdd = ProcessModel(
        process_name=outline.process_name,
        project_proposal=outline.project_proposal,
        as_is=steps,
        inputs=outline.inputs,
        key_names=outline.key_names,
        requirements=outline.requirements,
        business_exceptions=_dedupe_exceptions(outline.business_exceptions),
        system_exceptions=_dedupe_exceptions(outline.system_exceptions),
    )

    names_fixed = apply_key_names(pdd)

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
        "names_fixed": names_fixed,
        "applications": pdd.applications,
        "decision_points": [s.number for s in pdd.decision_points],
        "recorded_seconds": pdd.recorded_seconds,
        "invalid_frame_refs": invalid_refs,
        "frames_referenced": len(referenced),
        "frames_not_used": [c["id"] for c in captions if c["id"] not in referenced],
    }
    return pdd, report
