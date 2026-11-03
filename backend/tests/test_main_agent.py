import threading
import time

from app.agents.main_agent import score as opp
from app.ingest.apify_maps import to_record
from app.ingest.records import save
from app.models import AgentName, AgentTask, AuditJob, Business, JobStatus, TaskStatus
from app.services import audits, jobs
from tests.fakes import place


def test_score_weights_and_bands():
    dataset = {"issues": [{"issue": "Website does not use HTTPS", "severity": "high", "status": "verified",
                           "agents": ["website_expert"]},
                          {"issue": "No official social media account found", "severity": "medium",
                           "status": "requires_verification", "agents": ["social_media_expert"]}]}
    summaries = {"website_expert": {"status": "completed"}, "social_media_expert": {"audit_status": "completed"},
                 "automation_runner": {"evaluation_status": "completed", "existing_automation": [], "opportunities": [
                     {"techdeva_capability": {"status": "existing"}}, {"techdeva_capability": {"status": "existing"}},
                     {"techdeva_capability": {"status": "to_confirm"}}]}}
    profile = {"phone": "+971501234567", "phone_type": "mobile", "whatsapp": "+971501234567",
               "website_url": "https://x.ae", "email": "", "city": "Dubai", "category": "Salon"}
    r = opp.score(profile, dataset, summaries)
    b = {k: v["points"] for k, v in r["breakdown"].items()}
    assert b == {"website": 8, "social": 20, "automation": 30, "completeness": 8, "contact": 10}
    assert r["score"] == 76 and r["band"] == "Medium-high" and "not a probability" in r["label"]


def test_competitor_lowers_score_and_missing_parts_give_zero():
    summaries = {"automation_runner": {"evaluation_status": "completed", "opportunities": [
        {"techdeva_capability": {"status": "existing"}}], "existing_automation": [{"name": "Fresha", "competitor": True}]}}
    r = opp.score({}, {}, summaries)
    assert r["breakdown"]["automation"]["points"] == 2 and "Fresha" in r["breakdown"]["automation"]["why"]
    assert r["breakdown"]["website"]["points"] == 0 and r["band"] == "Lower priority"


def _business(maker, **kw):
    with maker() as s:
        return save(s, [to_record(place(**kw), "AE", "Dubai", "beauty")]).business_ids[0]


def test_two_workers_cannot_run_the_same_task(maker):
    bid = _business(maker)
    with maker() as s:
        tid = jobs.create_audit_jobs(s, [bid], {k: k == "main" for k in jobs.AUDIT_AGENTS}, "t")[0].tasks[0].id
    calls = []

    def slow(session, task, b):
        calls.append(task.id)
        time.sleep(0.3)
        return audits.Outcome({"ok": True})

    threads = [threading.Thread(target=audits.run_task, args=(tid, maker, slow)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with maker() as s:
        assert calls == [tid] and s.get(AgentTask, tid).attempt_count == 1


def test_failed_task_waits_before_retrying(maker):
    bid = _business(maker)
    with maker() as s:
        tid = jobs.create_audit_jobs(s, [bid], {k: k == "automation" for k in jobs.AUDIT_AGENTS}, "t")[0].tasks[0].id

    def boom(session, task, b):
        raise RuntimeError("network down")

    audits.run_task(tid, maker, boom)
    with maker() as s:
        t = s.get(AgentTask, tid)
        assert t.status == TaskStatus.PENDING and "retry_after" in t.input_data
        assert audits.next_task(s, [AgentName.AUTOMATION_RUNNER]) is None  # still waiting


def _wait(client, path, key, want, seconds=20):
    end = time.time() + seconds
    while time.time() < end:
        body = client.get(path).json()
        if body.get(key) in want:
            return body
        time.sleep(0.1)
    raise AssertionError(f"{path} never reached {want}: {body}")


def test_one_click_full_audit_ends_with_main_agent_and_score(client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    bid = _business(maker)
    job = client.post(f"/businesses/{bid}/full-audit").json()
    assert {t["agent_name"] for t in job["tasks"]} >= {"website_expert", "data_organizer", "reporting", "main"}
    assert client.post(f"/businesses/{bid}/full-audit").json()["id"] == job["id"]  # same job, not a second one
    main = _wait(client, f"/businesses/{bid}/agents/main", "task_status", {"completed"})["summary"]
    assert client.get(f"/audits/{job['id']}").json()["status"] == "completed"
    assert main["overall_audit_status"] == "completed" and main["statuses"]["reporting"] == "completed"
    assert len(main["reports"]) == 2 and 0 <= main["opportunity"]["score"] <= 100
    with maker() as s:
        assert s.get(Business, bid).details["opportunity"]["band"]


def test_monitor_retry_bulk_and_sort(client, maker):
    a = _business(maker)
    b = _business(maker, title="Other Salon", placeId="P2", phoneUnformatted="+97142220000", website="https://o.ae",
                  location={"lat": 25.3, "lng": 55.4})
    with maker() as s:
        s.get(Business, a).details = {**s.get(Business, a).details, "opportunity": {"score": 40}}
        s.get(Business, b).details = {**s.get(Business, b).details, "opportunity": {"score": 90}}
        tid = jobs.create_audit_jobs(s, [a], {k: k == "automation" for k in jobs.AUDIT_AGENTS}, "t")[0].tasks[0].id
        t = s.get(AgentTask, tid)
        t.status, t.error_message, t.attempt_count = TaskStatus.FAILED, "boom", 3
        s.commit()
    assert [x["id"] for x in client.get("/businesses", params={"sort": "score"}).json()["items"]] == [b, a]
    m = client.get("/monitor").json()
    assert m["failed"][0]["error"] == "boom" and len(m["workers"]["threads"]) == 3
    assert client.post(f"/tasks/{tid}/retry").json()["status"] == "pending"
    assert client.post(f"/tasks/{tid}/retry").status_code == 409  # no longer failed
    r = client.post("/audits/bulk", params={"q": "salon"}).json()
    assert r["matched"] == 2
    with maker() as s:
        assert s.query(AuditJob).filter(AuditJob.status != JobStatus.FAILED).count() >= 2
