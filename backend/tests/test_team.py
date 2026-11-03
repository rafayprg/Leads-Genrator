from datetime import date

from app.models import Business, Role, User
from app.security import hash_password
from app.services import audits
from tests.test_main_agent import _business
from tests.test_reporting import _run_all


def _login(raw_client, email, password):
    r = raw_client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _admin(maker, raw_client):
    with maker() as s:
        s.add(User(email="boss@example.com", name="Boss", role=Role.ADMIN, password_hash=hash_password("Admin-pass-2026")))
        s.commit()
    _login(raw_client, "boss@example.com", "Admin-pass-2026")


def test_add_member_temp_password_must_be_changed_first(raw_client, maker):
    _admin(maker, raw_client)
    r = raw_client.post("/team", json={"name": "Sara", "email": "Sara@Example.com", "phone": "+92 300 1234567",
                                       "countries": ["PK"], "industries": ["beauty"], "daily_call_target": 40})
    assert r.status_code == 201
    member, pw = r.json(), r.json()["temp_password"]
    assert member["must_change_password"] and member["email"] == "sara@example.com" and len(pw) == 12
    assert raw_client.post("/team", json={"name": "x", "email": "sara@example.com"}).status_code == 409
    assert raw_client.post("/team", json={"name": "x", "email": "x@example.com", "countries": ["ZZ"]}).status_code == 400

    raw_client.post("/auth/logout")
    me = _login(raw_client, "sara@example.com", pw)
    assert me["must_change_password"] is True
    assert raw_client.get("/businesses").status_code == 403          # nothing else until the password is changed
    assert raw_client.post("/auth/password", json={"current": pw, "new": "short"}).status_code == 400
    assert raw_client.post("/auth/password", json={"current": "wrong", "new": "Sara-new-2026"}).status_code == 400
    assert raw_client.post("/auth/password", json={"current": pw, "new": "Sara-new-2026"}).status_code == 204
    assert raw_client.get("/businesses").status_code == 200
    assert raw_client.get("/auth/me").json()["must_change_password"] is False


def test_team_needs_login_and_admin_for_changes(raw_client, maker):
    assert raw_client.get("/team").status_code == 401
    assert raw_client.get("/team/permissions").status_code == 401
    assert raw_client.get("/team/performance").status_code == 401
    with maker() as s:
        s.add(User(email="rep@example.com", name="Rep", role=Role.SALES, password_hash=hash_password("Rep-pass-2026")))
        s.commit()
    _login(raw_client, "rep@example.com", "Rep-pass-2026")
    assert raw_client.get("/team").status_code == 200
    assert raw_client.post("/team", json={"name": "x", "email": "x@example.com"}).status_code == 403
    assert raw_client.put("/team/permissions", json={"sales": {"export": False}}).status_code == 403


def test_permissions_switch_actions_off_for_sales(raw_client, maker):
    _admin(maker, raw_client)
    with maker() as s:
        s.add(User(email="rep@example.com", name="Rep", role=Role.SALES, password_hash=hash_password("Rep-pass-2026")))
        s.commit()
    r = raw_client.put("/team/permissions", json={"sales": {"export": False}})
    assert r.status_code == 200 and r.json()["roles"]["sales"]["export"] is False
    assert raw_client.put("/team/permissions", json={"sales": {"fly": True}}).status_code == 400
    assert raw_client.get("/businesses/export?format=csv").status_code == 200  # admins always can
    raw_client.post("/auth/logout")
    _login(raw_client, "rep@example.com", "Rep-pass-2026")
    blocked = raw_client.get("/businesses/export?format=csv")
    assert blocked.status_code == 403 and "may not" in blocked.json()["detail"]
    assert raw_client.post("/leads/assign", json={"business_ids": [1], "user_id": None}).status_code == 403  # off by default


def test_assign_take_auto_assign_and_leaving_member(client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    client.app.state.audit_worker.stop()
    with maker() as s:
        pk = User(email="pk@example.com", name="Pak rep", role=Role.SALES, password_hash="x", countries=["PK"])
        ae = User(email="ae@example.com", name="UAE rep", role=Role.SALES, password_hash="x", countries=["AE"])
        away = User(email="away@example.com", name="Away", role=Role.SALES, password_hash="x", away=True)
        s.add_all([pk, ae, away])
        s.commit()
        pk_id, ae_id = pk.id, ae.id
    a = _business(maker)
    b = _business(maker, title="Other Salon", placeId="P2", phoneUnformatted="+97142220000", website="https://o.ae",
                  location={"lat": 25.3, "lng": 55.4})
    c = _business(maker, title="Third Salon", placeId="P3", phoneUnformatted="+97142220001", website="https://t.ae",
                  location={"lat": 25.31, "lng": 55.41})
    for bid in (a, b):
        _run_all(maker, bid)

    r = client.post("/leads/auto-assign", json={"audit": "audited"}).json()
    assert r["assigned"] == 2 and r["per_member"] == [{"id": ae_id, "name": "UAE rep", "leads": 2}]  # Dubai leads -> UAE rep
    assert [x["id"] for x in client.get("/businesses", params={"owner": str(ae_id)}).json()["items"]] == sorted([a, b], reverse=True)
    assert [x["id"] for x in client.get("/businesses", params={"owner": "none"}).json()["items"]] == [c]

    assert client.post("/leads/assign", json={"business_ids": [c], "user_id": pk_id}).json() == {"assigned": 1}
    assert client.get(f"/businesses/{c}").json()["owner_id"] == pk_id
    assert client.post(f"/businesses/{c}/take").status_code == 409  # someone else owns it

    assert client.patch(f"/team/{ae_id}", json={"is_active": False}).status_code == 200
    with maker() as s:  # a member who leaves hands the leads back
        assert s.get(Business, a).owner_id is None and s.get(Business, b).owner_id is None
    assert client.post("/leads/assign", json={"business_ids": [a], "user_id": ae_id}).status_code == 400


def test_my_work_and_performance(raw_client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    raw_client.app.state.audit_worker.stop()
    with maker() as s:
        s.add(User(email="rep@example.com", name="Rep", role=Role.SALES, password_hash=hash_password("Rep-pass-2026"),
                   daily_call_target=5))
        s.commit()
        rep_id = s.query(User).filter_by(email="rep@example.com").one().id
    a = _business(maker)
    b = _business(maker, title="Other Salon", placeId="P2", phoneUnformatted="+97142220000", website="https://o.ae",
                  location={"lat": 25.3, "lng": 55.4})
    _run_all(maker, a)
    with maker() as s:
        for bid in (a, b):
            s.get(Business, bid).owner_id = rep_id
        s.commit()
    _login(raw_client, "rep@example.com", "Rep-pass-2026")
    w = raw_client.get("/me/work").json()
    assert w["owned"] == 2 and w["to_call"][0]["id"] == a and w["next"]["id"] == a  # audited, best score first
    raw_client.post(f"/businesses/{a}/sales", json={"status": "follow_up", "follow_up_on": date.today().isoformat()})
    raw_client.post(f"/businesses/{b}/sales", json={"status": "won"})
    w = raw_client.get("/me/work").json()
    assert [x["id"] for x in w["follow_ups"]] == [a] and w["calls_today"] == 2 and w["won_week"] == 1
    assert w["next"]["id"] == a and not w["to_call"]
    resp = raw_client.get("/team/performance?days=7")
    assert resp.status_code == 200, resp.text
    perf = resp.json()["members"]
    me = next(m for m in perf if m["id"] == rep_id)
    assert me["calls"] == 2 and me["won"] == 1 and me["warm"] == 2 and me["hit_rate"] == 100
    assert me["calls_today"] == 2 and me["daily_call_target"] == 5 and me["leads_owned"] == 2 and me["follow_ups_due"] == 1
    assert raw_client.get("/team/performance?days=3").status_code == 422
