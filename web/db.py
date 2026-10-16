from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import event, inspect, text
from sqlmodel import Field, SQLModel, Session, create_engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    name: str | None = None
    # Part of every session token; changing the password increases it, which logs out other sessions.
    session_version: int | None = 0
    created_at: datetime = Field(default_factory=utcnow)


class Run(SQLModel, table=True):
    """One recording turned into a PDD. Its files live in data/runs/<id>/ (see pipeline.py for the layout)."""
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    video_name: str                       # the uploaded file's name, as the user knows it
    video_file: str                       # the saved file's name inside the run folder
    status: str = Field(default="queued", index=True)  # queued, running, done, failed
    stage: str | None = None              # pipeline stage (pipeline.STAGES) while running
    message: str | None = None            # latest progress message
    error: str | None = None
    process_name: str | None = None
    template_name: str | None = None      # the company template the document is written into, if any
    name: str | None = None               # the project's name, as the user typed it
    api_key_id: str | None = None         # the user's API key it runs on; None: the server's key
    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ApiKey(SQLModel, table=True):
    """A user's own API key (see web/keys.py); `secret` is encrypted, `prefix` and `last4` are for display."""
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    provider: str
    name: str
    prefix: str
    last4: str
    secret: str
    created_at: datetime = Field(default_factory=utcnow)


class Template(SQLModel, table=True):
    """A company PDD template and its analysis, in data/templates/<id>/ (template.docx, template_analysis.json)."""
    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    name: str                             # the uploaded file's name
    language: str
    created_at: datetime = Field(default_factory=utcnow)


def _add_new_columns(engine) -> None:
    """
    create_all makes missing tables but doesn't change existing ones, so columns added to a model later
    (all nullable) are added here, keeping databases made by earlier versions working.
    """
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing and column.nullable:
                    kind = column.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {kind}'))


def make_engine(url: str):
    # Runs are processed in worker threads, so SQLite connections must be usable across threads.
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(conn, _):
            conn.execute("PRAGMA journal_mode=WAL")   # readers don't wait for the worker's progress writes
            conn.execute("PRAGMA foreign_keys=ON")
    SQLModel.metadata.create_all(engine)
    _add_new_columns(engine)
    return engine


def session(engine) -> Session:
    return Session(engine, expire_on_commit=False)
