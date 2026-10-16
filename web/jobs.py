"""
Runs the pipeline in background threads, one run at a time per worker.

The queue is the database itself (runs with status "queued"), so nothing else needs to be installed.
Each run's stages save their results in its folder (see pipeline.py), so a run that was interrupted by a
restart is simply queued again and continues where it stopped.
"""
import json
import logging
import threading
import traceback
from pathlib import Path
from typing import Callable
from sqlalchemy import update
from sqlmodel import select

from web.db import ApiKey, Run, session, utcnow
from web.keys import decrypt

log = logging.getLogger("pdd.jobs")

# run_fn(video_path, run_dir, progress, api_key, recording_name=...) -> (document path, report);
# progress(stage, message, done); api_key is the user's key for this run, or None for the server's;
# recording_name is the uploaded file's name (the video is stored as video.<ext>).
RunFn = Callable[..., tuple[str, dict]]


def default_run_fn(video_path: str, run_dir: str, progress, api_key: str | None = None,
                   recording_name: str | None = None) -> tuple[str, dict]:
    from pipeline import run_pdd_pipeline  # imported here so the API starts fast and tests can swap it
    return run_pdd_pipeline(video_path, run_dir, progress=progress, api_key=api_key, recording_name=recording_name)


class JobRunner:
    def __init__(self, engine, runs_dir: Path, run_fn: RunFn = default_run_fn, workers: int = 1, secret_key: str = ""):
        self.engine, self.runs_dir, self.run_fn, self.workers = engine, runs_dir, run_fn, workers
        self.secret_key = secret_key
        self._wake = threading.Condition()
        self._claim = threading.Lock()
        self._stop = False
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        with session(self.engine) as db:
            # Runs that were in progress when the server stopped continue from their saved stages.
            for run in db.exec(select(Run).where(Run.status == "running")).all():
                run.status, run.message = "queued", "Resuming after a server restart"
                db.add(run)
            db.commit()
        for n in range(self.workers):
            thread = threading.Thread(target=self._loop, name=f"pdd-worker-{n}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        with self._wake:
            self._stop = True
            self._wake.notify_all()

    def notify(self) -> None:
        """Called after a run is queued, so an idle worker picks it up at once."""
        with self._wake:
            self._wake.notify()

    def _next_run(self) -> Run | None:
        """Claims the oldest queued run. The conditional update makes the claim safe even if several server
        processes share the database: only one of them changes the status from "queued"."""
        with self._claim, session(self.engine) as db:
            for run in db.exec(select(Run).where(Run.status == "queued").order_by(Run.created_at).limit(5)).all():
                claimed = db.exec(update(Run).where(Run.id == run.id, Run.status == "queued")
                                  .values(status="running", started_at=utcnow(), error=None))
                db.commit()
                if claimed.rowcount == 1:
                    return db.get(Run, run.id, populate_existing=True)
            return None

    def _loop(self) -> None:
        while True:
            with self._wake:
                if self._stop:
                    return
            run = self._next_run()
            if run is None:
                with self._wake:
                    if not self._stop:
                        self._wake.wait(timeout=5)
                continue
            self.process(run)

    def _api_key(self, run: Run) -> str | None:
        return _key_for(self.engine, self.secret_key, run)

    def _update(self, run_id: str, **fields) -> None:
        with session(self.engine) as db:
            run = db.get(Run, run_id)
            if run is None:  # deleted meanwhile
                return
            for key, value in fields.items():
                setattr(run, key, value)
            db.add(run)
            db.commit()

    def process(self, run: Run) -> None:
        run_dir = self.runs_dir / run.id

        def progress(stage: str, message: str, done: bool) -> None:
            self._update(run.id, stage=stage, message=message)

        log.info("run %s started", run.id)
        try:
            _, report = self.run_fn(str(run_dir / run.video_file), str(run_dir), progress, self._api_key(run),
                                    recording_name=run.video_name)
            model = json.loads((run_dir / "process_model.json").read_text(encoding="utf-8"))
            self._update(run.id, status="done", finished_at=utcnow(), message="Document ready",
                         process_name=model.get("process_name"))
            log.info("run %s done (%s steps, $%s)", run.id, report.get("steps"), report.get("cost_usd"))
        except Exception as exc:  # any failure is shown to the user; details go to the server log
            log.error("run %s failed:\n%s", run.id, traceback.format_exc())
            self._update(run.id, status="failed", finished_at=utcnow(), error=_user_message(exc))


class MissingKey(Exception):
    pass


def _key_for(engine, secret_key: str, run: Run) -> str | None:
    if run.api_key_id is None:
        return None
    with session(engine) as db:
        key = db.get(ApiKey, run.api_key_id)
    if key is None:
        raise MissingKey("The API key chosen for this project was removed. Create the project again with another key.")
    try:
        return decrypt(secret_key, key.secret)
    except ValueError as exc:
        raise MissingKey(str(exc))


def _user_message(exc: Exception) -> str:
    """A message the person who uploaded the video can act on, without internal details."""
    name = type(exc).__name__
    text = str(exc)
    if isinstance(exc, MissingKey):
        return text
    if "AuthenticationError" in name or "api_key" in text.lower():
        return "OpenAI refused the API key. Check the key in your account (or, for the server key, the server's .env)."
    if "RateLimit" in name or "insufficient_quota" in text:
        return "The OpenAI account hit its rate limit or ran out of credit. Try again later (the run continues from where it stopped)."
    if "Could not open video" in text or "ffprobe failed" in text:
        return "The file could not be read as a video."
    return f"The run failed ({name}). Retry it; it continues from the last finished stage."
