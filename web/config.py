import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    """Read from environment variables (or .env); see the README's "Website" section."""
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("PDD_DATA_DIR", "data")))
    database_url: str = field(default_factory=lambda: os.getenv("PDD_DATABASE_URL", ""))
    secret_key: str = field(default_factory=lambda: os.getenv("PDD_SECRET_KEY", ""))
    allow_signup: bool = field(default_factory=lambda: _bool("PDD_ALLOW_SIGNUP", True))
    # Comma-separated email domains allowed to sign up (e.g. "company.com"); empty allows any.
    signup_domains: list[str] = field(default_factory=lambda: [
        d.strip().lower().lstrip("@") for d in os.getenv("PDD_SIGNUP_DOMAINS", "").split(",") if d.strip()])
    max_upload_mb: int = field(default_factory=lambda: int(os.getenv("PDD_MAX_UPLOAD_MB", "2048")))
    # Runs processed at the same time. Each run calls the OpenAI API for minutes, so more workers mostly
    # means hitting rate limits sooner.
    workers: int = field(default_factory=lambda: int(os.getenv("PDD_WORKERS", "1")))
    # Set to true when the site is served over HTTPS, so the login cookie is never sent over plain HTTP.
    cookie_secure: bool = field(default_factory=lambda: _bool("PDD_COOKIE_SECURE", False))
    session_days: int = field(default_factory=lambda: int(os.getenv("PDD_SESSION_DAYS", "7")))
    frontend_dir: Path = field(default_factory=lambda: Path(os.getenv(
        "PDD_FRONTEND_DIR", Path(__file__).parent / "frontend" / "dist")))

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "runs").mkdir(exist_ok=True)
        (self.data_dir / "templates").mkdir(exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'app.db'}"
        if not self.secret_key:
            # Kept in the data folder so logins survive restarts; set PDD_SECRET_KEY to manage it yourself.
            key_file = self.data_dir / "secret_key"
            if not key_file.exists():
                key_file.write_text(secrets.token_urlsafe(48))
                key_file.chmod(0o600)
            self.secret_key = key_file.read_text().strip()

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def templates_dir(self) -> Path:
        return self.data_dir / "templates"
