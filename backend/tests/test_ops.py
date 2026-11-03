from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.models import AgentName, AgentTask, AuditJob, Report
from app.services import audits, backup
from app.services import sales as sales_service
from tests.test_main_agent import _business
from tests.test_reporting import _run_all


def test_call_tracking_latest_status_follow_ups_and_results(client, raw_client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    bid = _business(maker)
    _run_all(maker, bid)
    assert client.post(f"/businesses/{bid}/sales", json={"status": "follow_up"}).status_code == 400  # needs a date
    client.post(f"/businesses/{bid}/sales", json={"status": "no_answer"})
    today = date.today().isoformat()
    r = client.post(f"/businesses/{bid}/sales", json={"status": "follow_up", "note": "  call after 5pm ", "follow_up_on": today})
    assert r.status_code == 201 and r.json()["note"] == "call after 5pm"
    hist = client.get(f"/businesses/{bid}/sales").json()
    assert [h["status"] for h in hist] == ["follow_up", "no_answer"]  # newest first, nothing overwritten
    summary = client.get("/sales/summary").json()
    assert summary["by_status"] == {"follow_up": 1} and summary["follow_ups_due"][0]["business_pk"] == bid
    row = client.get("/results").json()["results"][0]
    assert row["sales"]["status"] == "follow_up" and row["stale"] is False
    assert client.get("/results", params={"sales": "follow_up"}).json()["total"] == 1
    assert client.get("/results", params={"sales": "not_called"}).json()["total"] == 0
    assert "follow up" in client.get("/reports/export", params={"format": "csv"}).text
    assert raw_client.post(f"/businesses/{bid}/sales", json={"status": "won"}).status_code == 401


def test_stale_audits_are_flagged_and_reaudited(client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    bid = _business(maker)
    _run_all(maker, bid)
    assert client.get("/audits/stale").json() == {"days": 30, "count": 0}
    assert client.post("/audits/reaudit-stale").json()["queued"] == 0
    with maker() as s:  # pretend the audit finished 40 days ago
        t = s.scalars(select(AgentTask).where(AgentTask.agent_name == AgentName.MAIN)).one()
        t.completed_at = datetime.now(UTC) - timedelta(days=40)
        s.commit()
    assert client.get("/audits/stale").json()["count"] == 1
    assert client.get("/results").json()["results"][0]["stale"] is True
    r = client.post("/audits/reaudit-stale").json()
    assert r["queued"] == 1 and r["run"]
    with maker() as s:
        assert s.query(AuditJob).filter(AuditJob.business_id == bid).count() == 2


def test_old_report_versions_are_removed_newest_kept(client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    client.app.state.audit_worker.stop()  # this test runs the agents itself; the worker must not add reports
    bid = _business(maker)
    _run_all(maker, bid)
    _run_all(maker, bid)  # second audit -> v2 of both reports
    st = client.get("/settings/storage").json()
    assert st["old_report_versions"] == 2 and st["reports_mb"] >= 0 and st["backups_supported"]
    out = client.post("/reports/cleanup").json()
    assert out["reports_removed"] == 2
    with maker() as s:
        reps = s.scalars(select(Report).order_by(Report.id)).all()
        assert [r.status for r in reps][:2] == ["removed", "removed"] and reps[-1].status != "removed"
        assert not Path(reps[0].storage_path).exists() and Path(reps[-1].storage_path).exists()
    assert client.get(f"/reports/{reps[0].id}/html").status_code == 404
    assert client.get("/settings/storage").json()["old_report_versions"] == 0


def test_daily_backup_keeps_newest_copies(tmp_path):
    db = tmp_path / "audit.db"
    import sqlite3
    con = sqlite3.connect(db)
    con.execute("create table t (x)")
    con.execute("insert into t values (1)")
    con.commit()
    con.close()
    folder = backup.folder_for(db)
    folder.mkdir()
    for i in range(9):  # older days already there
        (folder / f"audit-2026-01-0{i + 1}.db").write_bytes(b"old")
    made = backup.backup_now(db, keep=3)
    names = [b["name"] for b in backup.list_backups(db)]
    assert len(names) == 3 and made.name in names and "audit-2026-01-01.db" not in names
    assert sqlite3.connect(made).execute("select x from t").fetchone() == (1,)


def test_backup_endpoint(client):
    r = client.post("/settings/backups")
    assert r.status_code == 201 and r.json()["name"].endswith(".db")
    assert client.get("/settings/storage").json()["backups"][0]["name"] == r.json()["name"]


def test_sales_helpers_without_notes(maker):
    with maker() as s:
        assert sales_service.latest_status(s, []) == {} and sales_service.follow_ups_due(s) == []
        assert sales_service.is_stale(None, 30) is False
