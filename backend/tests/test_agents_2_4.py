import time

import pytest

from app.agents.automation import capabilities, runner
from app.agents.social import expert, finder
from app.agents.website.fetch import SafeFetcher
from app.ingest.apify_maps import to_record
from app.ingest.records import save
from app.models import AgentName, AgentTask, TaskStatus
from app.services import audits, jobs
from tests.fakes import place
from tests.sitekit import Site


# ------------------------------------------------------------------ Agent 2 (presence only)
def prof(platform, conf, on_site=True):
    ev = ["Linked from the business's own website (home page)"] if on_site else ["Already on record"]
    return {"platform": platform, "profile_url": f"https://x/{platform}", "confidence": conf, "evidence": ev}


def test_no_trusted_accounts_is_a_medium_finding():
    res = expert.assess("beauty", [prof("instagram", "low", False)], finder_ran=True)
    titles = [f.title for f in res.findings]
    assert "No official social media account found" in titles and "1 social account(s) need a manual check" in titles
    assert res.summary()["mode"] == "presence_only" and "scraping declined" in res.summary()["overall_limitations"][0]


def test_missing_instagram_for_a_salon():
    res = expert.assess("beauty", [prof("facebook", "high")], finder_ran=True)
    assert [f.title for f in res.findings] == ["No Instagram account found"]


def test_accounts_not_linked_from_website():
    res = expert.assess("real_estate", [prof("facebook", "medium", on_site=False)], finder_ran=True)
    assert [f.title for f in res.findings] == ["Website does not link to the social accounts"]


def test_unchecked_accounts_are_not_judged():
    res = expert.assess("beauty", [prof("instagram", "low", False)], finder_ran=False)
    assert res.status == "skipped" and res.findings == []


# ------------------------------------------------------------------ Agent 4 (audit only)
FRESHA_SITE = """<html><head><script src="https://www.googletagmanager.com/gtm.js"></script></head><body>
<a href="https://www.fresha.com/a/glow-salon">Book now</a> <a href="https://wa.me/971501234567">WhatsApp</a>
<script src="https://embed.tawk.to/abc/default"></script></body></html>"""
MANUAL_SITE = """<html><body><h1>Clinic</h1><a href="/contact">Contact</a><p>Call us to book.</p></body></html>"""


def test_detects_tools_and_competitors():
    tools, signals = runner.detect({"home": FRESHA_SITE})
    names = {t["name"]: t for t in tools}
    assert {"Fresha", "tawk.to", "Google Tag Manager"} <= set(names)
    assert names["Fresha"]["competitor"] and names["Fresha"]["kind"] == "booking"
    assert signals["whatsapp_links"] == 1 and signals["booking_wording"]


def test_manual_site_gets_mapped_opportunities():
    tools, signals = runner.detect({"home": MANUAL_SITE, "contact": "<form action='/send'><input></form>"})
    opps = {o["workflow"]: o for o, _ in runner.opportunities("clinics", tools, signals)}
    assert set(opps) == {"appointment_request_processing", "whatsapp_channel", "lead_capture_to_crm", "lead_source_tracking"}
    assert opps["whatsapp_channel"]["techdeva_capability"]["offer"] == "TechDeva module"
    assert opps["appointment_request_processing"]["techdeva_capability"]["offer"].startswith("proposed")
    assert opps["lead_source_tracking"]["techdeva_capability"]["id"] is None  # not sold as a TechDeva module
    assert all(o["execution_status"] == "not_tested" and o["business_impact"] == "not_measured" for o in opps.values())


def test_only_listed_capabilities_can_be_recommended():
    for o, _ in runner.opportunities("beauty", [], {"forms": 1, "tel_links": 0, "whatsapp_links": 1, "booking_wording": False}):
        cap = o["techdeva_capability"]["id"]
        assert cap is None or cap in capabilities.CAPABILITIES


@pytest.fixture()
def site():
    s = Site({"/": FRESHA_SITE, "/robots.txt": (404, "", {})})
    yield s
    s.close()


def test_review_reads_the_site_and_never_runs_anything(site):
    res = runner.review(site.url + "/", "beauty", fetcher=SafeFetcher(allow_private=True, delay=0))
    s = res.summary()
    assert s["execution_mode"] == "audit_only" and "no workflow was run" in s["limitations"][0]
    assert s["signals"]["competitor_tools"] == ["Fresha", "tawk.to"]
    assert "appointment_request_processing" not in {o["workflow"] for o in res.opportunities}  # Fresha = booking exists


def test_review_without_website_is_skipped():
    assert runner.review(None).status == "skipped"


# ------------------------------------------------------------------ worker order: Agent 2 waits for Agent 3
def test_social_expert_waits_for_social_finder(maker):
    with maker() as s:
        bid = save(s, [to_record(place(), "AE", "Dubai", "beauty")]).business_ids[0]
        job = jobs.create_audit_jobs(s, [bid], {"website": False, "automation": False, "organizer": False,
                                                "reporting": False}, "t")[0]
        ids = {t.agent_name: t.id for t in job.tasks}
        assert audits.next_task(s, [AgentName.SOCIAL_MEDIA_EXPERT]) is None  # finder not done yet
    audits.run_social_task(ids[AgentName.SOCIAL_MEDIA_FINDER], maker,
                           lambda name, website, known, fetcher=None: finder.find(name, None, known))
    with maker() as s:
        t = audits.next_task(s, [AgentName.SOCIAL_MEDIA_EXPERT])
        assert t is not None and t.id == ids[AgentName.SOCIAL_MEDIA_EXPERT]
    audits.run_task(ids[AgentName.SOCIAL_MEDIA_EXPERT], maker, audits.social_expert_work())
    with maker() as s:
        t = s.get(AgentTask, ids[AgentName.SOCIAL_MEDIA_EXPERT])
        assert t.status == TaskStatus.COMPLETED and t.output_data["mode"] == "presence_only"


def test_api_runs_agent_4(client, maker):
    with maker() as s:
        bid = save(s, [to_record(place(), "AE", "Dubai", "clinics")]).business_ids[0]
    assert client.post(f"/businesses/{bid}/agents/automation").status_code == 202
    assert client.post(f"/businesses/{bid}/agents/website").status_code == 422  # only social / automation here
    end = time.time() + 10
    while time.time() < end:
        body = client.get(f"/businesses/{bid}/agents/automation").json()
        if body["task_status"] == "completed":
            break
        time.sleep(0.1)
    assert body["summary"]["execution_mode"] == "audit_only"
    assert {f["category"] for f in body["findings"]} == {"automation"}


def test_running_agent_2_alone_also_queues_agent_3(client, maker):
    with maker() as s:
        bid = save(s, [to_record(place(), "AE", "Dubai", "beauty")]).business_ids[0]
    client.post(f"/businesses/{bid}/agents/social")
    end = time.time() + 10
    while time.time() < end:
        body = client.get(f"/businesses/{bid}/agents/social").json()
        if body["task_status"] == "completed":
            break
        time.sleep(0.1)
    assert body["task_status"] == "completed"
    assert client.get(f"/businesses/{bid}/social").json()["task_status"] == "completed"  # Agent 3 ran first
