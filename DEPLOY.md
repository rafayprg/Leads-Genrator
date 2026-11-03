# Running with Docker + PostgreSQL (Phase 9.4)

Status 31 Oct 2026: files written and the PostgreSQL schema was generated from the migrations
(`alembic upgrade head --sql`, 14 tables, timezone-aware timestamps). The containers themselves were **not run**,
because Docker is not installed on this laptop. Try them on a machine with Docker before relying on them.

```
cp .env.example .env            # set POSTGRES_PASSWORD (long random)
cp backend/.env.example backend/.env
docker compose up -d --build
# open http://localhost:8080 -> first visit asks you to create the admin account
```

Notes
- One process holds the API and the background workers (3 threads). That is enough for one office;
  Redis/Celery is only needed when several API servers must share one queue, so it is not added yet.
- The laptop's SQLite data does not move by itself. Moving it to PostgreSQL is a separate step (export/import)
  to do once, when the server is ready.
- On a server (Phase 9.5, only with Rafay's OK): own compose project (`name: techdeva-audit`), never inside the
  TechDeva/InstantGrill compose; HTTPS in front (Caddy or nginx) with `COOKIE_SECURE=1` and
  `ALLOWED_HOSTS=<domain>`; nightly `pg_dump` backups of the `dbdata` volume and the `artifacts` volume.
