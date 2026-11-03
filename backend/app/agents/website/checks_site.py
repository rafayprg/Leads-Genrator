"""Phase 2.3 — technical checks on the whole site: reachability, HTTPS, speed, redirects, broken links."""
from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from ..findings import C, Finding, S, V
from .discover import Discovery
from .fetch import FetchResult, SafeFetcher

SLOW_MS = 3000
VERY_SLOW_MS = 8000
MAX_LINKS_TO_TEST = 25
IMPORTANT = ("contact", "booking", "services", "pricing")


def unreachable(url: str, home: FetchResult) -> Finding:
    if home.blocked == "unsafe":
        return Finding("availability", "Website address points to a private or unsafe location", S.HIGH,
                       "Check the website address listed on Google Maps; it should be the public site.",
                       impact="Customers clicking the listed website cannot reach the business.",
                       evidence={"url": url, "reason": home.error}, source_url=url)
    if home.blocked == "robots":
        return Finding("availability", "Website asks automated tools not to read it", S.LOW,
                       "Nothing to fix for customers; this audit could not inspect the pages.",
                       impact="Audit limited, not a customer-facing problem.", evidence={"url": url},
                       source_url=url, confidence=C.HIGH, verification=V.VERIFIED)
    if "domain name not found" in home.error:
        return Finding("availability", "Website domain could not be found", S.HIGH,
                       "Check that the domain is renewed and the address on Google Maps is spelled right. Re-test later.",
                       impact="If the domain really expired, everyone clicking the website link sees an error.",
                       evidence={"url": url, "result": home.error}, source_url=url, confidence=C.MEDIUM,
                       verification=V.REQUIRES_REVIEW)
    detail = home.error or f"HTTP {home.status}"
    return Finding("availability", "Website did not load during the audit", S.HIGH if home.tls_error else S.CRITICAL,
                   "Check hosting and the domain; renew the SSL certificate if it expired." if home.tls_error
                   else "Check hosting, domain renewal and DNS. Re-test later: it may be a temporary outage.",
                   impact="Visitors from Google Maps and social media hit an error page instead of the business.",
                   evidence={"url": url, "result": detail, "redirects": list(home.redirects)}, source_url=url,
                   confidence=C.MEDIUM, verification=V.VERIFIED)


def https_checks(fetcher: SafeFetcher, d: Discovery) -> list[Finding]:
    out = []
    final = d.home.final_url
    if final.startswith("http://"):
        out.append(Finding("https", "Website does not use HTTPS", S.HIGH,
                           "Install a free SSL certificate (e.g. Let's Encrypt) and redirect http:// to https://.",
                           impact="Browsers mark the site 'Not secure'; forms send data unencrypted.",
                           evidence={"final_url": final}, source_url=final))
    else:
        plain = "http://" + final.split("://", 1)[1]
        r = fetcher.get(plain, check_robots=False)
        if r.ok and r.final_url.startswith("http://"):
            out.append(Finding("https", "The http:// version does not redirect to https://", S.MEDIUM,
                               "Add a permanent (301) redirect from http:// to https://.",
                               impact="Some visitors land on the insecure version.",
                               evidence={"tested": plain, "ended_at": r.final_url}, source_url=plain))
    if len(d.home.redirects) > 2:
        out.append(Finding("redirects", f"Homepage goes through {len(d.home.redirects)} redirects", S.LOW,
                           "Point links straight at the final address to save a few hundred milliseconds.",
                           impact="Slower first load, especially on mobile data.",
                           evidence={"chain": [f"{u} ({c})" for u, c in d.home.redirects]}, source_url=d.home.url))
    return out


def speed_check(home: FetchResult) -> list[Finding]:
    if home.elapsed_ms >= VERY_SLOW_MS:
        sev = S.HIGH
    elif home.elapsed_ms >= SLOW_MS:
        sev = S.MEDIUM
    else:
        return []
    return [Finding("performance", f"Homepage HTML took {home.elapsed_ms / 1000:.1f}s to arrive", sev,
                    "Ask the host about server speed or caching; consider a CDN.",
                    impact="Many mobile visitors leave before a slow page appears.",
                    evidence={"url": home.final_url, "elapsed_ms": home.elapsed_ms,
                              "note": "measured once from the audit computer"},
                    source_url=home.final_url, confidence=C.MEDIUM)]


def broken_links(fetcher: SafeFetcher, d: Discovery, max_links: int = MAX_LINKS_TO_TEST) -> list[Finding]:
    important = {u: k for k, u in d.pages.items() if k in IMPORTANT}
    to_test = list(dict.fromkeys(list(important) + list(d.internal_links)))[:max_links]
    broken = []
    for u in to_test:
        r = fetcher.get(u, method="HEAD")
        if r.status in (405, 501) or (r.status == 0 and not r.blocked):
            r = fetcher.get(u)  # some servers refuse HEAD
        if r.blocked:
            continue
        if r.status >= 400 or (r.status == 0 and r.error):
            broken.append((u, r.status or r.error))
    out = []
    for u, why in broken:
        kind = important.get(u)
        out.append(Finding("links", f"Broken link: {kind + ' page' if kind else urlparse(u).path or u}",
                           S.HIGH if kind else S.MEDIUM, "Fix or remove the link; set up a redirect if the page moved.",
                           impact="Visitors following it hit an error" + (" on an important step." if kind else "."),
                           evidence={"url": u, "result": why, "linked_from": d.home.final_url}, source_url=u))
    return out


def mixed_content(d: Discovery) -> list[Finding]:
    if not d.home.final_url.startswith("https://"):
        return []
    soup = BeautifulSoup(d.home.text, "html.parser")
    insecure = [t.get("src") for t in soup.find_all(["img", "script", "iframe", "source"], src=True)
                if t.get("src", "").startswith("http://")]
    insecure += [t.get("href") for t in soup.find_all("link", href=True)
                 if t.get("href", "").startswith("http://") and "stylesheet" in (t.get("rel") or [])]
    if not insecure:
        return []
    return [Finding("https", f"{len(insecure)} file(s) load over insecure http:// on an https page", S.MEDIUM,
                    "Change these links to https:// so browsers do not block them.",
                    impact="Images, styles or scripts may not show; browsers warn about mixed content.",
                    evidence={"examples": insecure[:5]}, source_url=d.home.final_url)]


def crawl_files(d: Discovery) -> list[Finding]:
    out = []
    if not d.sitemap_url_count:
        out.append(Finding("seo", "No sitemap found", S.LOW,
                           "Add a sitemap.xml (most website builders can generate one) and list it in robots.txt.",
                           impact="Search engines may find new pages more slowly. Minor for small sites.",
                           evidence={"looked_for": list(d.sitemaps) or ["/sitemap.xml"]}, source_url=d.home.final_url,
                           confidence=C.MEDIUM))
    return out


def run(fetcher: SafeFetcher, d: Discovery, max_links: int = MAX_LINKS_TO_TEST) -> list[Finding]:
    return (https_checks(fetcher, d) + speed_check(d.home) + broken_links(fetcher, d, max_links) + mixed_content(d)
            + crawl_files(d))
