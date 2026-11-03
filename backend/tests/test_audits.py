import time

import pytest

from app.ingest.apify_maps import to_record
from app.ingest.records import save
from app.models import AgentName, AgentTask, AuditFinding, AuditJob, DataSource, JobStatus, TaskStatus, Verification
from app.services import audits, jobs
from tests.conftest import fake_website_audit
from tests.fakes import place


def _business(maker, **kw):
    with maker() as s:
        return save(s, [to_record(place(**kw), "AE", "Dubai", "beauty")]).business_ids[0]


def _queue(maker, bid, website_only=True):
    with maker() as s:
        opts = {k: (k == "website") for k in jobs.AUDIT_AGENTS} if website_only else {}
        job = jobs.create_audit_jobs(s, [bid], opts, "test")[0]
        return job.id, next(t.id for t in job.tasks if t.agent_name == AgentName.WEBSITE_EXPERT)


def test_website_task_saves_findings_and_verifies_the_website(maker):
    bid = _business(maker)
    job_id, task_id = _queue(maker, bid)
    audits.run_website_task(task_id, maker, fake_website_audit, use_browser=False)
    with maker() as s:
        task, job = s.get(AgentTask, task_id), s.get(AuditJob, job_id)
        assert task.status == TaskStatus.COMPLETED and task.attempt_count == 1
        assert task.output_data["issues_found"] == 1 and job.status == JobStatus.COMPLETED
        assert s.query(AuditFinding).one().title == "No WhatsApp contact link"
        ds = s.query(DataSource).filter_by(business_id=bid, field="website_url").one()
        assert ds.verification_status == Verification.VERIFIED


def test_other_agents_keep_waiting_so_job_is_partial(maker):
    bid = _business(maker)
    job_id, task_id = _queue(maker, bid, website_only=False)
    audits.run_website_task(task_id, maker, fake_website_audit, use_browser=False)
    with maker() as s:
        assert s.get(AuditJob, job_id).status == JobStatus.PARTIAL
        pending = [t.agent_name for t in s.get(AuditJob, job_id).tasks if t.status == TaskStatus.PENDING]
        assert AgentName.SOCIAL_MEDIA_FINDER in pending


def test_crash_is_retried_then_failed(maker):
    bid = _business(maker)
    _, task_id = _queue(maker, bid)

    def boom(*a, **k):
        raise RuntimeError("browser exploded")

    for _ in range(3):
        audits.run_website_task(task_id, maker, boom, use_browser=False)
    with maker() as s:
        t = s.get(AgentTask, task_id)
        assert t.status == TaskStatus.FAILED and t.attempt_count == 3 and "browser exploded" in t.error_message


def test_no_website_is_skipped(maker):
    bid = _business(maker, website="")
    job_id, task_id = _queue(maker, bid)
    audits.run_website_task(task_id, maker, fake_website_audit, use_browser=False)
    with maker() as s:
        assert s.get(AgentTask, task_id).status == TaskStatus.SKIPPED
        assert s.get(AuditJob, job_id).status == JobStatus.COMPLETED


def test_restart_puts_running_task_back_in_queue(maker):
    bid = _business(maker)
    _, task_id = _queue(maker, bid)
    with maker() as s:
        t = s.get(AgentTask, task_id)
        t.status, t.attempt_count = TaskStatus.RUNNING, 1
        s.commit()
        assert audits.recover_running(s) == 1
        assert s.get(AgentTask, task_id).status == TaskStatus.PENDING


def test_api_start_and_read_website_audit(client, maker):
    bid = _business(maker)
    r = client.post(f"/businesses/{bid}/website-audit")
    assert r.status_code == 202
    end = time.time() + 10
    while time.time() < end:
        body = client.get(f"/businesses/{bid}/website-audit").json()
        if body["task_status"] == "completed":
            break
        time.sleep(0.1)
    assert body["task_status"] == "completed" and body["findings"][0]["severity"] == "medium"
    assert body["summary"]["agent"] == "website_expert"
    # a second click while nothing is waiting starts a fresh audit
    assert client.post(f"/businesses/{bid}/website-audit").status_code == 202


@pytest.mark.parametrize("path", ["/artifacts/BUS-0001/1/..%2F..%2F.env", "/artifacts/BUS-0001/1/secret.png",
                                  "/artifacts/..%2Fdata/1/desktop.png", "/artifacts/BUS-0001/1/desktop.png"])
def test_artifacts_only_serve_known_screenshots(client, path):
    assert client.get(path).status_code == 404
