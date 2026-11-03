import shutil
from pathlib import Path

import pytest

from app.agents.website import agent, checks_page
from app.agents.website.fetch import SafeFetcher
from app.models import Severity
from tests.sitekit import Site

WEAK_HOME = """<html><head><title>Hi</title></head><body>
<h1>Welcome</h1><h1>Second</h1>
<img src=a.jpg><img src=b.jpg><img src=c.jpg>
<a href="/contact">Contact us</a> <a href="/services">Our services</a> <a href="/old-offer">Offers</a>
<p>Call 04 123 4567</p></body></html>"""

GOOD_HOME = """<html lang="en"><head><title>Bright Smile Dental Clinic in Jumeirah, Dubai</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Family dental clinic in Jumeirah. Book online or WhatsApp us.">
<link rel="canonical" href="/">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Dentist","name":"Bright Smile"}</script>
</head><body><h1>Dental care in Jumeirah</h1>
<a href="tel:+97143334444">Call</a> <a href="https://wa.me/97143334444">WhatsApp</a>
<a href="/booking">Book appointment</a> <a href="/contact">Contact</a>
<section>What our patients say: 5 stars</section></body></html>"""


def titles(findings):
    return [f.title for f in findings]


@pytest.fixture()
def weak_site():
    s = Site({
        "/": WEAK_HOME,
        "/contact": "<html><head><title>Hi</title><meta name='robots' content='noindex'></head><body>"
                    "<form><input name=n></form></body></html>",
        "/services": (500, "error", {}),
        "/old-offer": (404, "gone", {}),
        "/robots.txt": (404, "", {}),
    })
    yield s
    s.close()


@pytest.fixture()
def good_site():
    s = Site({"/": GOOD_HOME, "/booking": "<html><head><title>Book</title></head><body><form></form></body></html>",
              "/contact": "<html><head><title>Contact Bright Smile</title></head><body>Al Wasl Rd</body></html>",
              "/robots.txt": (200, "Sitemap: /sitemap.xml\n", {"Content-Type": "text/plain"}),
              "/sitemap.xml": (200, "<urlset><url><loc>/</loc></url></urlset>", {"Content-Type": "application/xml"})})
    yield s
    s.close()


def test_weak_site_gets_the_expected_findings(weak_site):
    res = agent.audit(weak_site.url + "/", "clinics", fetcher=SafeFetcher(allow_private=True, delay=0),
                      use_browser=False)
    t = titles(res.findings)
    assert res.status == "completed" and set(res.pages) == {"home", "contact"}
    assert any(x.startswith("services page could not be read") for x in res.limitations)
    assert "Website does not use HTTPS" in t
    assert "Homepage is not set up for mobile screens (no viewport tag)" in t
    assert "Contact page tells Google not to list it (noindex)" in t
    assert any(x.startswith("Broken link: services page") for x in t)
    assert any("/old-offer" in x for x in t)
    assert "No clear way to book an appointment online" in t
    assert "No tap-to-call phone link" in t and "No WhatsApp contact link" in t
    assert "Several pages share the same title" in t
    sev = [f.severity for f in res.findings]
    assert sev == sorted(sev, key=lambda s: agent.SEVERITY_ORDER[s])  # most serious first
    booking = next(f for f in res.findings if f.title.startswith("No clear way to book"))
    assert str(booking.verification) == "inferred"  # not seen directly, so not claimed as fact


def test_good_site_has_no_conversion_or_mobile_basics_problems(good_site):
    res = agent.audit(good_site.url + "/", "clinics", fetcher=SafeFetcher(allow_private=True, delay=0),
                      use_browser=False)
    t = titles(res.findings)
    for absent in ("No tap-to-call phone link", "No WhatsApp contact link", "No clear way to book an appointment online",
                   "Homepage has no main heading (H1)", "No sitemap found", "Homepage is not set up for mobile screens (no viewport tag)",
                   "No reviews or testimonials shown", "No local business details for search engines (structured data)"):
        assert absent not in t, absent
    assert all(f.severity in (Severity.HIGH, Severity.LOW, Severity.MEDIUM) for f in res.findings)


def test_unreachable_site_fails_cleanly():
    res = agent.audit("http://127.0.0.1:9/", "beauty", fetcher=SafeFetcher(allow_private=True, delay=0),
                      use_browser=False)
    assert res.status == "failed" and res.findings[0].category == "availability"
    assert res.findings[0].severity == Severity.CRITICAL


def test_no_website_is_skipped_not_failed():
    res = agent.audit(None)
    assert res.status == "skipped" and res.findings == []


def test_private_address_is_never_fetched_in_real_mode():
    res = agent.audit("http://192.168.1.1/", "beauty", use_browser=False)
    assert res.status == "failed" and "private or unsafe" in res.findings[0].title


def test_structured_data_detection_handles_graph():
    html = '<script type="application/ld+json">{"@graph":[{"@type":["WebSite"]},{"@type":"BeautySalon"}]}</script>'
    from bs4 import BeautifulSoup
    assert "beautysalon" in checks_page._schema_types(BeautifulSoup(html, "html.parser"))


def _chromium_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return Path(pw.chromium.executable_path).exists()
    except Exception:
        return False


@pytest.mark.skipif(not _chromium_ready(), reason="Chromium for Playwright is not installed")
def test_browser_checks_take_screenshots_and_measure(good_site, tmp_path):
    res = agent.audit(good_site.url + "/", "clinics", shots_dir=tmp_path,
                      fetcher=SafeFetcher(allow_private=True, delay=0))
    assert set(res.screenshots) == {"desktop", "mobile"}
    assert (tmp_path / "mobile.jpg").stat().st_size > 1000
    assert res.metrics["desktop"]["requests"] >= 1 and "overflow_px" in res.metrics["mobile"]
    assert res.metrics["mobile"]["cta_above_fold"] >= 1
    shutil.rmtree(tmp_path, ignore_errors=True)
