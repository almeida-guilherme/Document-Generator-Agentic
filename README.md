# Document Generator Agentic

Turns a screen recording of someone doing a task (optionally narrated) into a **Process Design Document (PDD)** in Word format, the document RPA teams write before automating a process: introduction, flowchart, numbered steps with screenshots, and business/system exceptions.

## Setup

System tools:

```bash
sudo apt install ffmpeg graphviz   # graphviz is only needed for the flowchart
```

Python (3.12):

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo "OPENAI_API_KEY=sk-..." > .env
```

## Usage

```bash
.venv/bin/python main.py path/to/recording.mp4
```

Each run creates its own folder under `runs/`:

```
runs/recording-20261013-184500/
  frames/F001.jpg ...     screenshots kept from the video
  audio/chunk_000.mp3 ... audio split for transcription
  captions.json           what the model saw in each frame
  pdd.json                the structured document
  report.json             counts and coverage checks (see below)
  output/PDD_final.docx
```

Options: `--window` (observations per structuring call, default 30), `--sample-every` (seconds between sampled frames, default 0.5), `--change-threshold` (share of changed pixels that counts as a new screen state, default 0.001). The model can be changed with the `PDD_MODEL` environment variable (default `gpt-4o-mini`).

## How it works

1. **Frames** (`create_video.py`): samples the video and keeps a frame whenever enough pixels differ from the last kept one and the screen has settled, plus the final state of a screen right before it changes (e.g. a filled form before Save). Scrolling or animations get one frame every few seconds. Each frame gets an id (`F001`, `F002`, ...).
2. **Captions**: each frame is described by the vision model (screen, action, visible text).
3. **Transcription** (`transcribe.py`): the audio is cut into 10-minute chunks (Whisper accepts at most 25 MB per file) and the timestamps are shifted back to video time. Videos without audio skip this step.
4. **Structuring** (`structure.py`): one call reads a compact view of the whole recording and decides the process name, proposal and goal; then the observations are processed in windows, each call writing that window's steps and citing frame ids. Code numbers the steps, takes each step's time from its first frame and maps ids to image files, so the model never writes file paths.
5. **Document** (`render.py`): python-docx builds the PDD with a clickable table of contents and a Graphviz flowchart.

## Checking a run

The run report printed at the end (and saved in `report.json`) shows where frames could get lost:

- `frames_kept` → `frames_referenced` → `images_inserted`: how many screenshots survive each stage.
- `frames_not_used`: frames no step cites; open them in `frames/` to see whether the model skipped something relevant.
- `steps_without_image`, `invalid_frame_refs`: steps whose frames could not be matched.

If relevant screens are missing from `frames/` itself, lower `--change-threshold`; if there are too many near-duplicates, raise it.

## Tests

```bash
OPENAI_API_KEY=unused .venv/bin/python -m pytest tests
```

The tests use a synthetic screen recording and fake model/transcription, so they run offline. `python -m tests.measure_frames create_video` reports how many of the synthetic recording's known screen states the frame extractor captures.
