import contextvars
import functools
import json
import shutil
import operator
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Annotated, Callable, TypedDict
from langchain_openai import ChatOpenAI
from openai import OpenAI
from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.graph import StateGraph, START, END

from create_video import create_frames, caption_frame
from transcribe import transcribe_audio, has_audio, media_seconds
from structure import structure_pdd
from verify_names import verify_names
from render import render_docx
from render_template import render_template
from schemas import FrameCaption, ProcessModel, repair_model
from template import TemplateAnalysis, TemplateFill, analyze_template, fill_template, body_blocks, normalize_fill
from costs import usage_cost, WHISPER_PER_MINUTE

# Captioning sends every frame as an image, so it uses a cheap vision model. Structuring is text only and
# much smaller, so a stronger model costs little there and makes the biggest difference to the steps.
CAPTION_MODEL = os.getenv("PDD_MODEL", "gpt-4.1-mini")
STRUCTURE_MODEL = os.getenv("PDD_STRUCTURE_MODEL", "gpt-4.1")
CAPTION_CONCURRENCY = int(os.getenv("PDD_CAPTION_CONCURRENCY", "6"))

# Each stage saves what it produced in the run folder. A stage whose file already exists loads it instead
# of running again, so an interrupted run continues where it stopped (see `--resume`).
FRAMES_FILE = "frames.json"
CAPTIONS_FILE = "captions.json"
TRANSCRIPT_FILE = "transcript.json"
MODEL_FILE = "process_model.json"
NAME_CHECKS_FILE = "name_checks.json"
REPORT_FILE = "report.json"
# A run keeps its own copy of the template it is written into and of the template's analysis.
TEMPLATE_FILE = "template.docx"
TEMPLATE_ANALYSIS_FILE = "template_analysis.json"
TEMPLATE_FILL_FILE = "template_fill.json"
# Pidi's own template, used when no company template is given. Its analysis was checked by hand and ships
# with it, so it is never analyzed again.
DEFAULT_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "pidi.docx")
DEFAULT_ANALYSIS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "pidi.analysis.json")


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
    template_path: str | None
    recording_name: str | None
    analysis: TemplateAnalysis
    fill: TemplateFill
    output_path: str
    # Every stage adds its own entries to the run report.
    report: Annotated[dict, operator.or_]


# Stages in the order they run, for progress displays ("reuse_run" replaces extract_frames to transcribe):
# with Pidi's template, with a company template (analyzed first) and in the standard layout (no template).
STAGES = ["extract_frames", "caption", "transcribe", "structure", "verify_names", "fill_template", "render"]
TEMPLATE_STAGES = ["analyze_template", *STAGES]
STANDARD_STAGES = [s for s in STAGES if s != "fill_template"]


def stages_for(company_template: bool) -> list[str]:
    return TEMPLATE_STAGES if company_template else STAGES


def console_progress(stage: str, message: str, done: bool, stages: list[str] = STAGES) -> None:
    """Default progress display: "[n/6] message", with in-progress lines overwritten in place."""
    if stage == "reuse_run":
        first = stages.index("extract_frames") + 1
        number = f"{first}-{first + 2}"
    else:
        number = str(stages.index(stage) + 1)
    line = f"[{number}/{len(stages)}] {message}"
    print(f"{line:<100}", end="\n" if done else "\r", flush=True)


def build_graph(llm, structure_llm, transcribe: Callable, frame_options: dict, caption_width: int,
                max_frames_per_window: int, progress: Callable[[str, str, bool], None] = console_progress):
    """
    The pipeline as a LangGraph graph. `progress(stage, message, done)` is called as stages start, advance
    and finish (stage is one of TEMPLATE_STAGES or "reuse_run"). The input is a recording (captured fresh
    or reused from an earlier run) and optionally a company template; the output is the .docx, in the
    standard layout or written into the template. The ROI analysis is meant to be added as a further node
    that reads the same ProcessModel.

        START ─┬─ analyze_template ─┬─┬─ extract_frames ─ caption ─ transcribe ─┬─ structure ─ verify_names ─┬─ fill_template ─┬─ render ─ END
               └────────────────────┘ └─ reuse_run ──────────────────────────────┘                            └─────────────────┘

    analyze_template runs only for a company template not analyzed yet (Pidi's template ships analyzed);
    fill_template is skipped only in the standard layout.
    """

    def analyze_template_node(state: PipelineState) -> PipelineState:
        run_dir = state["run_dir"]
        saved = _load(run_dir, TEMPLATE_ANALYSIS_FILE)
        if saved is not None:
            progress("analyze_template", "Template already analyzed", True)
            return {"analysis": TemplateAnalysis.model_validate(saved)}
        progress("analyze_template", "Reading the template: what to keep, remove and fill", False)
        analysis = analyze_template(state["template_path"], structure_llm)
        _save(run_dir, TEMPLATE_ANALYSIS_FILE, analysis.model_dump())
        removed = sum(1 for b in analysis.blocks if b.action == "remove")
        filled = sum(1 for b in analysis.blocks if b.action not in ("keep", "remove"))
        progress("analyze_template", f"Template in {analysis.language}: {filled} parts to fill, {removed} removed "
                                     "(instructions and examples)", True)
        return {"analysis": analysis}

    def extract_frames(state: PipelineState) -> PipelineState:
        run_dir = state["run_dir"]
        frames = _load(run_dir, FRAMES_FILE)
        if frames is None:
            progress("extract_frames", "Looking for screen changes in the video", False)
            frames = create_frames(state["video_path"], output_dir=os.path.join(run_dir, "frames"), **frame_options)
            _save(run_dir, FRAMES_FILE, frames)
            progress("extract_frames", f"{len(frames)} frames kept", True)
        else:
            progress("extract_frames", f"{len(frames)} frames already extracted", True)
        return {"frames": frames, "report": {"frames_kept": len(frames)}}

    def caption(state: PipelineState) -> PipelineState:
        run_dir, frames = state["run_dir"], state["frames"]
        # Saved after every frame: captioning is the slowest and most expensive stage, so an interruption
        # (network error, rate limit, Ctrl+C) loses at most one frame.
        captions = _load(run_dir, CAPTIONS_FILE) or []
        if captions:
            progress("caption", f"{len(captions)}/{len(frames)} frames already captioned", False)
        remaining = frames[len(captions):]
        caption_llm = llm.with_structured_output(FrameCaption) if remaining else None
        # Frames are captioned independently, so several requests run at once (a 40-minute recording has
        # over a thousand frames). map() yields results in frame order, so the saved file is always a prefix.
        # Each call runs in a copy of this thread's context, where the token usage callback lives.
        contexts = [contextvars.copy_context() for _ in remaining]
        with ThreadPoolExecutor(CAPTION_CONCURRENCY) as pool:
            results = pool.map(lambda ctx, frame: ctx.run(caption_frame, frame, caption_llm, caption_width),
                               contexts, remaining)
            for n, result in enumerate(results, len(captions) + 1):
                captions.append(result)
                _save(run_dir, CAPTIONS_FILE, captions)
                progress("caption", f"Captioned {n}/{len(frames)} frames", False)
        progress("caption", f"{len(captions)} frames captioned", True)
        return {"captions": captions, "report": {"caption_width": caption_width}}

    def transcribe_node(state: PipelineState) -> PipelineState:
        run_dir = state["run_dir"]
        transcript = _load(run_dir, TRANSCRIPT_FILE)
        report: dict = {}
        if transcript is None:
            progress("transcribe", "Transcribing the narration", False)
            transcript = transcribe(state["video_path"], audio_dir=os.path.join(run_dir, "audio"))
            _save(run_dir, TRANSCRIPT_FILE, transcript)
            if transcript and has_audio(state["video_path"]):
                report["transcribed_minutes"] = round(media_seconds(state["video_path"]) / 60, 2)
        progress("transcribe", f"{len(transcript)} narration segments", True)
        return {"transcript": transcript, "report": {"narration_segments": len(transcript), **report}}

    def reuse_run(state: PipelineState) -> PipelineState:
        frames, captions, transcript = load_previous_run(state["from_run"])
        progress("reuse_run", f"Reusing {len(frames)} frames, their captions and {len(transcript)} narration "
                              f"segments from {state['from_run']}", True)
        _save(state["run_dir"], FRAMES_FILE, frames)
        _save(state["run_dir"], CAPTIONS_FILE, captions)
        _save(state["run_dir"], TRANSCRIPT_FILE, transcript)
        return {"frames": frames, "captions": captions, "transcript": transcript,
                "report": {"frames_kept": len(frames), "narration_segments": len(transcript)}}

    def structure(state: PipelineState) -> PipelineState:
        run_dir = state["run_dir"]
        saved = _load(run_dir, MODEL_FILE)
        if saved is not None:
            progress("structure", "Process model already built", True)
            return {"model": repair_model(ProcessModel.model_validate(saved))}
        progress("structure", "Working out the process steps", False)
        analysis = state.get("analysis")
        model, structure_report = structure_pdd(state["captions"], state["transcript"], state["frames"],
                                                structure_llm, max_frames_per_window,
                                                language=analysis.language if analysis else None,
                                                step_example=_example_step(state.get("template_path"), analysis))
        _save(run_dir, MODEL_FILE, model.model_dump())
        progress("structure", f"{len(model.as_is)} steps refined in {structure_report['windows']} part(s), "
                              f"{structure_report['requirements']} requirements, {structure_report['exceptions']} exceptions",
                 True)
        return {"model": model, "report": structure_report}

    def verify_names_node(state: PipelineState) -> PipelineState:
        run_dir, model = state["run_dir"], state["model"]
        checks = _load(run_dir, NAME_CHECKS_FILE)
        if checks is None:
            progress("verify_names", "Checking similar names against the full-resolution frames", False)
            checks = verify_names(model, state["captions"], state["frames"], llm)
            _save(run_dir, MODEL_FILE, model.model_dump())
            _save(run_dir, NAME_CHECKS_FILE, checks)
        progress("verify_names", f"{len(checks['names_verified'])} similar name(s) checked against the full-resolution "
                                 f"frames, {len(checks['names_fixed_by_vision'])} misreading(s) fixed", True)
        return {"model": model, "report": checks}

    def fill_template_node(state: PipelineState) -> PipelineState:
        run_dir = state["run_dir"]
        saved = _load(run_dir, TEMPLATE_FILL_FILE)
        if saved is not None:
            progress("fill_template", "Template content already written", True)
            fill = TemplateFill.model_validate(saved)
            normalize_fill(fill)  # idempotent; applies clean-ups added since the file was saved
            return {"fill": fill}
        progress("fill_template", "Writing the template's sections for this process", False)
        fill = fill_template(state["template_path"], state["analysis"], state["model"], state["transcript"],
                             structure_llm, recording_name=state.get("recording_name"))
        _save(run_dir, TEMPLATE_FILL_FILE, fill.model_dump())
        unknown = sum(1 for p in fill.placeholders if p.value is None)
        progress("fill_template", f"{len(fill.blocks)} template parts written, {unknown} placeholder(s) left for "
                                  "the author", True)
        return {"fill": fill}

    def render(state: PipelineState) -> PipelineState:
        progress("render", "Writing the document", False)
        output_path = os.path.join(state["run_dir"], "output", "PDD_final.docx")
        if state.get("analysis"):
            output_path, stats = render_template(state["template_path"], state["analysis"], state["fill"],
                                                 state["model"], output_path)
        else:
            output_path, stats = render_docx(state["model"], output_path=output_path)
        progress("render", f"Document written with {stats['images_inserted']} screenshots", True)
        return {"output_path": output_path, "report": stats}

    graph = StateGraph(PipelineState)
    graph.add_node("analyze_template", analyze_template_node)
    graph.add_node("fill_template", fill_template_node)
    graph.add_node("extract_frames", extract_frames)
    graph.add_node("caption", caption)
    graph.add_node("transcribe", transcribe_node)
    graph.add_node("reuse_run", reuse_run)
    graph.add_node("structure", structure)
    graph.add_node("verify_names", verify_names_node)
    graph.add_node("render", render)
    def recording_source(state: PipelineState) -> str:
        return "reuse_run" if state.get("from_run") else "extract_frames"

    graph.add_conditional_edges(START, lambda s: "analyze_template" if s.get("template_path") and not s.get("analysis")
                                else recording_source(s), ["analyze_template", "reuse_run", "extract_frames"])
    graph.add_conditional_edges("analyze_template", recording_source, ["reuse_run", "extract_frames"])
    graph.add_edge("extract_frames", "caption")
    graph.add_edge("caption", "transcribe")
    graph.add_edge("transcribe", "structure")
    graph.add_edge("reuse_run", "structure")
    graph.add_edge("structure", "verify_names")
    graph.add_conditional_edges("verify_names", lambda s: "fill_template" if s.get("template_path") else "render",
                                ["fill_template", "render"])
    graph.add_edge("fill_template", "render")
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
    progress: Callable[[str, str, bool], None] | None = None,
    template_path: str | None = None,
    api_key: str | None = None,
    recording_name: str | None = None,
    standard_layout: bool = False,
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
        progress: called with (stage, message, done) as the run advances; prints to the console by default.
        template_path: a company PDD template (.docx) to write the document into, instead of Pidi's
            template. It is copied into the run folder (so is its analysis), and a run folder that has one
            uses it when resumed.
        api_key: the OpenAI key the default models and transcription use; by default OPENAI_API_KEY.
        recording_name: the recording's file name as shown in the document; by default video_path's.
        standard_layout: without a template, write the document in the standard layout (render.py)
            instead of Pidi's template.

    Returns:
        path to the generated .docx file, and the run report (also saved as report.json).
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    template_path = use_template(run_dir, template_path)
    if template_path is None and not standard_layout:
        template_path = use_template(run_dir, DEFAULT_TEMPLATE)
        shutil.copyfile(DEFAULT_ANALYSIS, os.path.join(run_dir, TEMPLATE_ANALYSIS_FILE))
    saved = _load(run_dir, TEMPLATE_ANALYSIS_FILE) if template_path else None
    analysis = TemplateAnalysis.model_validate(saved) if saved is not None else None
    if progress is None:
        stages = STANDARD_STAGES if template_path is None else STAGES if analysis else TEMPLATE_STAGES
        progress = lambda stage, message, done: console_progress(stage, message, done, stages)  # noqa: E731
    llm = llm or ChatOpenAI(model=CAPTION_MODEL, max_retries=5, api_key=api_key)
    # Temperature 0 so two runs over the same captions give (nearly) the same steps.
    structure_llm = structure_llm or ChatOpenAI(model=STRUCTURE_MODEL, temperature=0, max_retries=5, api_key=api_key)
    if api_key and transcribe is transcribe_audio:
        transcribe = functools.partial(transcribe_audio, client=OpenAI(api_key=api_key))
    graph = build_graph(llm, structure_llm, transcribe, frame_options or {}, caption_width, max_frames_per_window,
                        progress)

    report: dict = {"video": video_path, "caption_model": getattr(llm, "model_name", None),
                    "structure_model": getattr(structure_llm, "model_name", None), "reused_run": from_run}
    initial: PipelineState = {"video_path": video_path, "run_dir": run_dir, "from_run": from_run,
                              "template_path": template_path, "report": report,
                              "recording_name": recording_name or os.path.basename(video_path)}
    if analysis is not None:
        initial["analysis"] = analysis
    with get_usage_metadata_callback() as usage:
        state = graph.invoke(initial)

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


def use_template(run_dir: str, template_path: str | None) -> str | None:
    """The run's own copy of the template: copied in on the first run, found there when resumed."""
    own = os.path.join(run_dir, TEMPLATE_FILE)
    if template_path and os.path.abspath(template_path) != os.path.abspath(own):
        if not os.path.isfile(template_path):
            raise FileNotFoundError(f"Template not found: {template_path}")
        if os.path.exists(own) and _load(run_dir, TEMPLATE_ANALYSIS_FILE) is not None:
            raise ValueError(f"{run_dir} already has a template; resume it without --template.")
        shutil.copyfile(template_path, own)
    return own if os.path.exists(own) else None


def _example_step(template_path: str | None, analysis: TemplateAnalysis | None) -> str | None:
    """The text of the template's example step, whose wording the generated steps follow."""
    if not template_path or not analysis or analysis.step_format.example_step_index is None:
        return None
    from docx import Document
    from docx.text.paragraph import Paragraph
    doc = Document(template_path)
    return Paragraph(body_blocks(doc)[analysis.step_format.example_step_index], doc).text.strip() or None


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
    if report.get("template"):
        print(f"Template: {report['template']} | parts left for the author (highlighted): {report['missing_marks']}")
    if not report["flowchart"]:
        print("WARNING: flowchart not generated (is Graphviz installed? sudo apt install graphviz)")
    print(f"Tokens: {report['tokens']} {report['tokens_by_model']} | Cost: ${report['cost_usd']:.4f} "
          f"(transcription ${report['transcription_cost_usd']:.4f})")
    if report["models_without_price"]:
        print(f"WARNING: cost excludes models with no known price (add them to costs.py): "
              f"{report['models_without_price']}")
    print("------------------")
