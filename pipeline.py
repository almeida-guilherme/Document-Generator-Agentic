import json
import os
import time
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_community.callbacks import get_openai_callback
from langchain_community.callbacks.openai_info import MODEL_COST_PER_1K_TOKENS

from create_video import create_frames, caption_frame
from transcribe import transcribe_audio
from structure import structure_pdd
from render import render_docx
from schemas import FrameCaption

# Captioning sends every frame as an image, so it uses a cheap vision model. Structuring is text only and
# much smaller, so a stronger model costs little there and makes the biggest difference to the steps.
CAPTION_MODEL = os.getenv("PDD_MODEL", "gpt-4.1-mini")
STRUCTURE_MODEL = os.getenv("PDD_STRUCTURE_MODEL", "gpt-4.1")


def new_run_dir(video_path: str, base_dir: str = "runs") -> str:
    """Each run gets its own folder, so frames from a previous video can never leak into this one."""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    run_dir = os.path.join(base_dir, f"{stem}-{datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(run_dir)
    return run_dir


def load_previous_run(previous_dir: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Reads the frames, captions and transcript of an earlier run so they don't have to be paid for again."""
    with open(os.path.join(previous_dir, "captions.json"), encoding="utf-8") as f:
        captions = json.load(f)
    transcript_path = os.path.join(previous_dir, "transcript.json")
    if not os.path.exists(transcript_path):
        raise FileNotFoundError(f"{transcript_path} is missing; that run predates saved transcripts.")
    with open(transcript_path, encoding="utf-8") as f:
        transcript = json.load(f)
    frames = [{"id": c["id"], "timestamp": c["timestamp"],
               "path": os.path.join(previous_dir, "frames", f"{c['id']}.jpg")} for c in captions]
    return frames, captions, transcript


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
        run_dir: empty directory for this run's artifacts (frames, audio, output, report).
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
    structure_llm = structure_llm or ChatOpenAI(model=STRUCTURE_MODEL, max_retries=5)
    report: dict = {"video": video_path, "caption_model": getattr(llm, "model_name", None),
                    "structure_model": getattr(structure_llm, "model_name", None), "reused_run": from_run,
                    "caption_width": None if from_run else caption_width}

    with get_openai_callback() as cb, get_usage_metadata_callback() as usage:
        if from_run:
            frames, captions, transcript = load_previous_run(from_run)
            report["frames_kept"] = len(frames)
            report["narration_segments"] = len(transcript)
            print(f"[1-2/4] reusing {len(frames)} frames, their captions and {len(transcript)} narration "
                  f"segments from {from_run}")
        else:
            # 1. Frames + captioning
            frames = create_frames(video_path, output_dir=os.path.join(run_dir, "frames"), **(frame_options or {}))
            report["frames_kept"] = len(frames)
            print(f"[1/4] {len(frames)} frames kept")

            caption_llm = llm.with_structured_output(FrameCaption)
            captions = []
            for n, frame in enumerate(frames, 1):
                captions.append(caption_frame(frame, caption_llm, caption_width))
                print(f"      captioned {n}/{len(frames)}", end="\r")
                time.sleep(1)
            print()

            # 2. Audio + transcription
            transcript = transcribe(video_path, audio_dir=os.path.join(run_dir, "audio"))
            report["narration_segments"] = len(transcript)
            print(f"[2/4] {len(transcript)} narration segments")

        # 3. Structuring
        pdd, structure_report = structure_pdd(captions, transcript, frames, structure_llm, max_frames_per_window)
        report.update(structure_report)
        print(f"[3/4] {len(pdd.as_is)} steps refined in {structure_report['windows']} part(s), "
              f"{structure_report['requirements']} requirements, {structure_report['exceptions']} exceptions")

        # 4. Document generation
        output_path, render_stats = render_docx(pdd, output_path=os.path.join(run_dir, "output", "PDD_final.docx"))
        report.update(render_stats)
        print(f"[4/4] document written with {render_stats['images_inserted']} screenshots")

        report["tokens"] = cb.total_tokens
        report["cost_usd"] = round(cb.total_cost, 4)
        report["tokens_by_model"] = {m: u.get("total_tokens", 0) for m, u in usage.usage_metadata.items()}
        # The cost table only knows some models; say so instead of silently under-reporting.
        report["models_without_price"] = [m for m in report["tokens_by_model"] if m not in MODEL_COST_PER_1K_TOKENS]

    with open(os.path.join(run_dir, "captions.json"), "w", encoding="utf-8") as f:
        json.dump(captions, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "pdd.json"), "w", encoding="utf-8") as f:
        f.write(pdd.model_dump_json(indent=2))
    with open(os.path.join(run_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return output_path, report


def print_report(report: dict):
    print("\n--- Run report ---")
    print(f"Frames kept: {report['frames_kept']} | used by steps: {report['frames_referenced']} "
          f"| not used: {len(report['frames_not_used'])}")
    print(f"Steps: {report['steps']} | screenshots inserted: {report['images_inserted']}")
    print(f"Requirements: {report['requirements']} | exceptions: {report['exceptions']}")
    if report["steps_not_refined"]:
        print(f"WARNING: steps kept as outlined (refinement didn't return them): {report['steps_not_refined']}")
    if report["steps_framed_by_narration"]:
        print(f"Steps whose frames were found from the narration time: {report['steps_framed_by_narration']}")
    if report["frames_dropped_out_of_order"]:
        print(f"Frames dropped for being out of time order, by step: {report['frames_dropped_out_of_order']}")
    if report["steps_without_image"]:
        print(f"WARNING: steps without a screenshot: {report['steps_without_image']}")
    if report["invalid_frame_refs"]:
        print(f"WARNING: the model cited unknown frame ids (ignored): {report['invalid_frame_refs']}")
    if not report["flowchart"]:
        print("WARNING: flowchart not generated (is Graphviz installed? sudo apt install graphviz)")
    print(f"Tokens: {report['tokens']} {report['tokens_by_model']} | Cost: ${report['cost_usd']:.4f}")
    if report["models_without_price"]:
        print(f"WARNING: cost excludes models with no known price: {report['models_without_price']}")
    print("------------------")
