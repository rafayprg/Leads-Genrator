import time

import pytest

from app.ingest import apify_tokens as tk

TOKEN = "apify_api_" + "Z" * 20 + "9999"
SEARCH = {"targets": [{"country": "AE", "city": "Dubai"}], "industries": ["beauty"], "budget_usd": 2,
          "per_search": 10}


@pytest.fixture()
def one_account(monkeypatch):
    monkeypatch.setattr(tk, "tokens", lambda: (TOKEN,))
    monkeypatch.setattr(tk, "status", lambda t, fresh=False: tk.TokenStatus(
        key=tk.mask(t), last4=t[-4:], ok=True, message="OK", username="acct", remaining_usd=4.5, limit_usd=5,
        used_usd=0.5))


def wait_done(client, run_id, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        run = client.get(f"/searches/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.05)
    raise AssertionError("search did not finish")


def test_meta_lists_gulf_and_south_asia_cities_and_industries(client):
    m = client.get("/meta").json()
    regions = {cc: c["region"] for cc, c in m["countries"].items()}
    assert [cc for cc, r in regions.items() if r == "Gulf"] == ["AE", "SA", "QA", "KW", "BH", "OM"]
    assert [cc for cc, r in regions.items() if r == "South Asia"] == ["PK", "IN"]
    assert "Dubai" in m["countries"]["AE"]["cities"] and "Lahore" in m["countries"]["PK"]["cities"]
    assert m["industries"]["beauty"]["searches"] == 6


def test_south_asia_search_estimate_and_phones(client):
    from app.ingest.gulf import expand_targets
    from app.ingest.normalize import format_phone
    assert len(expand_targets("gulf")) == 34  # "gulf" still means the 6 Gulf countries only
    assert format_phone("0300 1234567", "PK") == ("+923001234567", "mobile")
    assert format_phone("+91 98765 43210", "IN") == ("+919876543210", "mobile")
    body = {**SEARCH, "targets": [{"country": "PK", "city": "Karachi"}, {"country": "IN", "city": "Hyderabad"},
                                  {"country": "PK", "city": "Hyderabad"}]}
    e = client.post("/searches/estimate", json=body).json()
    assert e["cities"] == 3
    bad = {**SEARCH, "targets": [{"country": "PK", "city": "Dubai"}]}
    assert client.post("/searches/estimate", json=bad).status_code == 422


def test_search_needs_an_apify_account(client, monkeypatch):
    monkeypatch.setattr(tk, "tokens", lambda: ())
    r = client.post("/searches", json=SEARCH)
    assert r.status_code == 400 and "No Apify account" in r.json()["detail"]


@pytest.mark.parametrize("bad", [
    {**SEARCH, "targets": [{"country": "AE", "city": "Paris"}]},
    {**SEARCH, "industries": ["casinos"]},
    {**SEARCH, "budget_usd": 0.1},
])
def test_search_input_is_validated(client, one_account, bad):
    assert client.post("/searches", json=bad).status_code == 422


def test_estimate(client, one_account):
    e = client.post("/searches/estimate", json=SEARCH).json()
    assert e["searches"] == 6 and e["max_places"] == 60 and e["credit_left_usd"] == 4.5


def test_search_runs_in_background_and_saves_businesses_with_audits(client, one_account):
    r = client.post("/searches", json={**SEARCH, "audit": {"social": False}})
    assert r.status_code == 202
    run = wait_done(client, r.json()["id"])
    assert run["status"] == "completed" and run["new_businesses"] == 2 and run["records_found"] == 3
    assert run["spent_usd"] == pytest.approx(0.0135) and any("fake apify run" in line for line in run["log"])

    page = client.get("/businesses", params={"country": "AE", "q": "smile"}).json()
    assert page["total"] == 1 and page["items"][0]["business_id"].startswith("BUS-")
    detail = client.get(f"/businesses/{page['items'][0]['id']}").json()
    assert {s["field"] for s in detail["data_sources"]} >= {"name", "phone"}
    tasks = {t["agent_name"] for t in detail["audit_jobs"][0]["tasks"]}
    assert "website_expert" in tasks and "social_media_expert" not in tasks  # social switched off


def test_second_search_while_one_runs_is_refused(client, one_account, maker):
    from app.models import CollectionRun, JobStatus
    with maker() as s:
        s.add(CollectionRun(requested_by="x", status=JobStatus.RUNNING, params={}))
        s.commit()
    assert client.post("/searches", json=SEARCH).status_code == 409


def test_queue_audit_and_skip_duplicates(client, one_account):
    run = wait_done(client, client.post("/searches", json=SEARCH).json()["id"])
    assert run["status"] == "completed"
    ids = [b["id"] for b in client.get("/businesses").json()["items"]]
    client.app.state.audit_worker.stop()  # keep jobs queued: with 3 fast workers they could finish in between
    first = client.post("/audits", json={"business_ids": ids})
    assert first.status_code == 201 and len(first.json()) == 2
    assert client.post("/audits", json={"business_ids": ids}).json() == []  # already queued
    assert client.post("/audits", json={"business_ids": [999]}).status_code == 404
    # Agent 1 may already have run; the other agents keep the job open
    assert client.get(f"/audits/{first.json()[0]['id']}").json()["status"] in ("queued", "running", "partial")


def test_accounts_are_masked(client, one_account):
    body = client.get("/apify/accounts").json()
    assert body["accounts"][0]["key"] == "…9999" and TOKEN not in str(body)


def test_other_websites_are_blocked(client):
    assert client.get("/meta", headers={"host": "evil.com"}).status_code == 403
    r = client.post("/searches/estimate", json=SEARCH, headers={"origin": "https://evil.com"})
    assert r.status_code == 403


def test_stats_for_overview(client, one_account):
    wait_done(client, client.post("/searches", json={**SEARCH, "audit": {}}).json()["id"])
    s = client.get("/stats").json()
    assert s["businesses"] == 2 and s["by_country"] == {"AE": 2} and sum(s["audits"].values()) == 2
    assert s["apify"] == {"accounts": 1, "credit_left_usd": 4.5}
    assert s["searches"][0]["new_businesses"] == 2 and s["failed_tasks"] == 0
