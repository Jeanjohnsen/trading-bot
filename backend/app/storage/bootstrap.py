from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.settings import get_settings
import app.storage.database as storage_db
import app.storage.models  # noqa: F401


def sqlite_path_from_url(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError(f"Only sqlite URLs are supported, got: {database_url}")

    raw_path = database_url.removeprefix("sqlite:///")
    if raw_path == ":memory:":
        return Path(":memory:")
    return Path(raw_path).resolve()


def _configure_sqlite_wal(database_path: Path) -> None:
    if str(database_path) == ":memory:":
        return

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.commit()


def bootstrap_database() -> Path:
    settings = get_settings()
    database_path = sqlite_path_from_url(settings.database_url)
    storage_db.configure_database(settings.database_url)
    _configure_sqlite_wal(database_path)
    storage_db.Base.metadata.create_all(bind=storage_db.engine)
    return database_path
