import glob
import os
import subprocess
from openai import OpenAI

# 10 minutes of 16 kHz mono MP3 at 48 kbps is ~3.6 MB, far below Whisper's 25 MB upload limit.
CHUNK_SECONDS = 600


def has_audio(video_path: str) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", video_path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {video_path}: {result.stderr.strip()}")
    return bool(result.stdout.strip())


def extract_audio_chunks(video_path: str, audio_dir: str, chunk_seconds: int = CHUNK_SECONDS) -> list[str]:
    """Extracts the audio as consecutive MP3 chunks of `chunk_seconds` each; returns their paths in order."""
    os.makedirs(audio_dir, exist_ok=True)
    result = subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1", "-b:a", "48k",
        "-f", "segment", "-segment_time", str(chunk_seconds), "-reset_timestamps", "1",
        os.path.join(audio_dir, "chunk_%03d.mp3"),
    ], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to extract audio: {result.stderr.strip()}")
    return sorted(glob.glob(os.path.join(audio_dir, "chunk_*.mp3")))


def transcribe_audio(video_path: str, audio_dir: str = "cache/audio", client: OpenAI | None = None,
                     chunk_seconds: int = CHUNK_SECONDS) -> list[dict]:
    """Returns narration segments [{text, start, end}] with times in seconds from the start of the video."""
    if not has_audio(video_path):
        print("No audio track found; continuing without narration.")
        return []

    client = client or OpenAI()
    segments = []
    for n, chunk in enumerate(extract_audio_chunks(video_path, audio_dir, chunk_seconds)):
        offset = n * chunk_seconds
        with open(chunk, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        segments += [
            {"text": seg.text.strip(), "start": seg.start + offset, "end": seg.end + offset}
            for seg in (response.segments or [])
            if seg.text.strip()
        ]
    return segments
