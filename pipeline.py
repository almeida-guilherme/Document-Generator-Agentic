import os
import time
from langchain_openai import ChatOpenAI

from create_video import create_frames, caption_frame
from transcribe import transcribe_audio
from structure import structure_pdd
from render import render_docx
from schemas import FrameCaption, format_timestamp



def run_pdd_pipeline(video_path: str, job_dir: str) -> str:
    """
    Runs the full PDD generation pipeline for a single video.

    Args:
        video_path: path to the input video file.
        job_dir: base directory for this job's artifacts (frames, audio, output).

    Returns:
        path to the generated .docx file.
    """
    frames_dir = os.path.join(job_dir, "frames")
    audio_path = os.path.join(job_dir, "audio.wav")
    output_path = os.path.join(job_dir, "output", "PDD_final.docx")

    # 1. Frames + captioning
    frames = create_frames(video_path, output_dir=frames_dir)

    llm = ChatOpenAI(model="gpt-4o-mini", max_retries=5).with_structured_output(FrameCaption)
    captions = []
    for frame in frames:
        captions.append(caption_frame(frame, llm))
        time.sleep(1)

    for c in captions:
        c["time"] = format_timestamp(c["timestamp"])

    # 2. Audio + transcription
    transcript = transcribe_audio(video_path, audio_path=audio_path)

    # 3. Structuring
    pdd = structure_pdd(captions, transcript)

    # 4. Document generation
    final_path = render_docx(pdd, output_path=output_path)

    return final_path