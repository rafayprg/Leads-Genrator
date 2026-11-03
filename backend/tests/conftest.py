"""Each test gets a fresh temporary database file; the real data/audit.db is never touched."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401  (registers tables)
from app.db import Base, get_session
from app.ingest import apify_maps
from app.main import create_app
from tests.fakes import place


@pytest.fixture(autouse=True)
def no_real_ai(monkeypatch):
    """backend/.env may hold a real Gemini/Groq key; tests must never call the real provider.
    The AI tests switch a fake model on themselves."""
    monkeypatch.setenv("AI_PROVIDER", "none")
    monkeypatch.delenv("HARVEY_SSH_HOST", raising=False)  # and never the real VPS (Harvey tests use a fake ssh)


@pytest.fixture()
def engine(tmp_path):
    # a real file, not ":memory:" + StaticPool: the worker thread and requests need separate connections,
    # exactly like the app, or one thread's rollback undoes the other's writes
    eng = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                        connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _record):  # same settings as the app (app/db.py)
        dbapi_conn.execute("PRAGMA foreign_keys=ON")
        dbapi_conn.execute("PRAGMA journal_mode=WAL")

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def maker(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def session(maker):
    s = maker()
    yield s
    s.close()


def fake_collect(targets, industries, budget_usd, per_search=40, log=print, on_batch=None, **_):
    """Stands in for apify_maps.collect: two places, one of them twice."""
    log("fake apify run")
    items = [place(), place(placeId="ChIJ1b"), place(title="Bright Smile Dental", placeId="ChIJ2",
                                                     phoneUnformatted="+97142223333", website="https://brightsmile.ae",
                                                     instagram="", location={"lat": 25.2, "lng": 55.3})]
    cc, city = targets[0]
    recs = tuple(r for r in (apify_maps.to_record(i, cc, city, industries[0]) for i in items) if r)
    info = {"run_id": "r1", "account": "acct", "status": "SUCCEEDED", "items": 3, "cost_usd": 0.0135,
            "city": city, "country": cc, "industry": industries[0]}
    if on_batch:
        on_batch(list(recs), info)
    return apify_maps.CollectResult(recs, 0.0135, "", (info,))


def fake_website_audit(website_url, industry="", shots_dir=None, fetcher=None, use_browser=True, **limits):
    """Stands in for Agent 1: one finding, no network."""
    from app.agents.findings import Finding, S
    from app.agents.website.agent import WebsiteAudit
    if not website_url:
        return WebsiteAudit("skipped", "", limitations=["No website on record for this business"])
    return WebsiteAudit("completed", website_url, pages={"home": website_url},
                        findings=[Finding("conversion", "No WhatsApp contact link", S.MEDIUM, "Add a WhatsApp button",
                                          evidence={"url": website_url}, source_url=website_url)])


def fake_find(business_name, website_url, known_links, fetcher=None):
    """Stands in for Agent 3: no network, uses only the links already on record."""
    from app.agents.social import finder
    return finder.find(business_name, None, known_links)


def fake_review(website_url, industry="", fetcher=None):
    """Stands in for Agent 4: no network."""
    from app.agents.automation import runner
    if not website_url:
        return runner.AutomationReview("skipped")
    res = runner.AutomationReview("completed")
    for opp, finding in runner.opportunities(industry, [], {"forms": 0, "tel_links": 1, "whatsapp_links": 0,
                                                            "booking_wording": False}):
        res.opportunities.append(opp)
        res.findings.append(finding)
    return res


def _app(maker):
    app = create_app(make_session=maker, collect=fake_collect, audit_fn=fake_website_audit, use_browser=False,
                     finder_fn=fake_find, automation_fn=fake_review, make_pdf=False, daily_backup=False)

    def _session():
        s = maker()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    return app


@pytest.fixture()
def client(maker):
    """Logged in as an admin (login itself is tested with raw_client)."""
    from app.models import Role, User
    from app.security import current_user
    app = _app(maker)
    app.dependency_overrides[current_user] = lambda: User(id=0, email="admin@test.local", name="Test admin",
                                                          role=Role.ADMIN, is_active=True)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def raw_client(maker):
    """No login: the real cookie flow."""
    from app import security
    security._failures.clear()
    app = _app(maker)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
