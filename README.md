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

Each stage saves its result in the run folder and is skipped when that file exists; captions are saved after every frame (frames are captioned several at a time, `PDD_CAPTION_CONCURRENCY`, default 6; a 40-minute recording has over a thousand frames). Resuming a finished run only rebuilds the document. Delete `process_model.json` and `name_checks.json` from the folder to redo the structuring too.

Models are set with environment variables: `PDD_MODEL` for captioning frames (default `gpt-4.1-mini`, which read screen text best in tests and is billed far fewer tokens per image than `gpt-4o-mini`; every frame is an image, so this is where most of the cost is) and `PDD_STRUCTURE_MODEL` for structuring (default `gpt-4.1` at temperature 0; text only, so a strong model costs little here; `gpt-5` needs a verified OpenAI organization). The cost in the run report comes from the price table in `costs.py` plus Whisper's per-minute price; the report warns about models missing from that table, so add new models there.

## Company templates

To write the document into the PDD format a company already uses, pass its Word template:

```bash
.venv/bin/python main.py path/to/recording.mp4 --template path/to/PDD_Template.docx
```

The template is read once per run (and once per upload on the website), by `template.py`:

- **Analysis**: the model sees the template block by block (paragraphs with their styles, tables row by row, images, page headers) and decides for each one: keep (fixed text such as the introduction or a generic list of requirements), remove (instructions to the author like "<Lista de todos os sistemas>", and leftovers of the process the template was last used for: example steps, screenshots, systems, people, sample rows), write (a paragraph written for each process), fill a table's rows, answer a question table (e.g. metrics), or put the flowchart there. It also lists the short placeholders ("<Cliente>", "<Nome do Processo>"), finds how the example step is written ("P1 - ...", grouped under headings) and the template's language. `python template.py PDD_Template.docx` prints what it decided.
- **Fill**: after the steps are worked out (in the template's language and in the wording of its example step), one call writes every part marked to fill from the process model and the narration: tables (systems, inputs, exceptions, revision history...), metrics answers, scope, captions and placeholder values.
- **Render** (`render_template.py`): the template's own file is the starting point, so its cover, logo, styles, headers, numbering and fixed text stay exactly as they are. Example blocks are removed, tables keep their header and the formatting of their first row, steps take the format of the example step, and the table of contents is rebuilt (Word fills in the page numbers when the document is opened).

Whatever the recording doesn't say (contacts, versions, login modules, volumes, risk...) is never invented: it is written as the template's own "to fill" marker (e.g. "[A preencher]"), or the placeholder is left, highlighted in yellow so the author sees what to complete. The run report counts them (`missing_marks`).

The run folder keeps its own `template.docx`, `template_analysis.json` and `template_fill.json`, so `--resume` and `--from-run` work as usual. Deleting `template_fill.json` rewrites the template's sections; deleting `template_analysis.json` too analyzes the template again.

## How it works

The pipeline is a LangGraph graph (`pipeline.py`). Every stage reads and writes a shared state whose central piece is the **process model** (`ProcessModel` in `schemas.py`): steps with their screenshots, application, decision and recorded duration; the process inputs (structured, semi-structured or unstructured); key names; business rules and requirements; exceptions. The inputs are the recording and optionally a company template; the output is the .docx. The ROI analysis is planned as a further node that reads the same model.

```
START ─┬─ analyze_template ─┬─┬─ extract_frames ─ caption ─ transcribe ─┬─ structure ─ verify_names ─┬─ fill_template ─┬─ render ─ END
       └─ (no template) ────┘ └─ reuse_run (--from-run) ─────────────────┘                            └─ (no template) ─┘
```

1. **Frames** (`create_video.py`): samples the video and keeps a frame whenever enough pixels differ from the last kept one and the screen has settled, plus the final state of a screen right before it changes (e.g. a filled form before Save). Scrolling or animations get one frame every few seconds. Each frame gets an id (`F001`, `F002`, ...).
2. **Captions**: each frame is described by the vision model (screen, action, visible text).
3. **Transcription** (`transcribe.py`): the audio is cut into 10-minute chunks (Whisper accepts at most 25 MB per file) and the timestamps are shifted back to video time. Videos without audio skip this step.
4. **Structuring** (`structure.py`), in two passes:
   - *Outline*: one call sees the whole recording (a compact view of every frame plus the full narration) and decides the complete ordered list of steps (each with its application, any decision, and the first and last frame showing it), the process inputs, the business rules and requirements, the exceptions, and the correct spelling of key names (files, sites, views) with the misreadings it saw. The narration is the main source for what the steps are; explanations become requirements rather than steps. Deciding the steps once avoids duplicates and gaps between windows.
   - *Refine*: steps are grouped so each group's frames fit in one window, and one call per group gets the detailed captions to make each instruction specific and pick its screenshot. It can't add, drop or reorder steps.

   Every list the model returns has a maximum length that the API enforces while generating: on a 41-minute meeting, the outline otherwise listed misreadings of a window title until it ran out of output tokens and failed. Long recordings also keep all their frames (up to 2000).

   Code numbers the steps, takes each step's start and duration from its frames, maps ids to image files (so the model never writes file paths), and replaces misreadings of key names. Only variants a few characters away from the name are replaced, since the model sometimes lists different things as variants.
5. **Name check** (`verify_names.py`): captions see frames scaled down, where small text like a title bar is misread differently from frame to frame (e.g. "5.5.26" read as "5.3.26" in half the frames), and the text-only model can't tell which reading is right. For each pair of key names a character or two apart, a few frames whose captions mention either are cut into overlapping full-resolution tiles and the vision model is asked which name actually appears. If only one ever does, the other is replaced by it. If both do (e.g. two dated files listed side by side), they are different things and are kept.
6. **Document** (`render.py`, or `render_template.py` with a company template, see above): python-docx builds the PDD: introduction with a process overview (applications, inputs, decision points, recorded duration), flowchart (long processes are laid out in columns joined by connector circles; decisions are diamonds), steps with screenshots, exceptions, and business rules & requirements, with a clickable table of contents.

## Website

Pidi, the website: a FastAPI backend (`web/`) and a React front end (`web/frontend/`) let people upload a recording in the browser as a project, follow its progress and download the document. Each user has an account and only sees their own projects, templates and API keys. The pages follow the Pidi design (landing page, log in / create account, projects, new project, account); fonts are bundled, so the site loads nothing from other servers.

Build the front end once (Node 22), then start the server; it serves both the API and the pages:

```bash
cd web/frontend && npm ci && npm run build && cd ../..
.venv/bin/uvicorn web.app:create_app --factory --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 and create an account. For development with live reload, run the same uvicorn command with `--reload` and, in another terminal, `cd web/frontend && npm run dev` (open http://localhost:5173; Vite forwards `/api` to port 8000).

- **Processing**: uploads go into a queue kept in the database and are processed by background threads in the server (`PDD_WORKERS`, default 1). A run interrupted by a restart continues from its last finished stage, and a failed run can be retried from the page.
- **Storage**: everything is in `data/` (`PDD_DATA_DIR`): the SQLite database (`PDD_DATABASE_URL` to use another), and one folder per run with the uploaded recording and the same files as a command-line run.
- **Accounts**: passwords are hashed with Argon2. The session is an httpOnly, SameSite=Lax cookie signed with `PDD_SECRET_KEY` (generated into `data/secret_key` if unset), valid for `PDD_SESSION_DAYS` (default 7).
  - `PDD_SIGNUP_DOMAINS=company.com` limits sign-up to company addresses.
  - `PDD_ALLOW_SIGNUP=false` closes it; create accounts with `.venv/bin/python -m web.create_user someone@company.com`, which also resets passwords.
- **API keys**: people connect their own OpenAI key on the Account page and pick one per project, so usage is billed to them. Keys are checked with OpenAI before they are saved, stored encrypted with a key derived from `PDD_SECRET_KEY` (changing that secret means people reconnect their keys), and never sent back to the browser (only their last four characters are shown). People without a key of their own use the server's `OPENAI_API_KEY`; set `PDD_ALLOW_SERVER_KEY=false` to require their own. Only OpenAI keys can run the pipeline today.
- **Account**: name, email and password can be changed on the Account page; changing the password logs out the account's other sessions.
- **Uploads** are limited to `PDD_MAX_UPLOAD_MB` (default 2048) and must contain a video stream.
- **Templates**: on the Templates page people upload their company's PDD template (.docx), see what the analysis decided for every part of it, and pick it when uploading a recording. Each run copies the template and its analysis into its folder, so deleting a template doesn't change documents made with it.
- **Before putting it on the internet**:
  - Serve it behind HTTPS (e.g. a reverse proxy such as Caddy or nginx) and set `PDD_COOKIE_SECURE=true`.
  - Run a single server process, since the job queue lives in it.
  - Recordings and documents are confidential company material, so restrict sign-up and back up `data/`.

The API is described at http://127.0.0.1:8000/api/docs.

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

The tests use a synthetic screen recording and fake model/transcription, so they run offline. `tests/test_web.py` covers the website's API (accounts, uploads, background runs, access between users) with the same fakes. `python -m tests.measure_frames create_video` reports how many of the synthetic recording's known screen states the frame extractor captures.
