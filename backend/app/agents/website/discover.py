"""Phase 2.2 — find the pages worth inspecting (home, contact, services, booking, ...)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

from .fetch import FetchResult, SafeFetcher

MAX_PAGES = 8
MAX_SITEMAP_URLS = 2000
# page type -> words in the link URL or text (English + common Arabic)
PAGE_TYPES: dict[str, tuple[str, ...]] = {
    "contact": ("contact", "reach-us", "get-in-touch", "find-us", "location", "اتصل", "تواصل"),
    "booking": ("book", "appointment", "reserve", "reservation", "schedule", "حجز", "موعد"),
    "services": ("service", "treatment", "what-we-do", "menu", "courses", "programs", "خدمات"),
    "pricing": ("price", "pricing", "packages", "fees", "rates", "أسعار"),
    "about": ("about", "who-we-are", "our-story", "من-نحن", "من نحن"),
    "team": ("team", "doctors", "our-doctors", "staff", "trainers", "فريق"),
    "faq": ("faq", "questions", "الأسئلة"),
    "blog": ("blog", "news", "articles"),
    "privacy": ("privacy", "terms", "الخصوصية"),
}
PRIORITY = ["contact", "booking", "services", "pricing", "about", "team", "faq", "blog", "privacy"]


@dataclass(frozen=True)
class Discovery:
    home: FetchResult
    pages: dict[str, str]            # page type -> url (home included)
    internal_links: tuple[str, ...]  # every same-site link seen on the home page
    robots_found: bool
    sitemaps: tuple[str, ...]
    sitemap_url_count: int


def same_site(url: str, base: str) -> bool:
    a, b = urlparse(url).netloc.lower(), urlparse(base).netloc.lower()
    return a.removeprefix("www.") == b.removeprefix("www.")


def classify(url: str, text: str) -> str:
    hay = f"{urlparse(url).path} {text}".lower()
    for kind in PRIORITY:
        if any(w in hay for w in PAGE_TYPES[kind]):
            return kind
    return ""


def links(html: str, base: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#", "whatsapp:")):
            continue
        url = urldefrag(urljoin(base, href))[0]
        if url not in seen and url.startswith(("http://", "https://")):
            seen.add(url)
            out.append((url, a.get_text(" ", strip=True)[:80]))
    return out


def _sitemaps(fetcher: SafeFetcher, home: str) -> tuple[bool, tuple[str, ...], int]:
    base = f"{urlparse(home).scheme}://{urlparse(home).netloc}"
    robots = fetcher.get(base + "/robots.txt", check_robots=False)
    found = robots.ok and "text/html" not in robots.headers.get("content-type", "").lower()
    maps = tuple(urljoin(base + "/", m) for m in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots.text)) if found else ()
    candidates = maps or (base + "/sitemap.xml",)
    for sm in candidates[:2]:
        r = fetcher.get(sm)
        if r.ok and "<loc>" in r.text:
            return found, maps or (sm,), min(r.text.count("<loc>"), MAX_SITEMAP_URLS)
    return found, maps, 0


def discover(fetcher: SafeFetcher, url: str, max_pages: int = MAX_PAGES) -> Discovery:
    home = fetcher.get(url)
    if not home.ok:
        return Discovery(home, {}, (), False, (), 0)
    final = home.final_url or url
    found_links = [(u, t) for u, t in links(home.text, final) if same_site(u, final)]
    pages: dict[str, str] = {"home": final}
    for u, t in found_links:
        kind = classify(u, t)
        if kind and kind not in pages and u.rstrip("/") != final.rstrip("/"):
            pages[kind] = u
    ordered = {"home": final} | {k: pages[k] for k in PRIORITY if k in pages}
    pages = dict(list(ordered.items())[:max(1, max_pages)])
    robots_found, sitemaps, count = _sitemaps(fetcher, final)
    return Discovery(home, pages, tuple(u for u, _ in found_links), robots_found, sitemaps, count)
