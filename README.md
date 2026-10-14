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
  frames.json             their ids and timestamps
  audio/chunk_000.mp3 ... audio split for transcription
  captions.json           what the model saw in each frame
  transcript.json         the narration, with timestamps
  process_model.json      the process model the document is rendered from
  name_checks.json        similar names re-read at full resolution (see below)
  report.json             counts, coverage checks and cost (see below)
  output/PDD_final.docx
```

Options: `--caption-width` (width frames are shrunk to before captioning, default 1366; OpenAI scales images to a 768 px short side, so larger gains nothing, and smaller misreads file names and column headers), `--window` (observations per refinement call, default 30), `--sample-every` (seconds between sampled frames, default 0.5), `--change-threshold` (share of changed pixels that counts as a new screen state, default 0.001).

To redo only the structuring and the document (e.g. after changing a prompt), reuse an earlier run's frames, captions and transcript, which are the expensive part, in a new run folder:

```bash
.venv/bin/python main.py path/to/recording.mp4 --from-run runs/recording-20261013-184500
```

To continue a run that stopped (network error, rate limit, Ctrl+C) in its own folder, without redoing what it finished:

```bash
.venv/bin/python main.py path/to/recording.mp4 --resume runs/recording-20261013-184500
```

Each stage saves its result in the run folder and is skipped when that file exists; captions are saved after every frame. Resuming a finished run only rebuilds the document. Delete `process_model.json` and `name_checks.json` from the folder to redo the structuring too.

Models are set with environment variables: `PDD_MODEL` for captioning frames (default `gpt-4.1-mini`, which read screen text best in tests and is billed far fewer tokens per image than `gpt-4o-mini`; every frame is an image, so this is where most of the cost is) and `PDD_STRUCTURE_MODEL` for structuring (default `gpt-4.1` at temperature 0; text only, so a strong model costs little here; `gpt-5` needs a verified OpenAI organization). The cost in the run report comes from the price table in `costs.py` plus Whisper's per-minute price; the report warns about models missing from that table, so add new models there.

## How it works

The pipeline is a LangGraph graph (`pipeline.py`). Every stage reads and writes a shared state whose central piece is the **process model** (`ProcessModel` in `schemas.py`): steps with their screenshots, application, decision and recorded duration; the process inputs (structured, semi-structured or unstructured); key names; business rules and requirements; exceptions. The recording is the only input today and the .docx the only output. Reading an existing PDD and the ROI analysis are planned as further nodes that produce or read the same model.

```
START ─┬─ extract_frames ─ caption ─ transcribe ─┬─ structure ─ verify_names ─ render ─ END
       └─ reuse_run (--from-run) ─────────────────┘
```

1. **Frames** (`create_video.py`): samples the video and keeps a frame whenever enough pixels differ from the last kept one and the screen has settled, plus the final state of a screen right before it changes (e.g. a filled form before Save). Scrolling or animations get one frame every few seconds. Each frame gets an id (`F001`, `F002`, ...).
2. **Captions**: each frame is described by the vision model (screen, action, visible text).
3. **Transcription** (`transcribe.py`): the audio is cut into 10-minute chunks (Whisper accepts at most 25 MB per file) and the timestamps are shifted back to video time. Videos without audio skip this step.
4. **Structuring** (`structure.py`), in two passes:
   - *Outline*: one call sees the whole recording (a compact view of every frame plus the full narration) and decides the complete ordered list of steps (each with its application and any decision), the process inputs, the business rules and requirements, the exceptions, and the correct spelling of key names (files, sites, views) with the misreadings it saw. The narration is the main source for what the steps are; explanations become requirements rather than steps. Deciding the steps once avoids duplicates and gaps between windows.
   - *Refine*: steps are grouped so each group's frames fit in one window, and one call per group gets the detailed captions to make each instruction specific and pick its screenshot. It can't add, drop or reorder steps.

   Code numbers the steps, takes each step's start and duration from its frames, maps ids to image files (so the model never writes file paths), and replaces misreadings of key names. Only variants a few characters away from the name are replaced, since the model sometimes lists different things as variants.
5. **Name check** (`verify_names.py`): captions see frames scaled down, where small text like a title bar is misread differently from frame to frame (e.g. "5.5.26" read as "5.3.26" in half the frames), and the text-only model can't tell which reading is right. For each pair of key names a character or two apart, a few frames whose captions mention either are cut into overlapping full-resolution tiles and the vision model is asked which name actually appears. If only one ever does, the other is replaced by it. If both do (e.g. two dated files listed side by side), they are different things and are kept.
6. **Document** (`render.py`): python-docx builds the PDD: introduction with a process overview (applications, inputs, decision points, recorded duration), flowchart (long processes are laid out in columns joined by connector circles; decisions are diamonds), steps with screenshots, exceptions, and business rules & requirements, with a clickable table of contents.

## Checking a run

The run report printed at the end (and saved in `report.json`) shows where frames could get lost:

- `frames_kept` → `frames_referenced` → `images_inserted`: how many screenshots survive each stage.
- `frames_not_used`: frames no step cites; open them in `frames/` to see whether the model skipped something relevant.
- `steps_framed_by_narration`: steps the outline attached no frames to, whose frames were then taken from the moment they are narrated (e.g. "delete the old data" over a table that just looks empty).
- `steps_without_image`: steps with no screenshot, typically actions that are neither shown nor narrated.
- `steps_not_refined`, `invalid_frame_refs`: steps the refinement skipped (their outline version is used) and frame ids the model made up.
- `names_fixed`, `names_verified`, `names_fixed_by_vision`: misread names replaced from the outline's list, and similar names checked against the full-resolution frames (with how many frames showed each).
- `applications`, `decision_points`, `recorded_seconds`: what the overview table shows. The recorded time includes the narrator's explanations, so it overstates the time the task takes.

If relevant screens are missing from `frames/` itself, lower `--change-threshold`; if there are too many near-duplicates, raise it.

## Tests

```bash
OPENAI_API_KEY=unused .venv/bin/python -m pytest tests
```

The tests use a synthetic screen recording and fake model/transcription, so they run offline. `python -m tests.measure_frames create_video` reports how many of the synthetic recording's known screen states the frame extractor captures.
