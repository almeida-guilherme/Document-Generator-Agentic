"""Offline tests: the LLM and Whisper are replaced by fakes, so no API key is needed."""
import os
import re
import subprocess
from types import SimpleNamespace
import pytest
from docx import Document

from pipeline import run_pdd_pipeline
from schemas import FrameCaption, ProcessOverview, WindowResult, DraftStep
from transcribe import transcribe_audio, has_audio
from tests.synthetic_video import build


class FakeLLM:
    """Mimics `llm.with_structured_output(schema).invoke(messages)` with deterministic answers."""

    model_name = "fake"

    def __init__(self):
        self.window_calls = 0

    def with_structured_output(self, schema):
        return SimpleNamespace(invoke=lambda messages: self._answer(schema, messages))

    def _answer(self, schema, messages):
        if schema is FrameCaption:
            return FrameCaption(screen_or_system="Intranet", observed_action="something", visible_text=[])
        if schema is ProcessOverview:
            return ProcessOverview(process_name="Create invoice", project_proposal="Proposal.", goal="Invoice created.")
        if schema is WindowResult:
            self.window_calls += 1
            text = messages[-1].content
            ids = re.findall(r'"id": "(F\d+)"', text)
            # One step per pair of frames, plus one bad id the code must ignore.
            steps = [DraftStep(instruction=f"You need to do {pair}", short_label="Do it", frame_ids=list(pair))
                     for pair in zip(ids[::2], ids[1::2])]
            if steps:
                steps[0].frame_ids.append("F999")
            return WindowResult(steps=steps)
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("video") / "synthetic.mp4")
    build(path)
    return path


def test_pipeline_end_to_end(video, tmp_path):
    llm = FakeLLM()
    output, report = run_pdd_pipeline(video, str(tmp_path), llm=llm, transcribe=lambda v, audio_dir: [],
                                      max_frames_per_window=5)

    assert report["frames_kept"] >= 10
    assert llm.window_calls == report["windows"] > 1
    window_sizes = [min(5, report["frames_kept"] - i) for i in range(0, report["frames_kept"], 5)]
    assert report["steps"] == sum(n // 2 for n in window_sizes)  # FakeLLM makes one step per pair of frames
    assert report["steps_without_image"] == []
    assert "F999" in report["invalid_frame_refs"]
    assert report["images_inserted"] == report["steps"]

    doc = Document(output)
    assert len(doc.inline_shapes) == report["images_inserted"] + int(report["flowchart"])
    for name in ("captions.json", "pdd.json", "report.json"):
        assert os.path.exists(tmp_path / name)


def test_steps_are_numbered_and_timed_by_code(video, tmp_path):
    import json
    run_pdd_pipeline(video, str(tmp_path), llm=FakeLLM(), transcribe=lambda v, audio_dir: [], max_frames_per_window=5)
    pdd = json.loads((tmp_path / "pdd.json").read_text())
    assert [s["number"] for s in pdd["as_is"]] == list(range(1, len(pdd["as_is"]) + 1))
    times = [s["time"] for s in pdd["as_is"]]
    assert times == sorted(times)
    assert all(os.path.basename(p).startswith(s["frame_ids"][0]) for s in pdd["as_is"] for p in s["frame_paths"][:1])


def test_transcription_offsets_chunks(tmp_path):
    media = str(tmp_path / "with_audio.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=white:s=320x240:d=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=25", "-shortest", media], check=True)
    assert has_audio(media)

    calls = []
    def create(**kwargs):
        calls.append(kwargs["file"].name)
        return SimpleNamespace(segments=[SimpleNamespace(text=f" chunk {len(calls)} ", start=1.0, end=2.0)])
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))

    segments = transcribe_audio(media, audio_dir=str(tmp_path / "audio"), client=client, chunk_seconds=10)
    assert len(calls) == 3
    assert [s["start"] for s in segments] == [1.0, 11.0, 21.0]
    assert segments[0]["text"] == "chunk 1"


def test_video_without_audio_skips_transcription(video, tmp_path):
    assert not has_audio(video)
    assert transcribe_audio(video, audio_dir=str(tmp_path), client=object()) == []
