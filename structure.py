import json
from typing import cast
from langchain_core.messages import HumanMessage, SystemMessage
from schemas import PDD, Step, ProcessOverview, WindowResult, ExceptionItem, format_timestamp
from prompts.structure_prompt import OVERVIEW_SYSTEM_PROMPT, STEPS_SYSTEM_PROMPT

# Narration starting this many seconds before a window is still sent with it, since people often
# explain an action right before doing it.
NARRATION_LEAD = 30.0


def _observations_text(captions: list[dict], compact: bool = False) -> str:
    if compact:
        rows = [{"id": c["id"], "t": c["timestamp"], "screen": c["screen_or_system"], "action": c["observed_action"]}
                for c in captions]
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    return json.dumps(captions, ensure_ascii=False, indent=2)


def _transcript_text(transcript: list[dict]) -> str:
    if not transcript:
        return "(no narration detected)"
    return "\n".join(f"[{t['start']:.1f}s] {t['text']}" for t in transcript)


def make_windows(captions: list[dict], max_frames: int) -> list[list[dict]]:
    return [captions[i:i + max_frames] for i in range(0, len(captions), max_frames)] or [[]]


def _dedupe_exceptions(items: list[ExceptionItem]) -> list[ExceptionItem]:
    seen, result = set(), []
    for item in items:
        key = item.name.strip().lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def structure_pdd(
    captions: list[dict],
    transcript: list[dict] | None,
    frames: list[dict],
    llm,
    max_frames_per_window: int = 30,
) -> tuple[PDD, dict]:
    """
    Builds the PDD in parts so long recordings don't get squeezed into one LLM answer:
      1. one call reads a compact view of the whole recording and decides name, proposal and goal;
      2. one call per window of observations writes that window's steps, citing frame ids;
      3. code numbers the steps, takes their time from their first frame and resolves ids to image paths.

    `llm` is a LangChain chat model (structured output is applied here).
    Returns the PDD and a report with the coverage checks.
    """
    transcript = transcript or []
    frame_by_id = {f["id"]: f for f in frames}

    overview = cast(ProcessOverview, llm.with_structured_output(ProcessOverview).invoke([
        SystemMessage(content=OVERVIEW_SYSTEM_PROMPT),
        HumanMessage(content=f"Screen observations:\n\n{_observations_text(captions, compact=True)}"
                             f"\n\nAudio narration:\n\n{_transcript_text(transcript)}"),
    ]))

    steps_llm = llm.with_structured_output(WindowResult)
    windows = make_windows(captions, max_frames_per_window)
    steps: list[Step] = []
    business, system = [], []
    invalid_refs: list[str] = []

    for w, window in enumerate(windows):
        if not window:
            continue
        start = window[0]["timestamp"]
        end = windows[w + 1][0]["timestamp"] if w + 1 < len(windows) else float("inf")
        narration = [t for t in transcript if t["end"] >= start - NARRATION_LEAD and t["start"] < end]
        window_ids = {c["id"] for c in window}
        previous = "\n".join(f"{s.number}. {s.instruction}" for s in steps[-3:]) or "(this is the first part)"

        result = cast(WindowResult, steps_llm.invoke([
            SystemMessage(content=STEPS_SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Process: {overview.process_name}\nGoal: {overview.goal}\n\n"
                f"Part {w + 1} of {len(windows)}.\n\nLast steps of the previous part:\n{previous}\n\n"
                f"Screen observations for this part:\n\n{_observations_text(window)}\n\n"
                f"Audio narration for this part:\n\n{_transcript_text(narration)}"
            )),
        ]))

        for draft in result.steps:
            valid = [i for i in dict.fromkeys(fid.strip().upper() for fid in draft.frame_ids) if i in window_ids]
            invalid_refs += [i for i in draft.frame_ids if i.strip().upper() not in window_ids]
            if valid:
                time = format_timestamp(frame_by_id[valid[0]]["timestamp"])
            else:
                time = format_timestamp(start)
            steps.append(Step(
                number=len(steps) + 1,
                time=time,
                instruction=draft.instruction,
                short_label=draft.short_label,
                frame_ids=valid,
                frame_paths=[frame_by_id[i]["path"] for i in valid],
            ))
        business += result.business_exceptions
        system += result.system_exceptions

    pdd = PDD(
        process_name=overview.process_name,
        project_proposal=overview.project_proposal,
        as_is=steps,
        business_exceptions=_dedupe_exceptions(business),
        system_exceptions=_dedupe_exceptions(system),
    )

    referenced = {i for s in steps for i in s.frame_ids}
    report = {
        "windows": len([w for w in windows if w]),
        "steps": len(steps),
        "steps_without_image": [s.number for s in steps if not s.frame_ids],
        "invalid_frame_refs": invalid_refs,
        "frames_referenced": len(referenced),
        "frames_not_used": [c["id"] for c in captions if c["id"] not in referenced],
    }
    return pdd, report
