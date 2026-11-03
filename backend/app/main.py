"""FastAPI entry point. Run: .venv\\Scripts\\python -m uvicorn app.main:app --port 8800"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from .agents.automation import runner as automation_runner
from .agents.social import finder as social_finder
from .agents.website import agent as website_agent
from .ai_routes import router as ai_router
from .auth_routes import router as auth_router
from .config import load_settings
from .db import SessionLocal, get_session
from .ingest import apify_maps
from .results_routes import router as results_router
from .routes import router
from .security import current_user
from .harvey_routes import router as harvey_router
from .calling_routes import router as calling_router
from .team_routes import router as team_router
from .ops_routes import router as ops_router
from .services.audits import AuditFn, AuditWorker, AutomationFn, FinderFn
from .services.backup import DailyBackup
from .services.harvey_auto import HarveyAutoSend
from .services.jobs import CollectFn, Worker

TEST_HOST = "testserver"  # FastAPI TestClient


class Health(BaseModel):
    status: str
    database: str
    apify_tokens: int
    ai_provider: str


def create_app(make_session: sessionmaker = SessionLocal, collect: CollectFn = apify_maps.collect,
               audit_fn: AuditFn = website_agent.audit, use_browser: bool = True,
               finder_fn: FinderFn = social_finder.find,
               automation_fn: AutomationFn = automation_runner.review, make_pdf: bool = True,
               daily_backup: bool = True) -> FastAPI:
    settings = load_settings()
    hosts = {*settings.allowed_hosts, TEST_HOST}

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.worker = Worker(make_session, collect)
        app.state.worker.start()
        app.state.audit_worker = AuditWorker(make_session, audit_fn, use_browser, finder_fn, automation_fn, make_pdf)
        app.state.audit_worker.start()
        app.state.backup = DailyBackup(make_session.kw["bind"])
        if daily_backup:
            app.state.backup.start()
        app.state.harvey_auto = HarveyAutoSend(make_session)  # does nothing until switched on
        app.state.harvey_auto.start()
        yield
        app.state.harvey_auto.stop()
        app.state.backup.stop()
        app.state.audit_worker.stop()
        app.state.worker.stop()

    app = FastAPI(title="TechDeva Audit Platform", version="0.3.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def only_this_computer(request: Request, call_next):
        """Other websites must not drive this API (it holds keys and can spend Apify credit)."""
        if (request.url.hostname or "") not in hosts:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and urlparse(origin).hostname not in hosts:
            return JSONResponse({"detail": "forbidden origin"}, status_code=403)
        return await call_next(request)

    @app.get("/health", response_model=Health)
    def health(session: Session = Depends(get_session)) -> Health:
        try:
            session.execute(text("SELECT 1"))
            db_state = "ok"
        except Exception as exc:  # report, never crash the health check
            db_state = f"error: {type(exc).__name__}"
        return Health(status="ok" if db_state == "ok" else "degraded", database=db_state,
                      apify_tokens=len(load_settings().apify_tokens), ai_provider=settings.ai_provider)

    app.include_router(auth_router)
    app.include_router(ai_router)  # each route checks the login/role itself
    # ops first: its fixed paths (/audits/stale) must win over /audits/{job_id}
    app.include_router(ops_router, dependencies=[Depends(current_user)])
    app.include_router(router, dependencies=[Depends(current_user)])  # every data route needs a login
    app.include_router(results_router, dependencies=[Depends(current_user)])
    app.include_router(harvey_router, dependencies=[Depends(current_user)])
    app.include_router(team_router)  # /auth/password must work before the first-login check passes
    app.include_router(calling_router)  # /auth/team + /auth/pin-login are public; the rest check the login
    return app


app = create_app()
