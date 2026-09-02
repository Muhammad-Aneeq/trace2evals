"""Settings. Every value has a local-first default; nothing here reaches the network.

Override any field with a `T2E_`-prefixed environment variable, e.g. `T2E_PORT=9000`.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="T2E_", env_file=".env", extra="ignore")

    #: SQLite lives under the working directory: per-project, no global state, trivially deletable.
    db_path: Path = Path(".t2e/t2e.db")

    host: str = "127.0.0.1"
    port: int = 8765

    #: Redact PII-lookalike payloads on import (spec 03 sec 11).
    #: Opt out per-import with --no-redact.
    redact: bool = True
    #: Optional file of extra redaction regexes, one `name=pattern` per line.
    redaction_patterns_file: Path | None = None

    #: Allow the Vite dev server origin during development only.
    dev_cors_origin: str = "http://localhost:5173"

    def resolved_db_path(self) -> Path:
        path = self.db_path.expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sqlalchemy_url(self) -> str:
        return f"sqlite+pysqlite:///{self.resolved_db_path().as_posix()}"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def set_settings(settings: Settings) -> None:
    """Used by the CLI (--db) and by tests to point at a temporary database."""
    global _settings
    _settings = settings
