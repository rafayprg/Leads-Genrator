"""Daily copy of the SQLite database (data/backups/audit-YYYY-MM-DD.db), newest KEEP kept.

Uses SQLite's online backup, so it is safe while workers are writing. PostgreSQL is backed up
on the server instead (see DEPLOY.md), so this does nothing there.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import Engine

KEEP = 7
CHECK_EVERY_S = 3600
log = logging.getLogger(__name__)


def sqlite_file(engine: Engine) -> Path | None:
    url = engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


def folder_for(db: Path) -> Path:
    return db.parent / "backups"


def backup_now(db: Path, keep: int = KEEP) -> Path:
    target_dir = folder_for(db)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{db.stem}-{datetime.now(UTC):%Y-%m-%d}.db"
    tmp = target.with_suffix(".tmp")
    src, dst = sqlite3.connect(db), sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    tmp.replace(target)  # a half-written copy never looks like a finished backup
    for old in sorted(target_dir.glob(f"{db.stem}-*.db"))[:-keep]:
        old.unlink(missing_ok=True)
    return target


def list_backups(db: Path) -> list[dict]:
    files = sorted(folder_for(db).glob(f"{db.stem}-*.db"), reverse=True)
    return [{"name": f.name, "size_mb": round(f.stat().st_size / 1e6, 2),
             "at": datetime.fromtimestamp(f.stat().st_mtime, UTC).isoformat(timespec="seconds")} for f in files]


class DailyBackup:
    """Background thread: one backup per day (on start if today's is missing, then checked hourly)."""

    def __init__(self, engine: Engine):
        self.db = sqlite_file(engine)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        if self.db is None:
            return
        self._thread = threading.Thread(target=self._loop, name="daily-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            today = folder_for(self.db) / f"{self.db.stem}-{datetime.now(UTC):%Y-%m-%d}.db"
            if not today.exists():
                try:
                    backup_now(self.db)
                    self.last_error = None
                except (OSError, sqlite3.Error) as e:  # keep the app running; shown in Settings
                    self.last_error = f"{type(e).__name__}: {e}"
                    log.warning("daily backup failed: %s", self.last_error)
            self._stop.wait(CHECK_EVERY_S)
