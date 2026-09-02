import subprocess
from openai import OpenAI

def extract_audio(video_path: str, audio_path: str = "cache/audio.wav") -> str:
    subprocess.run([
        "ffmpeg", "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1",
        audio_path, "-y"
    ], capture_output=True)
    return audio_path


def transcribe_audio(video_path: str, audio_path: str = "cache/audio.wav") -> list[dict]:
    audio_path = extract_audio(video_path, audio_path)

    client = OpenAI()
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            response_format="verbose_json",
            timestamp_granularities=["segment"],
        )
    return [
        {"text": seg.text.strip(), "start": seg.start, "end": seg.end}
        for seg in response.segments
        if seg.text.strip()
    ]