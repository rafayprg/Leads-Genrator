"""One-time move of the laptop's SQLite data into the server's PostgreSQL (DEPLOY.md: "export/import").

Run inside the backend container after `alembic upgrade head` made the empty schema:
    python scripts/sqlite_to_postgres.py /app/data/audit.db "C:\\Users\\...\\backend\\data"
Every table is copied in foreign-key order with the same ids, laptop file paths are rewritten to /app/data,
and the id sequences are moved past the copied rows. Refuses to run if the target already has businesses.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select, text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import models  # noqa: E402,F401  (registers every table on Base.metadata)
from app.config import load_settings  # noqa: E402
from app.db import Base  # noqa: E402

TARGET_DATA = "/app/data"
BATCH = 500


def rewrite(value, old_prefix: str):
    """Laptop paths inside strings, lists and dicts -> server paths."""
    if isinstance(value, str) and old_prefix in value:
        head, _, tail = value.partition(old_prefix)
        return head + TARGET_DATA + tail.replace("\\", "/")
    if isinstance(value, list):
        return [rewrite(v, old_prefix) for v in value]
    if isinstance(value, dict):
        return {k: rewrite(v, old_prefix) for k, v in value.items()}
    return value


def main(sqlite_path: str, old_prefix: str) -> None:
    src = create_engine(f"sqlite:///{sqlite_path}")
    dst = create_engine(load_settings().database_url)
    if dst.dialect.name != "postgresql":
        raise SystemExit("DATABASE_URL is not PostgreSQL")
    with dst.connect() as c:
        if c.scalar(select(func.count()).select_from(models.Business.__table__)):
            raise SystemExit("Target already has businesses; not copying twice")
    with src.connect() as s, dst.begin() as d:
        for table in Base.metadata.sorted_tables:
            rows = [{k: rewrite(v, old_prefix) for k, v in r._mapping.items()} for r in s.execute(select(table))]
            for i in range(0, len(rows), BATCH):
                d.execute(table.insert(), rows[i:i + BATCH])
            if "id" in table.c and rows:
                d.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                               f"(SELECT MAX(id) FROM \"{table.name}\"))"))
            print(f"{table.name}: {len(rows)}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
