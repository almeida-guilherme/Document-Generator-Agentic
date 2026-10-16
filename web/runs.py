import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import select

from web.auth import current_user
from web.db import Run, User, session
from web.templates import copy_into_run, own_template

router = APIRouter(prefix="/api/runs", tags=["runs"])

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv"}
FRAME_ID = re.compile(r"^F\d{3,4}$")
CHUNK = 1024 * 1024


class RunSummary(BaseModel):
    steps: int | None = None
    screenshots: int | None = None
    cost_usd: float | None = None
    applications: list[str] = []
    recorded_seconds: float | None = None
    warnings: list[str] = []
    to_complete: int = 0  # parts of a template document highlighted for the author to fill in


class RunOut(BaseModel):
    id: str
    video_name: str
    status: str
    stage: str | None
    message: str | None
    error: str | None
    process_name: str | None
    template_name: str | None = None
    # The stages this run goes through (pipeline.STAGES or TEMPLATE_STAGES), for the progress display.
    stages: list[str] = []
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    summary: RunSummary | None = None


def _run_dir(request: Request, run: Run) -> Path:
    return request.app.state.settings.runs_dir / run.id


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _steps(numbers: list[int]) -> str:
    """[2] -> "Step 2 has", [2, 5] -> "Steps 2 and 5 have"."""
    if len(numbers) == 1:
        return f"Step {numbers[0]} has"
    return f"Steps {', '.join(map(str, numbers[:-1]))} and {numbers[-1]} have"


def _summary(report: dict) -> RunSummary:
    warnings = []
    if report.get("steps_without_image"):
        warnings.append(f"{_steps(report['steps_without_image'])} no screenshot: nothing on screen clearly showed "
                        "the action. Add one by hand if it matters.")
    if report.get("steps_not_refined"):
        warnings.append(f"{_steps(report['steps_not_refined'])} a less specific description (the detailed pass "
                        "skipped them). Check their wording.")
    if not report.get("flowchart", True):
        warnings.append("The flowchart could not be drawn (Graphviz missing on the server).")
    if report.get("missing_marks"):
        warnings.append(f"{report['missing_marks']} part(s) of the document are highlighted in yellow: the recording "
                        "didn't say what goes there (e.g. contacts, versions, volumes). Fill them in before sharing it.")
    if report.get("models_without_price"):
        warnings.append(f"Cost excludes models with no known price: {', '.join(report['models_without_price'])}")
    return RunSummary(steps=report.get("steps"), screenshots=report.get("images_inserted"),
                      cost_usd=report.get("cost_usd"), applications=report.get("applications") or [],
                      recorded_seconds=report.get("recorded_seconds"), warnings=warnings,
                      to_complete=report.get("missing_marks") or 0)


def _out(request: Request, run: Run, with_summary: bool = False) -> RunOut:
    from pipeline import stages_for
    out = RunOut(**run.model_dump(include=set(RunOut.model_fields) - {"summary", "stages"}),
                 stages=stages_for(run.template_name is not None))
    if with_summary and run.status == "done":
        report = _read_json(_run_dir(request, run) / "report.json")
        out.summary = _summary(report) if report else None
    return out


def _own_run(request: Request, run_id: str, user: User) -> Run:
    """The run, if it exists and belongs to `user`; otherwise 404 (not 403, so ids of others don't leak)."""
    with session(request.app.state.engine) as db:
        run = db.get(Run, run_id)
    if run is None or run.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found.")
    return run


def _has_video_stream(path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return result.returncode == 0 and bool(result.stdout.strip())


@router.get("", response_model=list[RunOut])
def list_runs(request: Request, user: User = Depends(current_user)):
    with session(request.app.state.engine) as db:
        runs = db.exec(select(Run).where(Run.user_id == user.id).order_by(Run.created_at.desc())).all()
    return [_out(request, run) for run in runs]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=RunOut)
def create_run(request: Request, file: UploadFile = File(...), template_id: str | None = Form(None),
               user: User = Depends(current_user)):
    settings = request.app.state.settings
    template = own_template(request, template_id, user) if template_id else None
    name = os.path.basename(file.filename or "recording")
    ext = os.path.splitext(name)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                            f"Upload a screen recording ({', '.join(sorted(VIDEO_EXTENSIONS))}).")

    run = Run(user_id=user.id, video_name=name, video_file=f"video{ext}",
              template_name=template.name if template else None)
    run_dir = settings.runs_dir / run.id
    run_dir.mkdir(parents=True)
    limit, size = settings.max_upload_mb * CHUNK, 0
    try:
        with open(run_dir / run.video_file, "wb") as out:
            while chunk := file.file.read(CHUNK):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE,
                                        f"The file is larger than {settings.max_upload_mb} MB.")
                out.write(chunk)
        if not _has_video_stream(run_dir / run.video_file):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "The file could not be read as a video.")
        if template:
            copy_into_run(request, template, run_dir)
    except BaseException:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise

    with session(request.app.state.engine) as db:
        db.add(run)
        db.commit()
    request.app.state.jobs.notify()
    return _out(request, run)


@router.get("/{run_id}", response_model=RunOut)
def get_run(run_id: str, request: Request, user: User = Depends(current_user)):
    return _out(request, _own_run(request, run_id, user), with_summary=True)


@router.get("/{run_id}/model")
def get_model(run_id: str, request: Request, user: User = Depends(current_user)):
    """The process model for display: like process_model.json, with image URLs instead of server paths."""
    run = _own_run(request, run_id, user)
    model = _read_json(_run_dir(request, run) / "process_model.json")
    if model is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The process model isn't ready yet.")
    for step in model["as_is"]:
        path = step.pop("main_frame_path", None)
        step["image_url"] = f"/api/runs/{run.id}/frames/{Path(path).stem}" if path else None
    return model


@router.get("/{run_id}/frames/{frame_id}")
def get_frame(run_id: str, frame_id: str, request: Request, user: User = Depends(current_user)):
    run = _own_run(request, run_id, user)
    if not FRAME_ID.match(frame_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame not found.")
    path = _run_dir(request, run) / "frames" / f"{frame_id}.jpg"
    if not path.exists():
        # Runs made with --from-run point at the earlier run's frames; follow frames.json.
        frames = _read_json(_run_dir(request, run) / "frames.json") or []
        path = Path(next((f["path"] for f in frames if f["id"] == frame_id), ""))
        if not path.is_file():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Frame not found.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


def _document_name(run: Run) -> str:
    base = run.process_name or os.path.splitext(run.video_name)[0]
    base = re.sub(r"[^\w\s.-]", "", base).strip()[:80] or "Process"
    return f"{base} - PDD.docx"


@router.get("/{run_id}/document")
def get_document(run_id: str, request: Request, user: User = Depends(current_user)):
    run = _own_run(request, run_id, user)
    path = _run_dir(request, run) / "output" / "PDD_final.docx"
    if run.status != "done" or not path.exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "The document isn't ready yet.")
    return FileResponse(path, filename=_document_name(run),
                        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.post("/{run_id}/retry", response_model=RunOut)
def retry_run(run_id: str, request: Request, user: User = Depends(current_user)):
    """Queues a failed run again; it continues from its last finished stage."""
    run = _own_run(request, run_id, user)
    if run.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed runs can be retried.")
    with session(request.app.state.engine) as db:
        run = db.get(Run, run_id)
        run.status, run.error, run.message, run.finished_at = "queued", None, "Waiting to retry", None
        db.add(run)
        db.commit()
    request.app.state.jobs.notify()
    return _out(request, run)


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run(run_id: str, request: Request, user: User = Depends(current_user)):
    run = _own_run(request, run_id, user)
    if run.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "The run is in progress; delete it when it has finished.")
    with session(request.app.state.engine) as db:
        db.delete(db.get(Run, run_id))
        db.commit()
    shutil.rmtree(_run_dir(request, run), ignore_errors=True)
