import io
import time
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.agents.reporting import builder, pitch, render
from app.agents.social import finder
from app.ingest.apify_maps import to_record
from app.ingest.records import save
from app.models import AgentName, AgentTask, Report, TaskStatus
from app.services import audits, jobs
from tests.conftest import fake_review, fake_website_audit
from tests.fakes import place

PROFILE = {"name": "Glow <b>Salon</b>", "business_id": "BUS-0001", "industry": "beauty", "category": "Beauty salon",
           "city": "Dubai", "area": "Al Barsha", "country": "AE", "phone": "+971501234567", "email": "",
           "website_url": "javascript:alert(1)", "maps_url": "", "rating": 4.6, "review_count": 120}


def issue(title, sev="medium", status="verified", agents=("website_expert",)):
    return {"issue": title, "impact": "why", "severity": sev, "category": "x", "recommendation": "fix",
            "source_url": "", "status": status, "agents": list(agents), "related": []}


DATASET = {
    "issues": [issue("Website does not use HTTPS", "high"), issue("No WhatsApp contact link", "medium", "requires_verification",
                                                                    ("website_expert", "automation_runner")),
               issue("2 social account(s) need a manual check", "low", "requires_review", ("social_media_expert",)),
               issue("Old thing", "high", "stale")],
    "issue_counts": {"critical": 0, "high": 2, "medium": 1, "low": 1},
    "completeness": [{"section": "Website audit", "status": "complete", "reason": "3 pages"},
                     {"section": "Automation evaluation", "status": "not_run", "reason": "Agent has not run yet"}],
    "contradictions": [], "inputs": [{"agent_name": "website_expert", "task_id": 1}], "overall_completeness": "1/2",
}
SUMMARIES = {"automation_runner": {"evaluation_status": "completed", "existing_automation": [
    {"name": "Fresha", "kind": "booking", "competitor": True}], "opportunities": [
    {"business_problem": "No WhatsApp channel on the website", "recommended_solution": "AI WhatsApp assistant",
     "techdeva_capability": {"id": "whatsapp_ai_agent", "name": "WhatsApp AI agent", "status": "existing",
                             "offer": "TechDeva module"}}]}}
SOCIAL = [{"platform": "instagram", "profile_url": "https://www.instagram.com/glow", "confidence": "high"},
          {"platform": "facebook", "profile_url": "https://www.facebook.com/maybe", "confidence": "low"}]


def test_owner_report_keeps_doubts_internal_and_hides_sales_notes():
    p = builder.build(PROFILE, DATASET, SUMMARIES, SOCIAL, "owner")
    s = p["sections"]
    issues = [r["issue"] for r in s["recommendations"]]
    assert issues == ["Website does not use HTTPS", "No WhatsApp contact link"]  # stale + review left out
    assert s["recommendations"][0]["priority"] == "High" and s["recommendations"][1]["confirmed"] is False
    assert "opportunities" not in s and "techdeva" not in s["automation"]["opportunities"][0]
    assert [x["platform"] for x in s["social"]["profiles"]] == ["instagram"]
    assert "Old thing" in s["evidence_limitations"]["left_out"]
    assert "could not be completed (automation evaluation)" in s["executive_summary"]


def test_owner_report_pitches_techdeva_for_the_industry_and_what_was_seen():
    tp = builder.build(PROFILE, DATASET, SUMMARIES, SOCIAL, "owner")["sections"]["techdeva_pitch"]
    assert "appointment book" in tp["headline"]  # beauty outcome, not a generic line
    assert "Fresha" in tp["intro"]  # angle comes from the competitor tool the audit saw
    assert tp["benefits"][0]["because"] == "No WhatsApp channel on the website"
    assert "7 days" in tp["cta"] and "take over" in tp["control"]


def test_owner_pitch_never_offers_modules_that_are_not_live():
    a4 = {"evaluation_status": "completed", "signals": {"whatsapp_links": 0}, "opportunities": [
        {"business_problem": "No online booking", "techdeva_capability": {"id": "bookings", "status": "to_confirm"}}]}
    assert pitch.owner_pitch({**PROFILE, "industry": "clinics"}, a4) is None
    pc = pitch.internal_pitch({**PROFILE, "industry": "clinics"}, a4)
    assert pc["offer"] == [] and pc["do_not_promise"] and pc["angle"] == "new_channel"


def test_busy_business_gets_the_busy_angle():
    a4 = {"evaluation_status": "completed", "signals": {"whatsapp_links": 2}, "opportunities": []}
    assert pitch.internal_pitch({**PROFILE, "review_count": 800}, a4)["angle"] == "busy"
    assert pitch.internal_pitch({**PROFILE, "review_count": 80}, a4)["angle"] == "speed"


def test_internal_report_has_sales_notes():
    s = builder.build(PROFILE, DATASET, SUMMARIES, SOCIAL, "internal")["sections"]
    assert s["opportunities"]["suggested_first_topic"] == "No WhatsApp channel on the website"
    assert s["opportunities"]["competitor_tools"] == ["Fresha"]
    assert len(s["needs_verification"]) == 2 and len(s["social"]["profiles"]) == 2
    with pytest.raises(ValueError):
        builder.build(PROFILE, DATASET, SUMMARIES, SOCIAL, "everyone")


def test_html_escapes_scraped_text_and_blocks_bad_links(tmp_path):
    (tmp_path / "desktop.png").write_bytes(b"\x89PNG fake")
    pkg = builder.build(PROFILE, DATASET, SUMMARIES, SOCIAL, "internal")
    pkg["sections"]["website"]["screenshots"] = ["desktop"]
    out = render.html(pkg, tmp_path)
    assert "Glow &lt;b&gt;Salon&lt;/b&gt;" in out and "<b>Salon</b>" not in out
    assert 'href="javascript:' not in out and "data:image/png;base64," in out
    assert "Internal sales brief" in out and "Suggested first topic" in out


def _business(maker):
    with maker() as s:
        return save(s, [to_record(place(), "AE", "Dubai", "beauty")]).business_ids[0]


def _run_all(maker, bid, make_pdf=False):
    with maker() as s:
        job = jobs.create_audit_jobs(s, [bid], {}, "t")[0]
        ids = {t.agent_name: t.id for t in job.tasks}
    audits.run_website_task(ids[AgentName.WEBSITE_EXPERT], maker, fake_website_audit, use_browser=False)
    audits.run_social_task(ids[AgentName.SOCIAL_MEDIA_FINDER], maker,
                           lambda name, website, known, fetcher=None: finder.find(name, None, known))
    audits.run_task(ids[AgentName.SOCIAL_MEDIA_EXPERT], maker, audits.social_expert_work())
    audits.run_task(ids[AgentName.AUTOMATION_RUNNER], maker, audits.automation_work(fake_review))
    audits.run_task(ids[AgentName.DATA_ORGANIZER], maker, audits.organizer_work())
    with maker() as s:
        assert audits.next_task(s, [AgentName.REPORTING]).id == ids[AgentName.REPORTING]
    audits.run_task(ids[AgentName.REPORTING], maker, audits.reporting_work(make_pdf))
    audits.run_task(ids[AgentName.MAIN], maker, audits.main_work())  # final step frees the business for a new audit
    return ids


def test_reporting_task_writes_two_reports(maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    bid = _business(maker)
    ids = _run_all(maker, bid)
    with maker() as s:
        t = s.get(AgentTask, ids[AgentName.REPORTING])
        assert t.status == TaskStatus.COMPLETED and len(t.output_data["reports"]) == 2
        reps = s.query(Report).filter_by(business_id=bid).all()
        assert {r.report_type for r in reps} == {"owner_summary", "internal_sales"}
        assert all(Path(r.storage_path).is_file() and r.version == 1 for r in reps)
    _run_all(maker, bid)  # second full audit -> version 2
    with maker() as s:
        assert max(r.version for r in s.query(Report).filter_by(business_id=bid)) == 2


def test_reporting_without_organizer_is_skipped(maker):
    bid = _business(maker)
    with maker() as s:
        job = jobs.create_audit_jobs(s, [bid], {k: k == "reporting" for k in jobs.AUDIT_AGENTS}, "t")[0]
        tid = job.tasks[0].id
    audits.run_task(tid, maker, audits.reporting_work(False))
    with maker() as s:
        assert s.get(AgentTask, tid).status == TaskStatus.SKIPPED


def _chromium_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).exists()
    except Exception:
        return False


@pytest.mark.skipif(not _chromium_ready(), reason="Chromium for Playwright is not installed")
def test_pdf_is_made(tmp_path):
    out = tmp_path / "r.pdf"
    html = render.html(builder.build(PROFILE, DATASET, SUMMARIES, SOCIAL, "owner"))
    assert render.pdf(html, out) == "" and out.read_bytes()[:4] == b"%PDF"


def test_api_reports_html_pdf_and_sales_sheet(client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    bid = _business(maker)
    _run_all(maker, bid)
    reps = client.get("/reports", params={"business_id": bid}).json()
    assert len(reps) == 2 and reps[0]["has_pdf"] is False
    r = client.get(f"/reports/{reps[0]['id']}/html")
    assert r.status_code == 200 and "default-src 'none'" in r.headers["content-security-policy"]
    assert client.get(f"/reports/{reps[0]['id']}/pdf").status_code == 404  # PDF switched off in this test
    assert client.get("/reports/9999/html").status_code == 404
    ws = load_workbook(io.BytesIO(client.get("/reports/export").content)).active
    assert ws.cell(1, 1).value == "Business ID" and ws.max_row == 2
    col = [c.value for c in ws[1]].index("Report (HTML)") + 1
    assert "localhost:5190/api/reports/" in ws.cell(2, col).value


def test_api_reporting_alone_runs_organizer_first(client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    bid = _business(maker)
    client.post(f"/businesses/{bid}/website-audit")
    end = time.time() + 15
    while time.time() < end and client.get(f"/businesses/{bid}/website-audit").json()["task_status"] != "completed":
        time.sleep(0.1)
    client.post(f"/businesses/{bid}/agents/reporting")
    while time.time() < end:
        body = client.get(f"/businesses/{bid}/agents/reporting").json()
        if body["task_status"] == "completed":
            break
        time.sleep(0.1)
    assert body["task_status"] == "completed" and len(body["summary"]["reports"]) == 2


def test_proposal_uses_only_seen_findings_in_plain_words_best_first():
    ds = {"issues": [issue("Main content takes 10.1s to appear on desktop", "high"),
                     issue("No WhatsApp contact link", "medium", "requires_verification"),  # not seen: never used
                     issue("Images must have alternative text"),                           # too technical: skipped
                     issue("Booking page tells Google not to list it (noindex)", "high")]}
    p = pitch.proposal(PROFILE, ds, SUMMARIES["automation_runner"])
    assert p["finding_1"] == "your booking page is set to stay hidden from Google, so people searching for you won't find it"
    assert p["finding_2"] == "your homepage takes about 10.1 seconds to show on a computer"
    assert "Fresha" in p["techdeva_line"]  # the same angle as the report


def test_proposal_needs_two_findings_or_none():
    p = pitch.proposal(PROFILE, {"issues": [issue("Website does not use HTTPS", "high")]}, {})
    assert p["finding_1"] == p["finding_2"] == "" and p["techdeva_line"]


def test_proposal_takes_one_finding_per_topic():
    ds = {"issues": [issue("Main content takes 9.2s to appear on desktop", "high"),
                     issue("Homepage HTML took 3.3s to arrive", "high"),  # speed again: skipped
                     issue("No tap-to-call phone link")]}
    p = pitch.proposal(PROFILE, ds, {})
    assert p["finding_1"].startswith("your homepage takes about 9.2") and "tapped to call" in p["finding_2"]
