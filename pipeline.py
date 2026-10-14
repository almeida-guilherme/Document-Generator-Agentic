import json
import operator
import os
import time
from datetime import datetime
from typing import Annotated, Callable, TypedDict
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.graph import StateGraph, START, END

from create_video import create_frames, caption_frame
from transcribe import transcribe_audio, has_audio, media_seconds
from structure import structure_pdd
from verify_names import verify_names
from render import render_docx
from schemas import FrameCaption, ProcessModel
from costs import usage_cost, WHISPER_PER_MINUTE

# Captioning sends every frame as an image, so it uses a cheap vision model. Structuring is text only and
# much smaller, so a stronger model costs little there and makes the biggest difference to the steps.
CAPTION_MODEL = os.getenv("PDD_MODEL", "gpt-4.1-mini")
STRUCTURE_MODEL = os.getenv("PDD_STRUCTURE_MODEL", "gpt-4.1")

# Each stage saves what it produced in the run folder. A stage whose file already exists loads it instead
# of running again, so an interrupted run continues where it stopped (see `--resume`).
FRAMES_FILE = "frames.json"
CAPTIONS_FILE = "captions.json"
TRANSCRIPT_FILE = "transcript.json"
MODEL_FILE = "process_model.json"
NAME_CHECKS_FILE = "name_checks.json"
REPORT_FILE = "report.json"


def new_run_dir(video_path: str, base_dir: str = "runs") -> str:
    """Each run gets its own folder, so frames from a previous video can never leak into this one."""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    run_dir = os.path.join(base_dir, f"{stem}-{datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(run_dir)
    return run_dir


def _load(run_dir: str, name: str):
    path = os.path.join(run_dir, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(run_dir: str, name: str, data) -> None:
    with open(os.path.join(run_dir, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_previous_run(previous_dir: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Reads the frames, captions and transcript of an earlier run so they don't have to be paid for again."""
    captions = _load(previous_dir, CAPTIONS_FILE)
    transcript = _load(previous_dir, TRANSCRIPT_FILE)
    if captions is None or transcript is None:
        raise FileNotFoundError(f"{previous_dir} has no {CAPTIONS_FILE} or {TRANSCRIPT_FILE}; was that run finished?")
    # Runs made before frames.json existed only have the images, named after their ids.
    frames = _load(previous_dir, FRAMES_FILE) or [
        {"id": c["id"], "timestamp": c["timestamp"], "path": os.path.join(previous_dir, "frames", f"{c['id']}.jpg")}
        for c in captions]
    if len(frames) != len(captions):
        raise ValueError(f"{previous_dir} was interrupted while captioning; continue it with --resume first.")
    return frames, captions, transcript


class PipelineState(TypedDict, total=False):
    video_path: str
    run_dir: str
    from_run: str | None
    frames: list[dict]
    captions: list[dict]
    transcript: list[dict]
    model: ProcessModel
    output_path: str
    # Every stage adds its own entries to the run report.
    report: Annotated[dict, operator.or_]


def build_graph(llm, structure_llm, transcribe: Callable, frame_options: dict, caption_width: int,
                max_frames_per_window: int):
    """
    The pipeline as a LangGraph graph. Today there is one input (a recording, captured fresh or reused
    from an earlier run) and one output (the .docx); reading an existing PDD and the ROI analysis are
    meant to be added as further nodes that produce or read the same ProcessModel.

        START ─┬─ extract_frames ─ caption ─ transcribe ─┬─ structure ─ verify_names ─ render ─ END
               └─ reuse_run ──────────────────────────────┘
    """

    def extract_frames(state: PipelineState) -> PipelineState:
        run_dir = state["run_dir"]
        frames = _load(run_dir, FRAMES_FILE)
        if frames is None:
            frames = create_frames(state["video_path"], output_dir=os.path.join(run_dir, "frames"), **frame_options)
            _save(run_dir, FRAMES_FILE, frames)
            print(f"[1/6] {len(frames)} frames kept")
        else:
            print(f"[1/6] {len(frames)} frames already extracted")
        return {"frames": frames, "report": {"frames_kept": len(frames)}}

    def caption(state: PipelineState) -> PipelineState:
        run_dir, frames = state["run_dir"], state["frames"]
        # Saved after every frame: captioning is the slowest and most expensive stage, so an interruption
        # (network error, rate limit, Ctrl+C) loses at most one frame.
        captions = _load(run_dir, CAPTIONS_FILE) or []
        if captions:
            print(f"      {len(captions)}/{len(frames)} frames already captioned")
        remaining = frames[len(captions):]
        caption_llm = llm.with_structured_output(FrameCaption) if remaining else None
        for n, frame in enumerate(remaining, len(captions) + 1):
            captions.append(caption_frame(frame, caption_llm, caption_width))
            _save(run_dir, CAPTIONS_FILE, captions)
            print(f"      captioned {n}/{len(frames)}", end="\r")
            time.sleep(1)
        print(f"[2/6] {len(captions)} frames captioned")
        return {"captions": captions, "report": {"caption_width": caption_width}}

    def transcribe_node(state: PipelineState) -> PipelineState:
        run_dir = state["run_dir"]
        transcript = _load(run_dir, TRANSCRIPT_FILE)
        report: dict = {}
        if transcript is None:
            transcript = transcribe(state["video_path"], audio_dir=os.path.join(run_dir, "audio"))
            _save(run_dir, TRANSCRIPT_FILE, transcript)
            if transcript and has_audio(state["video_path"]):
                report["transcribed_minutes"] = round(media_seconds(state["video_path"]) / 60, 2)
        print(f"[3/6] {len(transcript)} narration segments")
        return {"transcript": transcript, "report": {"narration_segments": len(transcript), **report}}

    def reuse_run(state: PipelineState) -> PipelineState:
        frames, captions, transcript = load_previous_run(state["from_run"])
        print(f"[1-3/6] reusing {len(frames)} frames, their captions and {len(transcript)} narration "
              f"segments from {state['from_run']}")
        _save(state["run_dir"], FRAMES_FILE, frames)
        _save(state["run_dir"], CAPTIONS_FILE, captions)
        _save(state["run_dir"], TRANSCRIPT_FILE, transcript)
        return {"frames": frames, "captions": captions, "transcript": transcript,
                "report": {"frames_kept": len(frames), "narration_segments": len(transcript)}}

    def structure(state: PipelineState) -> PipelineState:
        run_dir = state["run_dir"]
        saved = _load(run_dir, MODEL_FILE)
        if saved is not None:
            print("[4/6] process model already built")
            return {"model": ProcessModel.model_validate(saved)}
        model, structure_report = structure_pdd(state["captions"], state["transcript"], state["frames"],
                                                structure_llm, max_frames_per_window)
        _save(run_dir, MODEL_FILE, model.model_dump())
        print(f"[4/6] {len(model.as_is)} steps refined in {structure_report['windows']} part(s), "
              f"{structure_report['requirements']} requirements, {structure_report['exceptions']} exceptions")
        return {"model": model, "report": structure_report}

    def verify_names_node(state: PipelineState) -> PipelineState:
        run_dir, model = state["run_dir"], state["model"]
        checks = _load(run_dir, NAME_CHECKS_FILE)
        if checks is None:
            checks = verify_names(model, state["captions"], state["frames"], llm)
            _save(run_dir, MODEL_FILE, model.model_dump())
            _save(run_dir, NAME_CHECKS_FILE, checks)
        print(f"[5/6] {len(checks['names_verified'])} similar name(s) checked against the full-resolution frames, "
              f"{len(checks['names_fixed_by_vision'])} misreading(s) fixed")
        return {"model": model, "report": checks}

    def render(state: PipelineState) -> PipelineState:
        output_path, stats = render_docx(state["model"],
                                         output_path=os.path.join(state["run_dir"], "output", "PDD_final.docx"))
        print(f"[6/6] document written with {stats['images_inserted']} screenshots")
        return {"output_path": output_path, "report": stats}

    graph = StateGraph(PipelineState)
    graph.add_node("extract_frames", extract_frames)
    graph.add_node("caption", caption)
    graph.add_node("transcribe", transcribe_node)
    graph.add_node("reuse_run", reuse_run)
    graph.add_node("structure", structure)
    graph.add_node("verify_names", verify_names_node)
    graph.add_node("render", render)
    graph.add_conditional_edges(START, lambda s: "reuse_run" if s.get("from_run") else "extract_frames",
                                ["reuse_run", "extract_frames"])
    graph.add_edge("extract_frames", "caption")
    graph.add_edge("caption", "transcribe")
    graph.add_edge("transcribe", "structure")
    graph.add_edge("reuse_run", "structure")
    graph.add_edge("structure", "verify_names")
    graph.add_edge("verify_names", "render")
    graph.add_edge("render", END)
    return graph.compile()


def run_pdd_pipeline(
    video_path: str,
    run_dir: str,
    llm=None,
    structure_llm=None,
    transcribe=transcribe_audio,
    max_frames_per_window: int = 30,
    frame_options: dict | None = None,
    caption_width: int = 1366,
    from_run: str | None = None,
) -> tuple[str, dict]:
    """
    Runs the full PDD generation pipeline for a single video.

    Args:
        video_path: path to the input video file.
        run_dir: directory for this run's artifacts (frames, audio, output, report). If it holds a run that
            was interrupted, the stages already done are loaded instead of run again.
        llm: LangChain chat model for captioning frames; defaults to ChatOpenAI with PDD_MODEL.
        structure_llm: LangChain chat model for structuring; defaults to ChatOpenAI with PDD_STRUCTURE_MODEL.
        transcribe: function(video_path, audio_dir) -> transcript segments.
        caption_width: frames are shrunk to this width before captioning. OpenAI scales images so the
            short side is at most 768 px, so 1366 is the useful maximum for 16:9 recordings.
        from_run: an earlier run folder of the same video; its frames, captions and transcript are reused,
            so only structuring and rendering run again.

    Returns:
        path to the generated .docx file, and the run report (also saved as report.json).
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    llm = llm or ChatOpenAI(model=CAPTION_MODEL, max_retries=5)
    # Temperature 0 so two runs over the same captions give (nearly) the same steps.
    structure_llm = structure_llm or ChatOpenAI(model=STRUCTURE_MODEL, temperature=0, max_retries=5)
    graph = build_graph(llm, structure_llm, transcribe, frame_options or {}, caption_width, max_frames_per_window)

    report: dict = {"video": video_path, "caption_model": getattr(llm, "model_name", None),
                    "structure_model": getattr(structure_llm, "model_name", None), "reused_run": from_run}
    with get_usage_metadata_callback() as usage:
        state = graph.invoke({"video_path": video_path, "run_dir": run_dir, "from_run": from_run, "report": report})

    report = state["report"]
    token_cost, unknown = usage_cost(usage.usage_metadata)
    report["tokens"] = sum(u.get("total_tokens", 0) for u in usage.usage_metadata.values())
    report["tokens_by_model"] = {m: u.get("total_tokens", 0) for m, u in usage.usage_metadata.items()}
    report["transcription_cost_usd"] = round(report.get("transcribed_minutes", 0) * WHISPER_PER_MINUTE, 4)
    report["cost_usd"] = round(token_cost + report["transcription_cost_usd"], 4)
    # The price table only knows some models; say so instead of silently under-reporting.
    report["models_without_price"] = unknown

    # On a resumed run, keep what earlier attempts measured (e.g. frames) and add this attempt's cost.
    previous = _load(run_dir, REPORT_FILE) or {}
    if previous:
        report["cost_usd"] = round(report["cost_usd"] + previous.get("cost_usd", 0), 4)
        report["transcription_cost_usd"] += previous.get("transcription_cost_usd", 0)
        report["tokens"] += previous.get("tokens", 0)
        for m, n in previous.get("tokens_by_model", {}).items():
            report["tokens_by_model"][m] = report["tokens_by_model"].get(m, 0) + n
        report = {**previous, **report}
    _save(run_dir, REPORT_FILE, report)
    return state["output_path"], report


def print_report(report: dict):
    print("\n--- Run report ---")
    print(f"Frames kept: {report['frames_kept']} | used by steps: {report.get('frames_referenced', '?')} "
          f"| not used: {len(report.get('frames_not_used', []))}")
    print(f"Steps: {report.get('steps', '?')} | screenshots inserted: {report['images_inserted']}")
    if "applications" in report:
        print(f"Applications: {', '.join(report['applications']) or '-'} | decision points at steps: "
              f"{report['decision_points'] or '-'}")
    if report.get("requirements") is not None:
        print(f"Requirements: {report['requirements']} | exceptions: {report['exceptions']}")
    if report.get("names_fixed") or report.get("names_fixed_by_vision"):
        print(f"Misread names corrected: {report.get('names_fixed', {}) | report.get('names_fixed_by_vision', {})}")
    if report.get("steps_not_refined"):
        print(f"WARNING: steps kept as outlined (refinement didn't return them): {report['steps_not_refined']}")
    if report.get("steps_framed_by_narration"):
        print(f"Steps whose frames were found from the narration time: {report['steps_framed_by_narration']}")
    if report.get("frames_dropped_out_of_order"):
        print(f"Frames dropped for being out of time order, by step: {report['frames_dropped_out_of_order']}")
    if report.get("steps_without_image"):
        print(f"WARNING: steps without a screenshot: {report['steps_without_image']}")
    if report.get("invalid_frame_refs"):
        print(f"WARNING: the model cited unknown frame ids (ignored): {report['invalid_frame_refs']}")
    if not report["flowchart"]:
        print("WARNING: flowchart not generated (is Graphviz installed? sudo apt install graphviz)")
    print(f"Tokens: {report['tokens']} {report['tokens_by_model']} | Cost: ${report['cost_usd']:.4f} "
          f"(transcription ${report['transcription_cost_usd']:.4f})")
    if report["models_without_price"]:
        print(f"WARNING: cost excludes models with no known price (add them to costs.py): "
              f"{report['models_without_price']}")
    print("------------------")
