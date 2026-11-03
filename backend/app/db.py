"""Database engine and session. SQLite on the laptop, PostgreSQL later: only DATABASE_URL changes."""
from __future__ import annotations

from collections.abc import Iterator

from datetime import datetime

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import load_settings


class Base(DeclarativeBase):
    # every timestamp keeps its timezone (UTC), so PostgreSQL later gets timestamptz, not naive times
    type_annotation_map = {datetime: DateTime(timezone=True)}


def make_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    # two background workers + requests write at once: wait up to 30 s for a lock instead of the default 5 s
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30} if is_sqlite else {})
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # foreign keys are off by default in SQLite
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


engine = make_engine(load_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
