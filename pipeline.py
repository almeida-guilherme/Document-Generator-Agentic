import json
import os
import time
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_community.callbacks import get_openai_callback

from create_video import create_frames, caption_frame
from transcribe import transcribe_audio
from structure import structure_pdd
from render import render_docx
from schemas import FrameCaption

DEFAULT_MODEL = os.getenv("PDD_MODEL", "gpt-4o-mini")


def new_run_dir(video_path: str, base_dir: str = "runs") -> str:
    """Each run gets its own folder, so frames from a previous video can never leak into this one."""
    stem = os.path.splitext(os.path.basename(video_path))[0]
    run_dir = os.path.join(base_dir, f"{stem}-{datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(run_dir)
    return run_dir


def run_pdd_pipeline(
    video_path: str,
    run_dir: str,
    llm=None,
    transcribe=transcribe_audio,
    max_frames_per_window: int = 30,
    frame_options: dict | None = None,
) -> tuple[str, dict]:
    """
    Runs the full PDD generation pipeline for a single video.

    Args:
        video_path: path to the input video file.
        run_dir: empty directory for this run's artifacts (frames, audio, output, report).
        llm: LangChain chat model; defaults to ChatOpenAI with PDD_MODEL.
        transcribe: function(video_path, audio_dir) -> transcript segments.

    Returns:
        path to the generated .docx file, and the run report (also saved as report.json).
    """
    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    llm = llm or ChatOpenAI(model=DEFAULT_MODEL, max_retries=5)
    report: dict = {"video": video_path, "model": getattr(llm, "model_name", None)}

    with get_openai_callback() as cb:
        # 1. Frames + captioning
        frames = create_frames(video_path, output_dir=os.path.join(run_dir, "frames"), **(frame_options or {}))
        report["frames_kept"] = len(frames)
        print(f"[1/4] {len(frames)} frames kept")

        caption_llm = llm.with_structured_output(FrameCaption)
        captions = []
        for n, frame in enumerate(frames, 1):
            captions.append(caption_frame(frame, caption_llm))
            print(f"      captioned {n}/{len(frames)}", end="\r")
            time.sleep(1)
        print()

        # 2. Audio + transcription
        transcript = transcribe(video_path, audio_dir=os.path.join(run_dir, "audio"))
        report["narration_segments"] = len(transcript)
        print(f"[2/4] {len(transcript)} narration segments")

        # 3. Structuring
        pdd, structure_report = structure_pdd(captions, transcript, frames, llm, max_frames_per_window)
        report.update(structure_report)
        print(f"[3/4] {len(pdd.as_is)} steps from {structure_report['windows']} part(s)")

        # 4. Document generation
        output_path, render_stats = render_docx(pdd, output_path=os.path.join(run_dir, "output", "PDD_final.docx"))
        report.update(render_stats)
        print(f"[4/4] document written with {render_stats['images_inserted']} screenshots")

        report["tokens"] = cb.total_tokens
        report["cost_usd"] = round(cb.total_cost, 4)

    with open(os.path.join(run_dir, "captions.json"), "w", encoding="utf-8") as f:
        json.dump(captions, f, ensure_ascii=False, indent=2)
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
    if report["steps_without_image"]:
        print(f"WARNING: steps without a screenshot: {report['steps_without_image']}")
    if report["invalid_frame_refs"]:
        print(f"WARNING: the model cited unknown frame ids (ignored): {report['invalid_frame_refs']}")
    if not report["flowchart"]:
        print("WARNING: flowchart not generated (is Graphviz installed? sudo apt install graphviz)")
    print(f"Tokens: {report['tokens']} | Cost: ${report['cost_usd']:.4f}")
    print("------------------")
