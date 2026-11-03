"""Agent 1 — Website Expert. Inspects a business website and returns evidence-based findings.

Boundary (from the architecture doc): website only. No social media audit, no automation runs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ...models import Severity
from ..findings import Finding
from . import browser, checks_page, checks_site
from .discover import discover
from .fetch import SafeFetcher

SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


@dataclass
class WebsiteAudit:
    status: str                      # completed / partial / failed / skipped
    website_url: str
    findings: list[Finding] = field(default_factory=list)
    pages: dict = field(default_factory=dict)      # page type -> url actually inspected
    metrics: dict = field(default_factory=dict)
    screenshots: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    def summary(self) -> dict:
        counts = {str(s): 0 for s in SEVERITY_ORDER}
        for f in self.findings:
            counts[str(f.severity)] += 1
        return {"agent": "website_expert", "status": self.status, "website_url": self.website_url,
                "pages_inspected": len(self.pages), "pages": self.pages, "issues_found": len(self.findings),
                "by_severity": counts, "metrics": self.metrics, "screenshots": self.screenshots,
                "limitations": self.limitations, "started_at": self.started_at, "completed_at": self.completed_at}


def audit(website_url: str | None, industry: str = "", shots_dir: Path | None = None,
          fetcher: SafeFetcher | None = None, use_browser: bool = True, max_pages: int = 8,
          max_links: int = 25) -> WebsiteAudit:
    started = datetime.now(UTC).isoformat(timespec="seconds")
    if not website_url:
        return WebsiteAudit("skipped", "", limitations=["No website on record for this business"],
                            started_at=started, completed_at=started)
    fetcher = fetcher or SafeFetcher()
    res = WebsiteAudit("completed", website_url, started_at=started)
    d = discover(fetcher, website_url, max_pages)
    if not d.home.ok and d.home.error.startswith("DNS lookup failed"):
        # our computer's problem, not the business's: no finding, just a clear "retry"
        res.status = "failed"
        res.limitations.append(f"{d.home.error}. Nothing was concluded about this website.")
        res.completed_at = datetime.now(UTC).isoformat(timespec="seconds")
        return res
    if not d.home.ok:
        res.status = "failed"
        res.findings.append(checks_site.unreachable(website_url, d.home))
        res.limitations.append("Website could not be loaded, so no other checks ran")
        res.completed_at = datetime.now(UTC).isoformat(timespec="seconds")
        return res

    html = {"home": d.home.text}
    headers = {"home": d.home.headers}
    for kind, url in d.pages.items():
        if kind == "home":
            continue
        r = fetcher.get(url)
        if r.ok:
            html[kind], headers[kind] = r.text, r.headers
        else:
            res.limitations.append(f"{kind} page could not be read ({r.blocked or r.error or r.status})")
    res.pages = {k: d.pages[k] for k in html}
    res.metrics["home_html_ms"] = d.home.elapsed_ms
    res.metrics["sitemap_urls"] = d.sitemap_url_count

    res.findings += checks_site.run(fetcher, d, max_links)
    for kind, page_html in html.items():
        res.findings += checks_page.seo(kind, d.pages[kind], page_html, headers[kind])
    res.findings += checks_page.duplicate_titles(html)
    res.findings += checks_page.conversion(html, res.pages, industry)

    if use_browser and shots_dir is not None:
        b = browser.run(d.home.final_url or website_url, fetcher, shots_dir)
        res.findings += b.findings
        res.metrics.update(b.metrics)
        res.screenshots = b.screenshots
        res.limitations += b.limitations
        if b.limitations and not b.metrics:
            res.status = "partial"
    elif use_browser:
        res.limitations.append("Browser checks skipped (no screenshot folder given)")

    res.findings.sort(key=lambda f: SEVERITY_ORDER[f.severity])
    res.completed_at = datetime.now(UTC).isoformat(timespec="seconds")
    return res
