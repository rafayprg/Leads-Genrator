import time
from datetime import UTC, datetime, timedelta

from app.agents.organizer.organize import AgentOutput, consolidate, normalise, organize
from app.agents.social import finder
from app.ingest.apify_maps import to_record
from app.ingest.records import save
from app.models import AgentName, AgentTask, TaskStatus
from app.services import audits, jobs
from tests.conftest import fake_review, fake_website_audit
from tests.fakes import place

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)
T = NOW - timedelta(hours=1)


def f(fid, title, sev="medium", ver="verified", evidence=None, when=T, category="conversion"):
    return {"id": fid, "title": title, "severity": sev, "verification_status": ver, "category": category,
            "evidence": {"url": "https://x.ae"} if evidence is None else evidence, "source_url": None,
            "confidence": "high", "recommendation": "fix", "description": "why", "observed_at": when}


def out(agent, findings=(), **summary):
    return AgentOutput(agent, 1, "completed", T, summary, list(findings))


def test_normalise_fixes_case_and_unknown_severity():
    n = normalise("website_expert", {**f(1, "X", sev="MEDIUM"), "confidence": "HIGH"})
    assert n["severity"] == "medium" and n["confidence"] == "high" and n["finding_id"] == "F-1"
    bad = normalise("website_expert", f(2, "Y", sev="urgent"))
    assert bad["severity"] == "low" and "unknown severity" in bad["notes"][0]


def test_same_issue_from_two_agents_is_merged_and_sources_kept():
    items = consolidate([normalise("website_expert", f(1, "No WhatsApp contact link", ver="verified")),
                         normalise("automation_runner", f(2, "No WhatsApp channel on the website", ver="inferred",
                                                          category="automation")),
                         normalise("website_expert", f(3, "Homepage has no canonical link", sev="low"))], NOW)
    wa = next(i for i in items if i["topic"] == "whatsapp")
    assert wa["source_finding_ids"] == ["F-1", "F-2"] and wa["agents"] == ["automation_runner", "website_expert"]
    assert wa["status"] == "verified" and wa["related"][0]["agent_name"] == "automation_runner"
    assert len(items) == 2  # canonical stays on its own


def test_evidence_check_statuses():
    items = consolidate([normalise("automation_runner", f(1, "No visitor tracking seen", ver="inferred")),
                         normalise("website_expert", f(2, "Broken thing", evidence={})),
                         normalise("website_expert", f(3, "Old thing", when=NOW - timedelta(days=45))),
                         normalise("social_media_expert", f(4, "2 social account(s) need a manual check",
                                                            ver="requires_review"))], NOW)
    by = {i["issue"]: i["status"] for i in items}
    assert by == {"No visitor tracking seen": "requires_verification", "Broken thing": "missing_evidence",
                  "Old thing": "stale", "2 social account(s) need a manual check": "requires_review"}


def test_contradictions_are_reported_not_hidden():
    data = organize({"business_id": "BUS-0001", "phone": "+9714", "website_url": "https://x.ae", "city": "Dubai",
                     "category": "Salon"}, [
        out("website_expert", [f(1, "No WhatsApp contact link"), f(2, "No clear way to book an appointment online",
                                                                    ver="inferred")], status="completed", pages={"home": "x"}),
        out("automation_runner", [], evaluation_status="failed", signals={"whatsapp_links": 2, "pages_read": ["contact"]},
            existing_automation=[{"kind": "booking", "name": "Fresha"}], limitations=["Website could not be read"]),
    ], now=NOW)
    topics = {c["topic"] for c in data["contradictions"]}
    assert topics == {"availability", "whatsapp", "online_booking"}
    assert "intermittent" in next(c for c in data["contradictions"] if c["topic"] == "availability")["statement"]


def test_completeness_and_next_steps():
    data = organize({"business_id": "BUS-0001", "phone": "", "website_url": "https://x.ae", "city": "Dubai",
                     "category": "Salon"}, [
        out("website_expert", [f(1, "Website does not use HTTPS", sev="high", category="https")],
            status="completed", pages={"home": "a", "contact": "b"}),
        out("social_media_expert", [], audit_status="completed", overall_limitations=["no posts"]),
    ], now=NOW)
    table = {r["section"]: r for r in data["completeness"]}
    assert table["Business profile"]["status"] == "partial" and "phone" in table["Business profile"]["reason"]
    assert table["Website audit"]["status"] == "complete" and "2 page(s)" in table["Website audit"]["reason"]
    assert table["Social media audit"]["status"] == "partial"           # presence only, never "complete"
    assert table["Automation evaluation"]["status"] == "not_run"
    assert data["next_steps"][0].startswith("Re-run: Social media discovery")
    assert "Raise: Website does not use HTTPS" in data["next_steps"]
    assert data["issue_counts"]["high"] == 1


def test_organizer_task_waits_for_specialists_then_builds_dataset(maker):
    with maker() as s:
        bid = save(s, [to_record(place(), "AE", "Dubai", "beauty")]).business_ids[0]
        job = jobs.create_audit_jobs(s, [bid], {"reporting": False}, "t")[0]
        ids = {t.agent_name: t.id for t in job.tasks}
        assert audits.next_task(s, [AgentName.DATA_ORGANIZER]) is None  # specialists not done
    audits.run_website_task(ids[AgentName.WEBSITE_EXPERT], maker, fake_website_audit, use_browser=False)
    audits.run_social_task(ids[AgentName.SOCIAL_MEDIA_FINDER], maker,
                           lambda name, website, known, fetcher=None: finder.find(name, None, known))
    audits.run_task(ids[AgentName.SOCIAL_MEDIA_EXPERT], maker, audits.social_expert_work())
    audits.run_task(ids[AgentName.AUTOMATION_RUNNER], maker, audits.automation_work(fake_review))
    with maker() as s:
        assert audits.next_task(s, [AgentName.DATA_ORGANIZER]).id == ids[AgentName.DATA_ORGANIZER]
    audits.run_task(ids[AgentName.DATA_ORGANIZER], maker, audits.organizer_work())
    with maker() as s:
        t = s.get(AgentTask, ids[AgentName.DATA_ORGANIZER])
        d = t.output_data
        assert t.status == TaskStatus.COMPLETED and d["agent"] == "data_organizer"
        assert {i["agent_name"] for i in d["inputs"]} == {"website_expert", "social_media_finder",
                                                          "social_media_expert", "automation_runner"}
        wa = next(i for i in d["issues"] if i["topic"] == "whatsapp")
        assert len(wa["source_finding_ids"]) == 2  # Agent 1 + Agent 4 said the same thing


def test_api_runs_organizer(client, maker):
    with maker() as s:
        bid = save(s, [to_record(place(), "AE", "Dubai", "beauty")]).business_ids[0]
    client.post(f"/businesses/{bid}/website-audit")
    end = time.time() + 10
    while time.time() < end and client.get(f"/businesses/{bid}/website-audit").json()["task_status"] != "completed":
        time.sleep(0.1)
    assert client.post(f"/businesses/{bid}/agents/organizer").status_code == 202
    while time.time() < end:
        body = client.get(f"/businesses/{bid}/agents/organizer").json()
        if body["task_status"] == "completed":
            break
        time.sleep(0.1)
    assert body["summary"]["issue_counts"]["medium"] == 1
    assert body["summary"]["completeness"][1]["section"] == "Website audit"
