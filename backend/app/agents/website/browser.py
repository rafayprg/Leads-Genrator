"""Phases 2.5–2.7 in a real browser (Playwright Chromium): speed, mobile layout, accessibility, mobile CTA.

Every request the page makes goes through the same safety check as the fetcher, so a business website
cannot make the audit browser reach this computer's network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from ..findings import C, Finding, S, V
from .fetch import HostNotFound, SafeFetcher, UnsafeURL

SHOT_QUALITY = 70
NAV_TIMEOUT_MS = 30_000
SETTLE_MS = 2500
MOBILE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2, "is_mobile": True, "has_touch": True,
          "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
                        "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"}
DESKTOP = {"viewport": {"width": 1366, "height": 800}}

OBSERVERS = """
window.__lcp = 0; window.__cls = 0;
try {
  new PerformanceObserver(l => { for (const e of l.getEntries()) window.__lcp = e.startTime })
    .observe({type: 'largest-contentful-paint', buffered: true});
  new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value })
    .observe({type: 'layout-shift', buffered: true});
} catch (e) {}
"""
METRICS_JS = """() => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const res = performance.getEntriesByType('resource');
  const bytes = res.reduce((a, r) => a + (r.transferSize || 0), 0) + (nav.transferSize || 0);
  return {ttfb_ms: Math.round(nav.responseStart || 0), dom_ready_ms: Math.round(nav.domContentLoadedEventEnd || 0),
          load_ms: Math.round(nav.loadEventEnd || 0), lcp_ms: Math.round(window.__lcp || 0),
          cls: Math.round((window.__cls || 0) * 1000) / 1000, requests: res.length + 1, bytes};
}"""
MOBILE_JS = """() => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const visible = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const cta = /(book|appointment|reserve|call|whatsapp|contact|enquire|حجز|اتصل)/i;
  const actions = [...document.querySelectorAll('a, button')].filter(visible);
  const above = actions.filter(el => { const r = el.getBoundingClientRect();
    const href = (el.getAttribute('href') || '').toLowerCase();
    return r.top < vh && r.bottom > 0 && (cta.test(el.innerText || '') || href.startsWith('tel:') || href.includes('wa.me')); });
  const small = actions.filter(el => { const r = el.getBoundingClientRect(); return r.width < 32 || r.height < 32; });
  let tiny = 0;
  for (const el of document.querySelectorAll('p, li, span, a, td')) {
    if (visible(el) && (el.innerText || '').trim().length > 20 && parseFloat(getComputedStyle(el).fontSize) < 12) tiny++;
  }
  return {overflow_px: Math.max(0, document.documentElement.scrollWidth - vw), cta_above_fold: above.length,
          cta_examples: above.slice(0, 3).map(e => (e.innerText || e.getAttribute('href') || '').trim().slice(0, 40)),
          small_tap_targets: small.length, tap_targets: actions.length, tiny_text_blocks: tiny};
}"""


@dataclass
class BrowserResult:
    findings: list[Finding] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    screenshots: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)


def _guard(fetcher: SafeFetcher):
    ok_hosts: dict[str, bool] = {}

    def handler(route):
        url = route.request.url
        if url.startswith(("data:", "blob:")):
            return route.continue_()
        host = urlparse(url).netloc
        if host not in ok_hosts:
            try:
                fetcher.check_url(url)
                ok_hosts[host] = True
            except (UnsafeURL, HostNotFound):
                ok_hosts[host] = False
        return route.continue_() if ok_hosts[host] else route.abort()
    return handler


def _perf_findings(m: dict, url: str) -> list[Finding]:
    out = []
    lcp = m.get("lcp_ms") or m.get("load_ms") or 0
    if lcp > 4000:
        out.append(Finding("performance", f"Main content takes {lcp / 1000:.1f}s to appear on desktop", S.HIGH,
                           "Compress large images (WebP), remove unused plugins/scripts, enable caching.",
                           impact="Slow pages lose visitors before they see the offer.", evidence={"url": url, **m},
                           source_url=url, confidence=C.MEDIUM))
    elif lcp > 2500:
        out.append(Finding("performance", f"Main content takes {lcp / 1000:.1f}s to appear on desktop", S.MEDIUM,
                           "Compress the largest images and defer non-essential scripts.",
                           impact="Noticeably slow first impression.", evidence={"url": url, **m}, source_url=url,
                           confidence=C.MEDIUM))
    if m.get("cls", 0) > 0.25:
        out.append(Finding("performance", "Page content jumps around while loading", S.MEDIUM,
                           "Give images and banners fixed sizes so content does not shift.",
                           impact="Visitors tap the wrong thing as the layout moves.",
                           evidence={"url": url, "cls": m["cls"]}, source_url=url, confidence=C.MEDIUM))
    mb = m.get("bytes", 0) / 1_000_000
    if mb > 5:
        out.append(Finding("performance", f"Homepage downloads {mb:.1f} MB", S.MEDIUM,
                           "Resize and compress images; most homepages fit in under 2 MB.",
                           impact="Slow and costly on mobile data.", evidence={"url": url, "bytes": m["bytes"]},
                           source_url=url))
    return out


def _mobile_findings(mob: dict, url: str, shot: str) -> list[Finding]:
    out, ev = [], {"url": url, "screen": "390x844 phone", "screenshot": shot}
    if mob.get("overflow_px", 0) > 10:
        out.append(Finding("mobile", "Page is wider than a phone screen (sideways scrolling)", S.MEDIUM,
                           "Find the element that overflows (often a wide image or table) and make it responsive.",
                           impact="Visitors have to scroll sideways; the site feels broken on mobile.",
                           evidence={**ev, "overflow_px": mob["overflow_px"]}, source_url=url))
    if mob.get("cta_above_fold", 0) == 0:
        out.append(Finding("mobile", "No call, WhatsApp or booking button on the first phone screen", S.MEDIUM,
                           "Put a 'Book' or 'WhatsApp us' button in the top part of the mobile homepage.",
                           impact="Mobile visitors must scroll or search to take the next step.", evidence=ev,
                           source_url=url, confidence=C.MEDIUM, verification=V.VERIFIED))
    total = mob.get("tap_targets", 0)
    if total and mob.get("small_tap_targets", 0) / total > 0.3 and mob["small_tap_targets"] >= 5:
        out.append(Finding("mobile", f"{mob['small_tap_targets']} links/buttons are small to tap on a phone", S.LOW,
                           "Make buttons and links at least about 44px tall on mobile.",
                           impact="Mis-taps and frustration on phones.", evidence={**ev, **mob}, source_url=url,
                           confidence=C.MEDIUM))
    if mob.get("tiny_text_blocks", 0) >= 5:
        out.append(Finding("mobile", "Some text is very small on phones", S.LOW, "Use at least 14–16px body text on mobile.",
                           impact="Hard to read without zooming.", evidence={**ev, "blocks": mob["tiny_text_blocks"]},
                           source_url=url, confidence=C.MEDIUM))
    return out


def _axe_findings(page, url: str) -> list[Finding]:
    from axe_playwright_python.sync_playwright import Axe
    violations = Axe().run(page).response.get("violations", [])
    out = []
    for v in sorted(violations, key=lambda v: ("critical", "serious").index(v["impact"])
                    if v.get("impact") in ("critical", "serious") else 9)[:5]:
        if v.get("impact") not in ("critical", "serious"):
            continue
        out.append(Finding("accessibility", v.get("help", v.get("id", "Accessibility problem")),
                           S.MEDIUM if v["impact"] == "critical" else S.LOW,
                           f"Fix as described here: {v.get('helpUrl', '')}".strip(),
                           impact="Harder or impossible to use for people with disabilities; also hurts usability.",
                           evidence={"url": url, "rule": v.get("id"), "impact": v["impact"], "elements": len(v.get("nodes", [])),
                                     "example": (v.get("nodes") or [{}])[0].get("html", "")[:200]},
                           source_url=url))
    return out


def run(url: str, fetcher: SafeFetcher, shots_dir: Path) -> BrowserResult:
    res = BrowserResult()
    try:
        from playwright.sync_api import Error as PwError
        from playwright.sync_api import sync_playwright
    except ImportError:
        res.limitations.append("Browser checks skipped: Playwright is not installed")
        return res
    shots_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for name, opts in (("desktop", DESKTOP), ("mobile", MOBILE)):
                    ctx = browser.new_context(**opts, service_workers="block")
                    ctx.route("**/*", _guard(fetcher))
                    page = ctx.new_page()
                    page.add_init_script(OBSERVERS)
                    try:
                        page.goto(url, wait_until="load", timeout=NAV_TIMEOUT_MS)
                    except PwError as e:
                        res.limitations.append(f"{name}: page did not finish loading ({str(e).splitlines()[0][:120]})")
                    page.wait_for_timeout(SETTLE_MS)
                    shot = shots_dir / f"{name}.jpg"  # JPEG: ~6x smaller than PNG, reports and PDFs stay light
                    page.screenshot(path=str(shot), type="jpeg", quality=SHOT_QUALITY)
                    res.screenshots[name] = shot.name
                    if name == "desktop":
                        res.metrics["desktop"] = page.evaluate(METRICS_JS)
                        res.findings += _perf_findings(res.metrics["desktop"], url)
                        try:
                            res.findings += _axe_findings(page, url)
                        except Exception as e:  # accessibility engine problems must not stop the audit
                            res.limitations.append(f"Accessibility scan failed: {type(e).__name__}")
                    else:
                        res.metrics["mobile"] = page.evaluate(MOBILE_JS)
                        res.findings += _mobile_findings(res.metrics["mobile"], url, shot.name)
                    ctx.close()
            finally:
                browser.close()
    except Exception as e:  # browser missing / crashed: report, keep the HTML-based audit
        res.limitations.append(f"Browser checks skipped: {type(e).__name__}: {str(e).splitlines()[0][:160]}")
    return res
