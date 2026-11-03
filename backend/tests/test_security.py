from datetime import UTC, datetime, timedelta

import pytest

from app import security
from app.ingest import apify_tokens as tk
from app.models import ActivityLog, CollectionRun, JobStatus, UserSession

ADMIN = {"email": "admin@techdeva.net", "name": "Rafay", "password": "Strong-pass-123"}
SEARCH = {"targets": [{"country": "AE", "city": "Dubai"}], "industries": ["beauty"], "budget_usd": 2}


def setup_admin(c):
    r = c.post("/auth/setup", json=ADMIN)
    assert r.status_code == 201
    return r


def add_user(c, email, role, password="Another-pass-456"):
    r = c.post("/users", json={"email": email, "name": email.split("@")[0], "password": password, "role": role})
    assert r.status_code == 201, r.text


def login(c, email, password):
    c.cookies.clear()
    return c.post("/auth/login", json={"email": email, "password": password})


def test_password_hashing():
    h = security.hash_password("Strong-pass-123")
    assert h.startswith("scrypt$") and "Strong" not in h
    assert security.check_password("Strong-pass-123", h) and not security.check_password("wrong", h)
    assert security.password_problem("short1") and security.password_problem("onlyletterslong")


def test_everything_needs_login_and_first_setup_creates_admin(raw_client):
    assert raw_client.get("/businesses").status_code == 401
    assert raw_client.get("/health").status_code == 200          # health stays public
    assert raw_client.get("/auth/status").json() == {"needs_setup": True}
    assert raw_client.post("/auth/setup", json={**ADMIN, "password": "weak"}).status_code == 400
    setup_admin(raw_client)
    assert raw_client.get("/auth/me").json()["role"] == "admin"
    assert raw_client.get("/businesses").status_code == 200       # cookie works
    assert raw_client.post("/auth/setup", json=ADMIN).status_code == 409  # only once
    cookie = raw_client.cookies.get("td_session")
    assert cookie and len(cookie) > 30


def test_wrong_password_is_throttled_and_logged(raw_client, maker):
    setup_admin(raw_client)
    for _ in range(5):
        assert login(raw_client, ADMIN["email"], "Wrong-pass-999").status_code == 401
    assert login(raw_client, ADMIN["email"], ADMIN["password"]).status_code == 429  # even the right one waits
    with maker() as s:
        assert s.query(ActivityLog).filter_by(action="login_failed").count() == 5


def test_roles(raw_client, monkeypatch):
    monkeypatch.setattr(tk, "tokens", lambda: ("apify_api_" + "X" * 24,))
    setup_admin(raw_client)
    add_user(raw_client, "sales@techdeva.net", "sales")
    add_user(raw_client, "view@techdeva.net", "viewer")

    assert login(raw_client, "sales@techdeva.net", "Another-pass-456").status_code == 200
    assert raw_client.post("/searches", json=SEARCH).status_code == 403          # spending = admin only
    assert raw_client.post("/apify/accounts", json={"token": "apify_api_" + "Y" * 24}).status_code == 403
    assert raw_client.get("/users").status_code == 403
    assert raw_client.post("/audits/bulk").status_code == 200                     # free audits are fine
    assert raw_client.get("/reports/export").status_code == 200

    assert login(raw_client, "view@techdeva.net", "Another-pass-456").status_code == 200
    assert raw_client.get("/businesses").status_code == 200
    assert raw_client.post("/audits/bulk").status_code == 403
    assert raw_client.get("/businesses/export").status_code == 403


def test_last_admin_cannot_be_removed_and_logout_ends_session(raw_client, maker):
    setup_admin(raw_client)
    me = raw_client.get("/auth/me").json()
    assert raw_client.patch(f"/users/{me['id']}", json={"role": "sales"}).status_code == 400
    assert raw_client.patch(f"/users/{me['id']}", json={"is_active": False}).status_code == 400
    raw_client.post("/auth/logout")
    assert raw_client.get("/auth/me").status_code == 401
    with maker() as s:
        assert s.query(UserSession).count() == 0


def test_expired_session_is_refused(raw_client, maker):
    setup_admin(raw_client)
    with maker() as s:
        row = s.query(UserSession).one()
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        s.commit()
    assert raw_client.get("/businesses").status_code == 401


def test_limits_are_enforced_and_changes_logged(raw_client, maker, monkeypatch):
    monkeypatch.setattr(tk, "tokens", lambda: ("apify_api_" + "X" * 24,))
    setup_admin(raw_client)
    assert raw_client.put("/settings/limits", json={"apify_monthly_cap_usd": 5, "bulk_audit_max": 1}).status_code == 200
    assert raw_client.put("/settings/limits", json={"bulk_audit_max": 9999}).status_code == 400
    assert raw_client.put("/settings/limits", json={"nonsense": 1}).status_code == 400
    with maker() as s:
        s.add(CollectionRun(requested_by="x", status=JobStatus.COMPLETED, params={}, spent_usd=4.0))
        s.commit()
    r = raw_client.post("/searches", json=SEARCH)  # 4 spent + 2 budget > 5 cap
    assert r.status_code == 400 and "Monthly Apify limit" in r.json()["detail"]
    assert raw_client.post("/searches", json={**SEARCH, "budget_usd": 50}).status_code == 400  # per-search cap 10
    acts = [a["action"] for a in raw_client.get("/activity").json()]
    assert "limits_changed" in acts and "setup_first_admin" in acts


@pytest.mark.parametrize("path", ["/users", "/activity"])
def test_admin_pages_need_login(raw_client, path):
    assert raw_client.get(path).status_code == 401
