from app.models import Business, Role, SalesNote, User
from app.security import hash_password
from tests.test_main_agent import _business
from tests.test_team import _admin


def _member(maker, name="Waleed", email="waleed@example.com"):
    with maker() as s:
        u = User(email=email, name=name, role=Role.SALES, password_hash=hash_password("Temp-pass-2026"),
                 must_change_password=True)
        s.add(u)
        s.commit()
        return u.id


def _leads(maker):
    a = _business(maker)
    b = _business(maker, title="Lahore Glow", placeId="P2", phoneUnformatted="+923001112222", website="https://lg.pk",
                  city="Lahore", location={"lat": 31.5, "lng": 74.3})
    with maker() as s:  # _business always saves as AE/Dubai; move one to Lahore, PK
        x = s.get(Business, b)
        x.country, x.city = "PK", "Lahore"
        s.commit()
    return a, b


def test_pin_login_lists_names_only_and_skips_the_temp_password_step(raw_client, maker):
    _admin(maker, raw_client)
    uid = _member(maker)
    assert raw_client.put(f"/team/{uid}/pin", json={"pin": "12ab"}).status_code == 400
    assert raw_client.put(f"/team/{uid}/pin", json={"pin": "4821"}).status_code == 204
    raw_client.post("/auth/logout")
    team = raw_client.get("/auth/team").json()
    assert team == [{"id": uid, "name": "Waleed"}]  # no PIN, no email
    assert raw_client.post("/auth/pin-login", json={"user_id": uid, "pin": "0000"}).status_code == 401
    me = raw_client.post("/auth/pin-login", json={"user_id": uid, "pin": "4821"})
    assert me.status_code == 200 and me.json()["must_change_password"] is False
    assert raw_client.get("/calling/list").json()["total"] == 0


def test_pin_login_is_throttled(raw_client, maker):
    _admin(maker, raw_client)
    uid = _member(maker)
    raw_client.put(f"/team/{uid}/pin", json={"pin": "4821"})
    codes = [raw_client.post("/auth/pin-login", json={"user_id": uid, "pin": "1111"}).status_code for _ in range(12)]
    assert codes[-1] == 429


def test_assign_a_whole_city_then_call_list_and_funnel(client, maker):
    dubai, lahore = _leads(maker)
    uid = _member(maker)
    rows = {r["city"]: r for r in client.get("/calling/cities").json()}
    assert rows["Lahore"]["unassigned"] == 1 and rows["Dubai"]["unassigned"] == 1

    assert client.post("/calling/assign-city", json={"country": "PK", "city": "Lahore", "user_id": uid}).json()["assigned"] == 1
    rows = {r["city"]: r for r in client.get("/calling/cities?country=PK").json()}
    assert rows["Lahore"]["owners"] == [{"id": uid, "name": "Waleed", "leads": 1}] and "Dubai" not in rows

    lst = client.get(f"/calling/list?user_id={uid}").json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == lahore and lst["items"][0]["status"] == "pending"
    assert client.post(f"/businesses/{lahore}/sales", json={"status": "not_on_whatsapp", "note": "no WA"}).status_code == 201
    lst = client.get(f"/calling/list?user_id={uid}&status=not_on_whatsapp").json()
    assert [i["id"] for i in lst["items"]] == [lahore] and lst["counts"]["pending"] == 0

    f = client.get("/calling/funnel").json()
    assert f["assigned"] == 1 and f["unassigned"] == 1 and f["by_status"]["not_on_whatsapp"] == 1
    assert f["members"][0]["name"] == "Waleed" and f["members"][0]["called"] == 1

    assert client.post("/calling/assign-city", json={"country": "PK", "city": "Lahore", "user_id": None}).json()["assigned"] == 1
    with maker() as s:
        assert s.get(Business, lahore).owner_id is None and s.query(SalesNote).count() == 1  # history kept


def test_only_admin_sees_another_members_list(raw_client, maker):
    _admin(maker, raw_client)
    uid = _member(maker)
    other = _member(maker, "Fareed", "fareed@example.com")
    raw_client.put(f"/team/{uid}/pin", json={"pin": "4821"})
    raw_client.post("/auth/logout")
    raw_client.post("/auth/pin-login", json={"user_id": uid, "pin": "4821"})
    assert raw_client.get(f"/calling/list?user_id={other}").status_code == 403
    assert raw_client.post("/calling/assign-city", json={"country": "AE", "city": "Dubai", "user_id": uid}).status_code == 403


def test_caller_only_has_the_calling_desk_and_only_own_leads(raw_client, maker):
    _admin(maker, raw_client)
    dubai, lahore = _leads(maker)
    uid = _member(maker)
    assert raw_client.patch(f"/team/{uid}", json={"role": "caller"}).status_code == 200
    raw_client.put(f"/team/{uid}/pin", json={"pin": "4821"})
    raw_client.post("/calling/assign-city", json={"country": "PK", "city": "Lahore", "user_id": uid})
    raw_client.post("/auth/logout")
    me = raw_client.post("/auth/pin-login", json={"user_id": uid, "pin": "4821"}).json()
    assert me["role"] == "caller"

    assert [i["id"] for i in raw_client.get("/calling/list").json()["items"]] == [lahore]
    assert raw_client.post(f"/businesses/{lahore}/sales", json={"status": "connected"}).status_code == 201
    assert raw_client.get(f"/businesses/{lahore}/sales").status_code == 200
    # someone else's lead, and every other page of the platform, are closed
    assert raw_client.post(f"/businesses/{dubai}/sales", json={"status": "connected"}).status_code == 403
    for path in ("/businesses", f"/businesses/{lahore}", "/stats", "/team", "/calling/funnel", "/calling/cities",
                 "/reports", "/harvey/status", "/me/work", "/activity", "/ai/status", "/settings/report"):
        assert raw_client.get(path).status_code == 403, path
    assert raw_client.post("/auth/logout").status_code == 204


def test_split_unassigned_leads_by_count_per_member(client, maker):
    ids = [_business(maker, title=f"Salon {i}", placeId=f"S{i}", phoneUnformatted=f"+97150000{i:04d}",
                     website=f"https://s{i}.ae", location={"lat": 25 + i / 100, "lng": 55}) for i in range(5)]
    a, b = _member(maker), _member(maker, "Fareed", "fareed@example.com")
    with maker() as s:  # one lead already belongs to someone: never moved
        s.get(Business, ids[0]).owner_id = a
        s.commit()
    assert client.get("/businesses?owner=none&limit=1").json()["total"] == 4
    assert client.get("/businesses?owner=any&limit=1").json()["total"] == 1
    r = client.post("/leads/distribute", json={"country": ["AE"], "shares": [{"user_id": b, "count": 3}, {"user_id": a, "count": 5}]}).json()
    assert r["available"] == 4 and r["assigned"] == 4
    assert [(m["name"], m["assigned"]) for m in r["per_member"]] == [("Fareed", 3), ("Waleed", 1)]
    assert client.get("/businesses?owner=none&limit=1").json()["total"] == 0
    assert client.post("/leads/distribute", json={"shares": [{"user_id": a, "count": 1}, {"user_id": a, "count": 2}]}).status_code == 400
    assert client.post("/leads/distribute", json={"shares": [{"user_id": 9999, "count": 1}]}).status_code == 400
