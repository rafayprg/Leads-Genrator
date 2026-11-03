import csv
import io
import json

import pytest

from app import harvey_routes
from app.harvey import bridge
from app.ingest import apify_tokens
from app.models import Business
from app.services import audits
from tests.test_main_agent import _business
from tests.test_reporting import _run_all

STATUS_OUT = "\n".join([
    "@@/api/harvey/status", json.dumps({"running": True}),
    "@@/api/sending-mode", json.dumps({"mode": "approval"}),
    "@@/api/stats", json.dumps({"pipeline": {"to_write": 4, "contacted": 2}, "prospects": {"total": 6}}),
    "@@/api/outbox", json.dumps({"paused": False, "pending": [
        {"id": "a1", "subject": "Quick idea", "to_email": "owner@example.com", "body": "SECRET BODY",
         "context": {"company": "Example Salon", "contact": "Sam", "email_status": "verified"}}],
        "approved": [], "sent": [{}, {}], "failed": []}),
])


@pytest.fixture()
def fake_vps(tmp_path, monkeypatch):
    """Harvey set up against a fake ssh: records each remote command and the bytes sent on stdin."""
    key = tmp_path / "id_test"
    key.write_text("not a real key")
    monkeypatch.setenv("HARVEY_SSH_HOST", "203.0.113.5")
    monkeypatch.setenv("HARVEY_SSH_KEY", str(key))
    monkeypatch.setattr(bridge, "_cache", {})
    calls = []

    def ssh(cfg, remote, data=None, timeout=bridge.SSH_TIMEOUT_S):
        calls.append({"remote": remote, "data": data})
        if "harvey import" in remote:
            if "--check" in remote:
                return "  x.csv: 2 businesses, 2 with a website, 1 with an owner and email\n  Check only: nothing was saved.\n"
            return "  x.csv: 2 businesses, 2 with a website, 1 with an owner and email\n  IMPORT — 1 new businesses, 1 already known\n"
        return STATUS_OUT

    monkeypatch.setattr(bridge, "_ssh", ssh)
    return calls


def test_not_set_up_says_so(monkeypatch):
    monkeypatch.delenv("HARVEY_SSH_HOST", raising=False)
    monkeypatch.setattr(bridge, "_cache", {})
    st = bridge.status()
    assert st["configured"] is False and st["reachable"] is False


def test_status_reads_everything_in_one_call_and_never_the_body(fake_vps):
    st = bridge.status(fresh=True)
    assert st["reachable"] and st["running"] and st["mode"] == "approval" and st["prospects"] == 6
    assert st["outbox"] == {"pending": 1, "approved": 0, "sent": 2, "failed": 0}
    assert st["pending_preview"][0]["company"] == "Example Salon" and "SECRET BODY" not in json.dumps(st)
    assert len(fake_vps) == 1 and "dashboard-token" in fake_vps[0]["remote"] and "127.0.0.1:5555" in fake_vps[0]["remote"]
    bridge.status()
    assert len(fake_vps) == 1  # cached


def test_broken_dashboard_answer_is_reported(fake_vps, monkeypatch):
    monkeypatch.setattr(bridge, "_ssh", lambda *a, **k: "@@/api/stats\nnot json\n")
    st = bridge.status(fresh=True)
    assert st["reachable"] is False and "dashboard" in st["error"]


def test_csv_keeps_harvey_columns_and_one_line_per_lead():
    raw = bridge.to_csv([{"name": "A\nB", "website": "https://a.example", "email": "x@example.com", "extra": "dropped"}])
    rows = list(csv.DictReader(io.StringIO(raw.decode())))
    assert tuple(rows[0]) == bridge.CSV_COLUMNS and rows[0]["name"] == "A B" and len(rows) == 1


def test_send_checks_then_imports_marks_sent_and_never_resends(client, maker, fake_vps, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path / "reports")
    a = _business(maker)
    b = _business(maker, title="Other Salon", placeId="P2", phoneUnformatted="+97142220000", website="https://o.ae",
                  location={"lat": 25.3, "lng": 55.4})
    _run_all(maker, a)
    _run_all(maker, b)
    cand = client.get("/harvey/candidates").json()
    assert cand["total"] == 2 and cand["already_sent"] == 0

    check = client.post("/harvey/send", json={"business_ids": [a, b], "check_only": True}).json()
    assert check["check_only"] and check["with_website"] == 2 and client.get("/harvey/candidates").json()["total"] == 2

    done = client.post("/harvey/send", json={"business_ids": [a, b], "check_only": False}).json()
    assert done["new"] == 1 and done["already_known"] == 1 and done["leads"] == 2
    imp = fake_vps[-1]
    assert "--check" not in imp["remote"] and "--limit 2" in imp["remote"] and 'rm -f "$f"' in imp["remote"]
    assert "Other Salon" in imp["data"].decode() and "Other Salon" not in imp["remote"]  # lead data only on stdin
    with maker() as s:
        assert s.get(Business, a).details["harvey"]["batch"]
    assert client.get("/harvey/candidates").json()["total"] == 0
    again = client.post("/harvey/send", json={"business_ids": [a], "check_only": False})
    assert again.status_code == 400  # already sent
    assert client.get("/activity").json()[0]["action"] == "sent_to_harvey"


def test_auto_send_is_off_by_default_then_sends_new_audited_leads_once(client, maker, fake_vps, tmp_path, monkeypatch):
    from app.services import harvey_auto
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path / "reports")
    a = _business(maker)
    _run_all(maker, a)
    with maker() as s:
        assert harvey_auto.run_once(s) == "off" and not any("harvey import" in c["remote"] for c in fake_vps)
    assert client.put("/harvey/auto", json={"enabled": True}).json()["enabled"] is True
    with maker() as s:
        assert harvey_auto.run_once(s).startswith("sent 1 leads")
        assert s.get(Business, a).details["harvey"]["by"] == "auto"
        assert harvey_auto.run_once(s) == "nothing new"  # never sent twice
    st = client.get("/harvey/auto").json()
    assert st["enabled"] and st["last_result"].startswith("sent 1")
    imports = [c for c in fake_vps if "harvey import" in c["remote"]]
    assert len(imports) == 1 and "--check" not in imports[0]["remote"]


def test_auto_send_takes_new_leads_too_and_resends_once_after_the_audit(client, maker, fake_vps, tmp_path,
                                                                        monkeypatch):
    from app.services import harvey_auto
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path / "reports")
    new = _business(maker)  # not audited yet
    old = _business(maker, title="Other Salon", placeId="P2", phoneUnformatted="+97142220000", website="https://o.ae",
                    location={"lat": 25.3, "lng": 55.4})
    _run_all(maker, old)
    client.put("/harvey/auto", json={"enabled": True})
    with maker() as s:
        assert harvey_auto.run_once(s).startswith("sent 2 leads")
        rows = list(csv.DictReader(io.StringIO(fake_vps[-1]["data"].decode())))
        assert rows[0]["name"] == "Other Salon"  # audited first
        assert s.get(Business, new).details["harvey"]["audited"] is False
        assert harvey_auto.run_once(s) == "nothing new"
    _run_all(maker, new)
    with maker() as s:
        assert harvey_auto.run_once(s).startswith("sent 1 leads")  # again, now with the audit's facts
        assert s.get(Business, new).details["harvey"]["audited"] is True
        assert harvey_auto.run_once(s) == "nothing new"


def test_auto_send_refreshes_leads_sent_before_rows_carried_the_proposal(client, maker, fake_vps, tmp_path,
                                                                         monkeypatch):
    from app.services import harvey_auto
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path / "reports")
    a = _business(maker)
    _run_all(maker, a)
    with maker() as s:
        b = s.get(Business, a)
        b.details = {**(b.details or {}), "harvey": {"sent_at": "2026-10-30T10:00:00+00:00", "by": "auto", "batch": "x"}}
        s.commit()
    client.put("/harvey/auto", json={"enabled": True})
    with maker() as s:
        assert harvey_auto.run_once(s).startswith("sent 1 leads")
        assert s.get(Business, a).details["harvey"]["v"] == harvey_routes.SEND_VERSION


def test_unaudited_leads_cannot_be_sent(client, maker, fake_vps):
    bid = _business(maker)
    assert client.post("/harvey/send", json={"business_ids": [bid], "check_only": True}).status_code == 400


def test_vps_error_becomes_502(client, maker, fake_vps, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path / "reports")
    bid = _business(maker)
    _run_all(maker, bid)

    def down(*a, **k):
        raise bridge.HarveyUnavailable("The VPS did not answer within 25 s")

    monkeypatch.setattr(bridge, "_ssh", down)
    r = client.post("/harvey/send", json={"business_ids": [bid], "check_only": True})
    assert r.status_code == 502 and "did not answer" in r.json()["detail"]


def test_settings_validate_and_save(client, fake_vps, tmp_path, monkeypatch):
    monkeypatch.setattr(apify_tokens, "ENV_FILE", tmp_path / ".env")
    bad = client.put("/settings/harvey", json={"host": "1.2.3.4; rm -rf /", "key": fake_vps and "x"})
    assert bad.status_code == 422  # host may only hold letters, digits, dots and dashes
    missing = client.put("/settings/harvey", json={"host": "203.0.113.5", "key": str(tmp_path / "nope")})
    assert missing.status_code == 400
    key = tmp_path / "id_ok"
    key.write_text("k")
    ok = client.put("/settings/harvey", json={"host": "203.0.113.9", "key": str(key)})
    assert ok.status_code == 200 and ok.json()["ready"] and "HARVEY_SSH_HOST=203.0.113.9" in (tmp_path / ".env").read_text()


def test_real_ssh_is_never_run_without_setup(monkeypatch):
    monkeypatch.delenv("HARVEY_SSH_HOST", raising=False)
    with pytest.raises(bridge.HarveyUnavailable, match="not set up"):
        bridge._ssh(bridge.config(), "true")
