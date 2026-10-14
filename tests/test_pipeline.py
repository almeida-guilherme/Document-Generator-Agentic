"""Offline tests: the LLM and Whisper are replaced by fakes, so no API key is needed."""
import os
import re
import subprocess
from types import SimpleNamespace
import pytest
from docx import Document

from pipeline import run_pdd_pipeline
from schemas import (FrameCaption, ProcessOutline, OutlineStep, WindowRefinement, RefinedStep,
                     RequirementItem, ExceptionItem)
from transcribe import transcribe_audio, has_audio
from tests.synthetic_video import build


class FakeLLM:
    """Mimics `llm.with_structured_output(schema).invoke(messages)` with deterministic answers."""

    model_name = "fake"

    def __init__(self):
        self.refine_calls = 0

    def with_structured_output(self, schema):
        return SimpleNamespace(invoke=lambda messages: self._answer(schema, messages))

    def _answer(self, schema, messages):
        text = messages[-1].content
        if schema is FrameCaption:
            return FrameCaption(screen_or_system="Intranet", observed_action="something", visible_text=[])
        if schema is ProcessOutline:
            ids = re.findall(r'"id": "(F\d+)"', text)
            times = dict(re.findall(r'"id": "(F\d+)", "t": ([\d.]+)', text))
            # One step per pair of frames, plus one bad id the code must ignore and two steps with no frames:
            # one never narrated (stays without image) and one narrated just before the next step's frames.
            steps = [OutlineStep(instruction=f"You need to do {a}+{b}", short_label="Do it", frame_ids=[a, b])
                     for a, b in zip(ids[::2], ids[1::2])]
            steps[0].frame_ids.append("F999")
            steps.insert(1, OutlineStep(instruction="You need to wait for approval", short_label="Wait", frame_ids=[]))
            steps.insert(2, OutlineStep(instruction="You need to clear the form", short_label="Clear", frame_ids=[],
                                        narrated_at=float(times[ids[2]])))
            return ProcessOutline(
                process_name="Create invoice", project_proposal="Proposal.", steps=steps,
                requirements=[RequirementItem(category="frequency", description="Runs daily.")],
                business_exceptions=[ExceptionItem(name="No client", action="Client missing", action_to_be_taken="Skip"),
                                     ExceptionItem(name="no client ", action="dup", action_to_be_taken="dup")],
            )
        if schema is WindowRefinement:
            self.refine_calls += 1
            numbered = [int(n) for n in re.findall(r"^(\d+)\. ", text, re.M)]
            guesses = re.findall(r"first guess of frames: \[(.*?)\]", text)
            refined = []
            for n, guess in zip(numbered, guesses):
                ids = re.findall(r"F\d+", guess)
                if n == 4:
                    continue  # forgotten by the model: code must keep the outline version
                main = "F998" if n == numbered[-1] else (ids[-1] if ids else "")  # last one invalid
                refined.append(RefinedStep(number=n, instruction=f"Refined {n}", frame_ids=ids, main_frame_id=main))
            return WindowRefinement(steps=refined)
        raise AssertionError(f"unexpected schema {schema}")


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("video") / "synthetic.mp4")
    build(path)
    return path


def test_pipeline_end_to_end(video, tmp_path):
    llm = FakeLLM()
    output, report = run_pdd_pipeline(video, str(tmp_path), llm=llm, structure_llm=llm,
                                      transcribe=lambda v, audio_dir: [], max_frames_per_window=5)

    assert report["frames_kept"] >= 10
    assert report["steps"] == report["frames_kept"] // 2 + 2  # one per pair of frames + the two frameless steps
    assert llm.refine_calls == report["windows"] > 1
    assert report["steps_not_refined"] == [4]
    assert report["steps_framed_by_narration"] == [3]
    assert report["steps_without_image"] == [2]  # the step that was never narrated
    assert {"F999", "F998"} <= set(report["invalid_frame_refs"])
    assert report["images_inserted"] == report["steps"] - 1
    assert report["requirements"] == 1 and report["exceptions"] == 1  # duplicate exception removed

    doc = Document(output)
    assert len(doc.inline_shapes) == report["images_inserted"] + int(report["flowchart"])
    # Word refuses files where a paragraph's properties (w:pPr) aren't its first child.
    for p in doc.element.body.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        if p.pPr is not None:
            assert p[0] is p.pPr
    for name in ("captions.json", "transcript.json", "pdd.json", "report.json"):
        assert os.path.exists(tmp_path / name)


def test_steps_are_numbered_and_timed_by_code(video, tmp_path):
    import json
    llm = FakeLLM()
    run_pdd_pipeline(video, str(tmp_path), llm=llm, structure_llm=llm, transcribe=lambda v, audio_dir: [],
                     max_frames_per_window=5)
    steps = json.loads((tmp_path / "pdd.json").read_text())["as_is"]
    assert [s["number"] for s in steps] == list(range(1, len(steps) + 1))
    timed = [s["time"] for s in steps if s["frame_ids"]]
    assert timed == sorted(timed)
    assert steps[1]["time"] == "" and steps[1]["main_frame_path"] is None
    assert steps[2]["frame_ids"]  # found from its narration time
    assert steps[3]["instruction"].startswith("You need to do")  # not refined: outline text kept
    assert steps[4]["instruction"] == "Refined 5"
    # The screenshot is the frame the model chose, or the step's last frame when its choice is invalid.
    for s in steps:
        if s["main_frame_path"]:
            assert os.path.basename(s["main_frame_path"]) == f'{s["frame_ids"][-1]}.jpg'


def test_rerun_from_previous_run_reuses_captions(video, tmp_path):
    llm = FakeLLM()
    first = tmp_path / "first"; first.mkdir()
    run_pdd_pipeline(video, str(first), llm=llm, structure_llm=llm, transcribe=lambda v, audio_dir: [])
    second = tmp_path / "second"; second.mkdir()
    no_captions = SimpleNamespace(model_name="unused", with_structured_output=lambda schema: pytest.fail("captioned again"))
    _, report = run_pdd_pipeline(video, str(second), llm=no_captions, structure_llm=llm,
                                 transcribe=lambda v, audio_dir: pytest.fail("transcribed again"), from_run=str(first))
    assert report["images_inserted"] == report["steps"] - 1
    assert not (second / "frames").exists()


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


def test_out_of_order_frames_are_dropped():
    from schemas import Step
    from structure import enforce_chronology
    frames = {f"F{i:03d}": {"id": f"F{i:03d}", "timestamp": float(i * 10), "path": f"F{i:03d}.jpg"} for i in range(1, 31)}
    step = lambda n, ids, main: Step(number=n, time="", instruction="x", short_label="x", frame_ids=ids,
                                     main_frame_path=f"{main}.jpg")
    steps = [step(1, ["F001", "F002"], "F002"),
             step(2, ["F004", "F029"], "F029"),   # one frame from far later: dropped, screenshot falls back to F004
             step(3, ["F028"], "F028"),           # only a far-later frame: left without screenshot
             step(4, ["F006", "F007"], "F007")]
    dropped = enforce_chronology(steps, frames)
    assert dropped == {2: ["F029"], 3: ["F028"]}
    assert steps[1].frame_ids == ["F004"] and steps[1].main_frame_path == "F004.jpg" and steps[1].time == "00:40"
    assert steps[2].frame_ids == [] and steps[2].main_frame_path is None and steps[2].time == ""
    assert steps[3].main_frame_path == "F007.jpg"
