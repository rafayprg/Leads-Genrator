"""Agent 3 — Social Media Finder. Finds the business's official social accounts and hands them to Agent 2.

Decided 31 Oct 2026: sources are ONLY the business's own website (home, contact, about pages) plus links
already on its Google Maps listing. No searching inside social platforms, no scraping them.
Boundary: discovery and identity matching only; content and engagement analysis is Agent 2's job.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...ingest.normalize import own_domain
from ...models import Confidence, Verification
from ..website.discover import discover, links
from ..website.fetch import SafeFetcher
from .profiles import PLATFORMS, Profile, name_match, parse

PAGES_TO_READ = ("home", "contact", "about")
NAME_MATCH_STRONG = 0.6


@dataclass
class Candidate:
    profile: Profile
    on_website_pages: list[str] = field(default_factory=list)  # page types where the link was seen
    on_record: bool = False  # already collected (Google Maps listing / earlier import)
    name_score: float = 0.0

    def decide(self) -> tuple[Confidence, Verification, list[str]]:
        """Multiple signals -> high; one solid signal -> medium; weak -> low (needs a human look)."""
        evidence = []
        if self.on_website_pages:
            pages = self.on_website_pages
            listed = pages[0] if len(pages) == 1 else f"{', '.join(pages[:-1])} and {pages[-1]}"
            evidence.append(f"Linked from the business's own website ({listed} page{'s' if len(pages) > 1 else ''})")
        if self.on_record:
            evidence.append("Already on record from data collection (Google Maps listing or earlier import)")
        if self.name_score >= NAME_MATCH_STRONG:
            evidence.append(f"Account name '{self.profile.handle}' matches the business name or website address")
        elif self.name_score > 0:
            evidence.append(f"Account name '{self.profile.handle}' partly matches the business name")
        else:
            evidence.append(f"Account name '{self.profile.handle}' does not resemble the business name")
        strong = sum([bool(self.on_website_pages), self.on_record, self.name_score >= NAME_MATCH_STRONG])
        if self.on_website_pages and strong >= 2:
            return Confidence.HIGH, Verification.PROBABLE, evidence
        if self.on_website_pages or (self.on_record and self.name_score >= NAME_MATCH_STRONG):
            return Confidence.MEDIUM, Verification.PROBABLE, evidence
        return Confidence.LOW, Verification.REQUIRES_REVIEW, evidence


@dataclass
class SocialDiscovery:
    status: str  # completed / partial / skipped
    profiles: list[dict] = field(default_factory=list)
    platforms_not_found: list[str] = field(default_factory=list)
    profiles_requiring_review: list[str] = field(default_factory=list)
    pages_read: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    checked_at: str = ""

    def summary(self) -> dict:
        return {"agent": "social_media_finder", "discovery_status": self.status, "profiles": self.profiles,
                "platforms_not_found": self.platforms_not_found,
                "profiles_requiring_review": self.profiles_requiring_review, "pages_read": self.pages_read,
                "limitations": self.limitations, "verification_timestamp": self.checked_at,
                "method": "own website links + links already on record only (no searching inside social platforms)"}


def _from_website(fetcher: SafeFetcher, website_url: str) -> tuple[dict[str, list[str]], dict, list[str]]:
    """{profile url -> [page types]} from home/contact/about of the business's own site."""
    found: dict[str, list[str]] = {}
    notes: list[str] = []
    d = discover(fetcher, website_url)
    if not d.home.ok:
        return {}, {}, [f"Website could not be read ({d.home.blocked or d.home.error or d.home.status}); "
                        "only links already on record were used"]
    read = {}
    for kind in PAGES_TO_READ:
        url = d.pages.get(kind)
        if not url:
            continue
        html = d.home.text if kind == "home" else fetcher.get(url).text
        if not html:
            notes.append(f"{kind} page could not be read")
            continue
        read[kind] = url
        for link, _text in links(html, url):
            if parse(link):
                found.setdefault(link, []).append(kind)
    return found, read, notes


def find(business_name: str, website_url: str | None, known_links: list[str],
         fetcher: SafeFetcher | None = None) -> SocialDiscovery:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    if not website_url and not known_links:
        return SocialDiscovery("skipped", platforms_not_found=list(PLATFORMS), checked_at=now,
                               limitations=["No website and no social links on record"])
    res = SocialDiscovery("completed", checked_at=now)
    site_links: dict[str, list[str]] = {}
    if website_url:
        site_links, res.pages_read, notes = _from_website(fetcher or SafeFetcher(), website_url)
        res.limitations += notes
        if notes and not res.pages_read:
            res.status = "partial"
    else:
        res.limitations.append("No website on record; only links already on record were used")

    candidates: dict[str, Candidate] = {}
    for raw, pages in site_links.items():
        p = parse(raw)
        c = candidates.setdefault(p.url, Candidate(p))
        c.on_website_pages = sorted(set(c.on_website_pages + pages), key=PAGES_TO_READ.index)
    for raw in known_links:
        p = parse(raw)
        if p:
            candidates.setdefault(p.url, Candidate(p)).on_record = True
    # the account may carry the brand from the website address rather than the listing name (e.g. vog.ae)
    brand = own_domain(website_url).split(".")[0] if website_url else ""
    for c in candidates.values():
        c.name_score = max(name_match(c.profile.handle, business_name),
                           name_match(c.profile.handle, brand) if len(brand) >= 3 else 0.0)

    for c in sorted(candidates.values(), key=lambda c: (c.profile.platform, -c.name_score)):
        conf, ver, evidence = c.decide()
        res.profiles.append({"platform": c.profile.platform, "handle": c.profile.handle, "profile_url": c.profile.url,
                             "official_status": "likely_official" if conf == Confidence.HIGH else
                             ("probable" if conf == Confidence.MEDIUM else "unverified"),
                             "confidence": str(conf), "verification": str(ver), "evidence": evidence,
                             "verification_timestamp": now})
        if conf == Confidence.LOW:
            res.profiles_requiring_review.append(c.profile.url)
    found_platforms = {p["platform"] for p in res.profiles}
    res.platforms_not_found = [p for p in PLATFORMS if p not in found_platforms]
    return res
