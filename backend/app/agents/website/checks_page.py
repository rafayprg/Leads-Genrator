"""Phase 2.4 + 2.7 — SEO checks per page, and conversion checks across the inspected pages."""
from __future__ import annotations

import json
import re
from collections import Counter

from bs4 import BeautifulSoup

from ..findings import C, Finding, S, V

TITLE_MAX, TITLE_MIN, DESC_MAX = 65, 10, 170
LOCAL_SCHEMA_TYPES = ("localbusiness", "organization", "medicalbusiness", "dentist", "medicalclinic", "physician",
                      "beautysalon", "hairsalon", "dayspa", "healthandbeautybusiness", "educationalorganization",
                      "school", "restaurant", "autorepair", "realestateagent", "exercisegym", "veterinarycare")
BOOKING_WORDS = re.compile(r"(?i)\bbook(ing)?\b|appointment|reserve|reservation|schedule a|حجز|موعد")
TRUST_WORDS = re.compile(r"(?i)testimonial|review|what (our )?(clients|patients|customers) say|rated|stars?\b|آراء")
# where booking matters most for a first contact
BOOKING_INDUSTRIES = {"beauty", "clinics", "fitness", "veterinary", "academies", "driving_schools", "automotive"}


def _schema_types(soup: BeautifulSoup) -> set[str]:
    types = set()
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                t = item.get("@type")
                types |= {x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)}
                stack += item.get("@graph", []) if isinstance(item.get("@graph"), list) else []
    return types


def seo(kind: str, url: str, html: str, headers: dict) -> list[Finding]:
    soup = BeautifulSoup(html, "html.parser")
    home = kind == "home"
    out: list[Finding] = []
    ev = {"url": url, "page": kind}

    title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    if not title:
        out.append(Finding("seo", f"{kind.title()} page has no title", S.MEDIUM if home else S.LOW,
                           "Add a title with the business name, main service and city, e.g. 'Dental Clinic in Al Barsha, Dubai | Name'.",
                           impact="Google shows a poor or random headline for the page.", evidence=ev, source_url=url))
    elif len(title) > TITLE_MAX or len(title) < TITLE_MIN:
        out.append(Finding("seo", f"{kind.title()} page title is too {'long' if len(title) > TITLE_MAX else 'short'}",
                           S.LOW, f"Keep titles between {TITLE_MIN} and {TITLE_MAX} characters.",
                           impact="Google cuts long titles; very short ones say little.",
                           evidence={**ev, "title": title, "length": len(title)}, source_url=url))
    desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    if not desc or not (desc.get("content") or "").strip():
        out.append(Finding("seo", f"{kind.title()} page has no meta description", S.LOW,
                           "Write a 1–2 sentence summary with the main service, area and a reason to visit.",
                           impact="Google picks random text for the search snippet.", evidence=ev, source_url=url))
    h1s = soup.find_all("h1")
    if home and not h1s:
        out.append(Finding("seo", "Homepage has no main heading (H1)", S.MEDIUM,
                           "Add one clear H1 that says what the business does and where.",
                           impact="Visitors and search engines get a weaker first signal of what the page is about.",
                           evidence=ev, source_url=url))
    elif len(h1s) > 1:
        out.append(Finding("seo", f"{kind.title()} page has {len(h1s)} main headings (H1)", S.LOW,
                           "Keep one H1 per page and use H2/H3 for sections.", impact="Muddier page structure.",
                           evidence={**ev, "h1": [h.get_text(' ', strip=True)[:60] for h in h1s[:4]]}, source_url=url))
    imgs = soup.find_all("img")
    no_alt = [i.get("src", "")[:120] for i in imgs if not (i.get("alt") or "").strip()]
    if imgs and len(no_alt) / len(imgs) > 0.3 and len(no_alt) >= 3:
        out.append(Finding("accessibility", f"{len(no_alt)} of {len(imgs)} images on the {kind} page have no description (alt text)",
                           S.LOW, "Add short alt text describing each meaningful image.",
                           impact="Screen-reader users miss the content; image search cannot understand the photos.",
                           evidence={**ev, "examples": no_alt[:5]}, source_url=url))
    robots_meta = soup.find("meta", attrs={"name": re.compile("^robots$", re.I)})
    noindex = "noindex" in ((robots_meta.get("content") or "").lower() if robots_meta else "") or \
        "noindex" in headers.get("x-robots-tag", headers.get("X-Robots-Tag", "")).lower()
    if noindex and kind in ("home", "services", "contact", "booking"):
        out.append(Finding("seo", f"{kind.title()} page tells Google not to list it (noindex)", S.HIGH,
                           "Remove 'noindex' unless the page is meant to be hidden.",
                           impact="The page cannot appear in Google search results.", evidence=ev, source_url=url))
    if home:
        if not soup.find("meta", attrs={"name": re.compile("^viewport$", re.I)}):
            out.append(Finding("mobile", "Homepage is not set up for mobile screens (no viewport tag)", S.HIGH,
                               "Add <meta name='viewport' content='width=device-width, initial-scale=1'> or use a mobile-friendly theme.",
                               impact="On phones the page shows zoomed-out and hard to use.", evidence=ev, source_url=url))
        if not soup.find("link", rel=lambda r: r and "canonical" in [x.lower() for x in r]):
            out.append(Finding("seo", "Homepage has no canonical link", S.LOW,
                               "Add a canonical link pointing to the main address of the homepage.",
                               impact="Minor: duplicate versions of the page may compete in search.", evidence=ev,
                               source_url=url, confidence=C.MEDIUM))
        if not (soup.html and soup.html.get("lang")):
            out.append(Finding("accessibility", "Page language is not declared", S.LOW,
                               "Add lang='en' (or 'ar') to the <html> tag.",
                               impact="Screen readers may read the text with the wrong voice.", evidence=ev, source_url=url))
        if not any(t in LOCAL_SCHEMA_TYPES for t in _schema_types(soup)):
            out.append(Finding("seo", "No local business details for search engines (structured data)", S.LOW,
                               "Add LocalBusiness structured data with name, address, phone, hours.",
                               impact="Search engines get less certain business details; minor for small sites.",
                               evidence=ev, source_url=url, confidence=C.MEDIUM))
    return out


def duplicate_titles(pages: dict[str, str]) -> list[Finding]:
    titles = {}
    for kind, html in pages.items():
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            titles[kind] = soup.title.string.strip()
    dupes = [t for t, n in Counter(titles.values()).items() if n > 1]
    if not dupes:
        return []
    return [Finding("seo", "Several pages share the same title", S.LOW,
                    "Give each page its own title describing that page.",
                    impact="Search engines struggle to tell the pages apart.",
                    evidence={"title": dupes[0], "pages": [k for k, t in titles.items() if t == dupes[0]]})]


def conversion(pages: dict[str, str], urls: dict[str, str], industry: str) -> list[Finding]:
    """Can a visitor easily call, message or book? Looks across every inspected page."""
    soups = {k: BeautifulSoup(h, "html.parser") for k, h in pages.items()}
    hrefs = [a["href"].lower() for s in soups.values() for a in s.find_all("a", href=True)]
    text = " ".join(s.get_text(" ", strip=True) for s in soups.values())
    home = urls.get("home", "")
    out = []
    if not any(h.startswith("tel:") for h in hrefs):
        out.append(Finding("conversion", "No tap-to-call phone link", S.MEDIUM,
                           "Make the phone number a tel: link, especially in the header on mobile.",
                           impact="Mobile visitors must copy the number by hand to call.",
                           evidence={"pages_checked": list(urls.values())}, source_url=home))
    if not any("wa.me" in h or "whatsapp" in h for h in hrefs):
        out.append(Finding("conversion", "No WhatsApp contact link", S.MEDIUM,
                           "Add a WhatsApp button (wa.me link) — most customers in the Gulf and South Asia prefer to message first.",
                           impact="Visitors who prefer messaging have no quick way to reach the business.",
                           evidence={"pages_checked": list(urls.values())}, source_url=home, confidence=C.HIGH))
    booking_link = any(BOOKING_WORDS.search(h) for h in hrefs) or "booking" in urls
    booking_text = bool(BOOKING_WORDS.search(text))
    if industry in BOOKING_INDUSTRIES and not (booking_link or booking_text):
        out.append(Finding("conversion", "No clear way to book an appointment online", S.HIGH,
                           "Add a visible 'Book appointment' button on the homepage leading to a simple booking form.",
                           impact="Visitors ready to book have to call or leave; bookings may be lost after hours.",
                           evidence={"pages_checked": list(urls.values()), "searched_for": "book / appointment / reserve"},
                           source_url=home, confidence=C.MEDIUM, verification=V.INFERRED))
    if not any(s.find("form") for s in soups.values()):
        out.append(Finding("conversion", "No contact or enquiry form on the inspected pages", S.LOW,
                           "Add a short enquiry form (name, phone, message) on the contact page.",
                           impact="Visitors who do not want to call have fewer ways to reach out.",
                           evidence={"pages_checked": list(urls.values())}, source_url=urls.get("contact", home),
                           confidence=C.MEDIUM, verification=V.INFERRED))
    if not TRUST_WORDS.search(text):
        out.append(Finding("conversion", "No reviews or testimonials shown", S.LOW,
                           "Show a few real customer reviews (e.g. from Google) on the homepage.",
                           impact="New visitors see less proof that others trust the business.",
                           evidence={"pages_checked": list(urls.values())}, source_url=home,
                           confidence=C.MEDIUM, verification=V.INFERRED))
    return out
