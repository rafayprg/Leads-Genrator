# TechDeva Audit Platform

AI multi-agent lead generation + business audit (Apify → Main Agent → 6 specialist agents → report).
Plan, sub-phases and decisions: [../docs/audit-platform/PLAN.md](../docs/audit-platform/PLAN.md).
The older lead tool in `../leadgen/` is separate and unchanged.

## First start

The first visit asks you to create the **admin** account (name, email, password of 10+ characters).
Add teammates in Settings → Users as `sales` (audits, reports, exports) or `viewer` (read only).
Only admins can add Apify accounts, start paid searches, change limits and see the Activity log.
`demo.bat` has its own demo login, written at the top of `backend/scripts/demo_server.py`.

## Run (Windows)

Double-click `start.bat`: it starts the API on http://127.0.0.1:8800 and the dashboard on http://localhost:5190.

To try it without an Apify account or spending anything, double-click `demo.bat` instead: same dashboard,
but a separate `backend/data/demo.db` and a fake Apify that returns made-up businesses.

Dashboard pages: Overview · Lead Search · All Leads (click a lead for its sources and audits) · Settings (Apify accounts).

By hand:

```
cd backend
.venv\Scripts\python -m alembic upgrade head
.venv\Scripts\python -m uvicorn app.main:app --port 8800
cd ..\frontend
npm run dev
```

## One-time setup for the browser checks

```
cd backend
.venv\Scripts\python -m playwright install chromium
```

Import the old tool's leads once: `.venv\Scripts\python -m app.cli import-leadgen`.

## Tests

```
cd backend
.venv\Scripts\python -m pytest --cov=app
```

## API (http://127.0.0.1:8800/docs)

| Endpoint | What |
|---|---|
| `GET /meta` | Gulf countries/cities, industries, Apify prices |
| `GET/POST /apify/accounts`, `DELETE /apify/accounts/{last4}` | accounts with real credit (masked); add = test then save |
| `POST /searches/estimate` | cost before spending |
| `POST /searches` | start an Apify collection in the background (one at a time, hard $ cap) |
| `GET /searches`, `GET /searches/{id}` | status, live log, actor runs, cost, new/updated/rejected |
| `GET /businesses`, `GET /businesses/{id}` | list with filters; detail with per-field sources, social candidates, audits |
| `POST /audits`, `GET /audits/{id}` | queue audits (Agent 1 runs now; other agent tasks wait until built) |
| `POST/GET /businesses/{id}/website-audit` | run Agent 1 / read its findings, metrics, screenshots |
| `POST/GET /businesses/{id}/social` | run Agent 3 / read the social profiles it matched |
| `POST/GET /businesses/{id}/agents/social` | Agent 2, presence only (runs Agent 3 first) |
| `POST/GET /businesses/{id}/agents/automation` | Agent 4, audit only: tools in use + gaps mapped to TechDeva |
| `POST /businesses/{id}/full-audit` | Main Agent: every agent in order, ends with the audit record + opportunity score |
| `POST /audits/bulk?<All Leads filters>&limit=50` | full audit for matching leads |
| `GET /monitor`, `POST /tasks/{id}/retry` | Agent Monitor data; retry a failed task |
| `GET/POST /businesses/{id}/sales`, `GET /sales/summary` | call tracking: history (newest first), add a status/note/follow-up; counts + follow-ups due |
| `GET /audits/stale`, `POST /audits/reaudit-stale` | audits older than `audit_stale_days`; re-run them as one run |
| `GET /settings/storage`, `POST /reports/cleanup`, `POST /settings/backups` | admin: disk use + backups; remove old report versions; back up now |
| `GET /harvey/status`, `GET /harvey/candidates`, `POST /harvey/send`, `GET/PUT /settings/harvey` | Outreach: Harvey on the VPS over SSH only (status, audited leads ready to send, `check_only` then import) |
| `GET /results?run=&band=&q=&sales=&sort=finished\|score` | Audit Results: finished full audits + bulk runs with progress (bulk returns its `run` id) |
| `POST/GET /businesses/{id}/agents/reporting` | Agent 6: owner + internal reports (runs Agent 5 first) |
| `GET /reports`, `/reports/{id}/html`, `/reports/{id}/pdf` | list / open reports |
| `GET /reports/export?format=xlsx\|csv` | sales sheet: one row per audited business |
| `POST/GET /businesses/{id}/agents/organizer` | Agent 5: Unified Business Audit Dataset (merged issues, evidence check, contradictions, completeness, next steps) |
| `GET /businesses/export?format=xlsx\|csv` | Excel / CSV with the All Leads filters |
| `?audit=new\|audited\|all` on `/businesses`, `/businesses/export`, `/audits/bulk` | not-audited vs audited leads (bulk defaults to `new`, lists to `all`) |
| `GET /ai/status`, `POST/DELETE /ai/key`, `GET /ai/models`, `PUT /ai/model`, `POST /ai/test` | AI provider (Gemini/Groq, admin): key checked by listing models, saved only to `backend/.env`, shown masked. `as_backup: true` / `?backup=true` = the other provider, tried once when the main one fails |
| `GET/PUT /settings/report` | report languages (English / Roman Urdu), detail level, AI wording on/off |

Docker + PostgreSQL: see [DEPLOY.md](DEPLOY.md) (files ready, not run on this laptop).

## Layout

| Path | What |
|---|---|
| `backend/app/ingest/` | Apify layer (ported from `leadgen/`): accounts + switcher, records, dedupe, provenance |
| `backend/app/services/jobs.py` | background worker for searches, audit queue |
| `backend/app/agents/website/` | Agent 1: safe fetcher, discovery, technical/SEO/conversion checks, browser checks |
| `backend/app/agents/social/` | Agent 3 (profiles.py, finder.py) + Agent 2 presence-only (expert.py) |
| `backend/app/agents/main_agent/` | Main Agent: score.py (opportunity score) |
| `backend/app/agents/organizer/` | Agent 5: organize.py |
| `backend/app/agents/reporting/` | Agent 6: builder.py (sections), render.py (HTML template + PDF) |
| `backend/data/reports/` | report files per business (HTML + PDF, versioned) |
| `backend/app/agents/automation/` | Agent 4 Mode A: signatures.py (tools), capabilities.py (what TechDeva may offer), runner.py |
| `backend/app/services/audits.py` | audit worker: runs Agent 1 and Agent 3 tasks, saves results, retries |
| `backend/data/artifacts/` | screenshots per business and audit |
| `backend/app/models.py` | collection_runs + the 8 tables: businesses, data_sources, social_profiles, audit_jobs, agent_tasks, audit_findings, automation_runs, reports |
| `backend/migrations/` | Alembic migrations (SQLite now, PostgreSQL later: change `DATABASE_URL`) |
| `backend/.env` | secrets, owner-only file, never sent to the browser |
| `frontend/` | Vite + plain JavaScript; `/api/*` is proxied to the backend |
