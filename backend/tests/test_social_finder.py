import time

import pytest

from app.agents.social import finder
from app.agents.social.profiles import name_match, parse
from app.agents.website.fetch import SafeFetcher
from app.ingest.apify_maps import to_record
from app.ingest.records import save
from app.models import AgentTask, Business, Confidence, SocialProfile, TaskStatus, Verification
from app.services import audits, jobs
from tests.fakes import place
from tests.sitekit import Site


@pytest.mark.parametrize("url,expected", [
    ("https://instagram.com/GlowSalon/", ("instagram", "GlowSalon", "https://www.instagram.com/GlowSalon")),
    ("https://www.facebook.com/glowsalondxb?ref=footer", ("facebook", "glowsalondxb", "https://www.facebook.com/glowsalondxb")),
    ("https://m.facebook.com/profile.php?id=1000123", ("facebook", "1000123", "https://www.facebook.com/profile.php?id=1000123")),
    ("https://www.tiktok.com/@glow.salon", ("tiktok", "glow.salon", "https://www.tiktok.com/@glow.salon")),
    ("https://www.youtube.com/@GlowTV", ("youtube", "@GlowTV", "https://www.youtube.com/@GlowTV")),
    ("https://www.linkedin.com/company/glow-salon/about/", ("linkedin", "glow-salon", "https://www.linkedin.com/company/glow-salon")),
    ("https://twitter.com/glowsalon", ("x", "glowsalon", "https://x.com/glowsalon")),
    ("https://www.snapchat.com/add/glowsalon", ("snapchat", "glowsalon", "https://www.snapchat.com/add/glowsalon")),
])
def test_profile_links_are_recognised_and_cleaned(url, expected):
    p = parse(url)
    assert (p.platform, p.handle, p.url) == expected


@pytest.mark.parametrize("url", [
    "https://www.facebook.com/sharer/sharer.php?u=x", "https://twitter.com/intent/tweet?text=x",
    "https://www.instagram.com/p/Cxyz123/", "https://www.instagram.com/", "https://www.facebook.com/wix",
    "https://www.youtube.com/watch?v=abc", "https://www.tiktok.com/tag/salon", "https://www.linkedin.com/shareArticle?x",
    "https://example.com/instagram", "mailto:a@b.c",
])
def test_share_post_and_builder_links_are_not_profiles(url):
    assert parse(url) is None


def test_name_match():
    assert name_match("glowsalondxb", "Glow Ladies Salon") == 1.0
    assert name_match("brightsmile", "Bright Smile Dental Clinic") == 1.0
    assert name_match("randomhandle", "Bright Smile Dental Clinic") == 0.0


@pytest.fixture()
def site():
    s = Site({
        "/": """<html><body><a href='/contact'>Contact</a>
                <footer><a href='https://instagram.com/glowsalondxb'>IG</a>
                <a href='https://www.facebook.com/sharer/sharer.php?u=x'>share</a>
                <a href='https://www.tiktok.com/@weirdname123'>TikTok</a></footer></body></html>""",
        "/contact": "<a href='https://www.facebook.com/glowsalondxb'>FB</a><a href='https://instagram.com/glowsalondxb/'>IG</a>",
        "/robots.txt": (404, "", {}),
    })
    yield s
    s.close()


def test_finder_uses_own_website_and_rates_confidence(site):
    res = finder.find("Glow Ladies Salon", site.url + "/", ["https://www.youtube.com/@SomeoneElse"],
                      fetcher=SafeFetcher(allow_private=True, delay=0))
    by = {p["platform"]: p for p in res.profiles}
    assert by["instagram"]["confidence"] == "high" and by["instagram"]["official_status"] == "likely_official"
    assert "home and contact pages" in by["instagram"]["evidence"][0]
    assert by["facebook"]["confidence"] == "high"
    assert by["tiktok"]["confidence"] == "medium"          # on the site, but the name does not match
    assert by["youtube"]["confidence"] == "low"            # only on record, name does not match
    assert by["youtube"]["profile_url"] in res.profiles_requiring_review
    assert "linkedin" in res.platforms_not_found and len(res.profiles) == 4


def test_no_website_and_no_links_is_skipped():
    assert finder.find("X", None, []).status == "skipped"


def test_unreadable_website_falls_back_to_known_links():
    res = finder.find("Glow Salon", "http://127.0.0.1:9/", ["https://instagram.com/glowsalon"],
                      fetcher=SafeFetcher(allow_private=True, delay=0))
    assert res.status == "partial" and res.profiles[0]["confidence"] == "medium"


def test_task_saves_clean_profiles_and_marks_junk(maker):
    with maker() as s:
        bid = save(s, [to_record(place(instagram="https://instagram.com/glowsalon/"), "AE", "Dubai", "beauty")]).business_ids[0]
        b = s.get(Business, bid)
        b.social_profiles.append(SocialProfile(platform="facebook", profile_url="https://www.facebook.com/sharer.php?u=1"))
        s.commit()
        job = jobs.create_audit_jobs(s, [bid], {k: k == "social_finder" for k in jobs.AUDIT_AGENTS}, "t")[0]
        tid = job.tasks[0].id

    def offline(name, website_url, known, fetcher=None):
        return finder.find(name, None, known)

    audits.run_social_task(tid, maker, offline)
    with maker() as s:
        t = s.get(AgentTask, tid)
        assert t.status == TaskStatus.COMPLETED and t.output_data["agent"] == "social_media_finder"
        rows = {r.profile_url: r for r in s.query(SocialProfile).filter_by(business_id=bid)}
        ig = rows["https://www.instagram.com/glowsalon"]  # cleaned URL replaced the raw one
        assert ig.confidence == Confidence.MEDIUM and ig.username == "glowsalon" and ig.last_checked_at
        junk = rows["https://www.facebook.com/sharer.php?u=1"]
        assert junk.verification_status == Verification.REQUIRES_REVIEW and "ignored by Agent 3" in junk.evidence[-1]


def test_api_runs_social_finder(client, maker):
    with maker() as s:
        bid = save(s, [to_record(place(), "AE", "Dubai", "beauty")]).business_ids[0]
    assert client.post(f"/businesses/{bid}/social").status_code == 202
    end = time.time() + 10
    while time.time() < end:
        body = client.get(f"/businesses/{bid}/social").json()
        if body["task_status"] == "completed":
            break
        time.sleep(0.1)
    assert body["task_status"] == "completed" and body["profiles"][0]["platform"] == "instagram"
    assert body["summary"]["method"].startswith("own website links")


def test_account_matching_the_website_brand_counts():
    res = finder.find("Elata Beauty", "http://127.0.0.1:9/", ["https://instagram.com/vog_salon"],
                      fetcher=SafeFetcher(allow_private=True, delay=0))
    assert res.profiles[0]["confidence"] == "low"  # 127.0.0.1 has no brand word
    res = finder.find("Elata Beauty", None, ["https://instagram.com/vog_salon"])
    assert res.profiles[0]["confidence"] == "low"
    from app.agents.social.profiles import name_match
    assert name_match("vog_salon", "vog") == 1.0
