"""
The website: a JSON API under /api and, when it has been built, the React front end at every other path.

    .venv/bin/uvicorn web.app:create_app --factory --port 8000
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from web import auth, runs, templates
from web.config import Settings
from web.db import make_engine
from web.jobs import JobRunner, RunFn, default_run_fn

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
                               "frame-ancestors 'none'",
}


def create_app(settings: Settings | None = None, run_fn: RunFn = default_run_fn, start_jobs: bool = True,
               analyze_template=templates.default_analyze) -> FastAPI:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or Settings()
    engine = make_engine(settings.database_url)
    jobs = JobRunner(engine, settings.runs_dir, run_fn, settings.workers)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_jobs:
            jobs.start()
        yield
        jobs.stop()

    app = FastAPI(title="Document Generator", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.settings, app.state.engine, app.state.jobs = settings, engine, jobs
    # analyze_template(path) -> TemplateAnalysis; swapped for a fake in tests.
    app.state.analyze_template = analyze_template

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    app.include_router(auth.router)
    app.include_router(runs.router)
    app.include_router(templates.router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    _serve_frontend(app, settings.frontend_dir)
    return app


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serves the built React app (npm run build). In development Vite serves it instead (npm run dev)."""
    if not (dist / "index.html").exists():
        return
    dist = dist.resolve()
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        file = (dist / path).resolve()
        if path and file.is_file() and file.is_relative_to(dist):
            return FileResponse(file)
        # Any other path is a page of the app (e.g. /runs/abc); React Router shows it.
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
