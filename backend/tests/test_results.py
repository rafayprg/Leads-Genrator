from datetime import UTC, datetime

from app.models import AgentName, TaskStatus
from app.services import audits, jobs
from app.services.results import results
from tests.test_main_agent import _business
from tests.test_reporting import _run_all


def _finish(session, job, score, band):
    """Mark every task of a job done, with a Main Agent record like main_work writes."""
    for t in job.tasks:
        t.status, t.completed_at = TaskStatus.COMPLETED, datetime.now(UTC)
        if t.agent_name == AgentName.MAIN:
            t.output_data = {"overall_audit_status": "completed", "failed_parts": [], "reports": [],
                             "opportunity": {"score": score, "band": band}}
    session.commit()


def test_finished_audit_shows_with_score_issues_and_reports(maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    bid = _business(maker)
    _run_all(maker, bid)
    with maker() as s:
        out = results(s)
    assert out["total"] == 1 and out["active"] == 0
    row = out["results"][0]
    assert row["business_pk"] == bid and row["score"] is not None and row["band"]
    assert {r["type"] for r in row["reports"]} == {"owner_summary", "internal_sales"}
    assert row["issue_counts"] and len(row["top_issues"]) <= 3


def test_runs_progress_latest_per_business_and_filters(maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    a = _business(maker)
    b = _business(maker, title="Other Salon", placeId="P2", phoneUnformatted="+97142220000", website="https://o.ae",
                  location={"lat": 25.3, "lng": 55.4})
    _run_all(maker, a)  # an older single audit of A
    with maker() as s:
        run = jobs.create_audit_jobs(s, [a, b], {"run": "r1", "run_label": "2 leads · AE"}, "t")
        _finish(s, run[0], 85, "High priority")  # A done again in the run, B still waiting
        out = results(s)
        assert out["active"] == 1 and out["total"] == 1  # latest audit per business: A's run job
        assert out["results"][0]["score"] == 85 and out["results"][0]["run"] == "r1"
        r1 = next(r for r in out["runs"] if r["key"] == "r1")
        assert (r1["label"], r1["total"], r1["done"], r1["active"], r1["finished_at"]) == ("2 leads · AE", 2, 1, 1, None)
        assert all(r["key"] == "r1" for r in out["runs"])  # a finished one-lead audit is not shown as a run

        assert results(s, run="r1")["run"] == "r1"
        assert results(s, run="nope")["run"] is None  # unknown run -> all audits
        assert results(s, band="Lower priority")["total"] == 0
        assert results(s, q="zzz")["total"] == 0

        _finish(s, run[1], 30, "Lower priority")
        out = results(s, run="r1", sort="score")
        assert [x["score"] for x in out["results"]] == [85, 30] and out["active"] == 0
        assert next(r for r in out["runs"] if r["key"] == "r1")["finished_at"] is not None


def test_results_route_needs_login_and_bulk_names_its_run(client, raw_client, maker):
    assert raw_client.get("/results").status_code == 401
    _business(maker)
    r = client.post("/audits/bulk").json()
    assert r["queued"] == 1 and r["run"].startswith("r")
    body = client.get("/results", params={"run": r["run"]}).json()
    assert body["run"] == r["run"] and body["runs"][0]["label"].startswith("1 lead")


def test_new_and_audited_leads_are_kept_apart(client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    a = _business(maker)
    b = _business(maker, title="Other Salon", placeId="P2", phoneUnformatted="+97142220000", website="https://o.ae",
                  location={"lat": 25.3, "lng": 55.4})
    _run_all(maker, a)  # A has a finished full audit, B never had one
    ids = lambda audit: [x["id"] for x in client.get("/businesses", params={"audit": audit}).json()["items"]]  # noqa: E731
    assert ids("audited") == [a] and ids("new") == [b] and sorted(ids("all")) == sorted([a, b])
    assert client.get("/businesses").json()["total"] == 2  # default stays "all" for old callers

    r = client.post("/audits/bulk").json()  # bulk defaults to "new": the audited business is not done again
    assert r["matched"] == 1 and r["queued"] == 1
    with maker() as s:
        from app.models import AuditJob
        assert s.query(AuditJob).filter(AuditJob.business_id == a).count() == 1
    assert client.post("/audits/bulk", params={"audit": "audited"}).json()["matched"] == 1  # only when asked
    assert client.get("/businesses/export", params={"audit": "audited", "format": "csv"}).text.count("\n") == 2
