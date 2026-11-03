"""Recognise and clean social media profile links (Phase 3.1).

Only links that point at a profile/page count. Share buttons, single posts, the platform's home page and
website-builder credit links are thrown away.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from ...ingest.normalize import norm_name

PLATFORMS = ("instagram", "facebook", "tiktok", "youtube", "linkedin", "x", "snapchat", "pinterest")
# account names that belong to website builders/themes, not to the business
BUILDER_HANDLES = {"wix", "squarespace", "wordpress", "wordpressdotcom", "elementor", "godaddy", "shopify",
                   "envato", "themeforest", "webflow", "hostinger", "yourpage", "yourusername", "username", "example"}
_NOT_A_PROFILE = {
    "instagram": {"p", "reel", "reels", "explore", "stories", "accounts", "tv", "about", "legal", "developer"},
    "facebook": {"sharer", "sharer.php", "share", "share.php", "plugins", "tr", "dialog", "events", "groups",
                 "watch", "photo", "photo.php", "story.php", "login", "help", "policies", "privacy", "hashtag"},
    "x": {"intent", "share", "home", "search", "hashtag", "i", "login", "privacy", "tos"},
    "tiktok": {"tag", "music", "discover", "embed", "legal"},
    "youtube": {"watch", "embed", "results", "shorts", "playlist", "feed", "redirect", "t", "about"},
    "linkedin": {"sharearticle", "shareArticle", "feed", "jobs", "login", "legal", "pulse", "posts"},
    "pinterest": {"pin", "search", "ideas", "_"},
    "snapchat": {"discover", "spotlight", "lens"},
}


@dataclass(frozen=True)
class Profile:
    platform: str
    handle: str
    url: str  # cleaned, canonical form


def _platform(host: str) -> str:
    host = host.lower().removeprefix("www.").removeprefix("m.").removeprefix("mobile.")
    for name, domains in (("instagram", ("instagram.com", "instagr.am")), ("facebook", ("facebook.com", "fb.com", "fb.me")),
                          ("tiktok", ("tiktok.com",)), ("youtube", ("youtube.com", "youtu.be")),
                          ("linkedin", ("linkedin.com",)), ("x", ("twitter.com", "x.com")),
                          ("snapchat", ("snapchat.com",)), ("pinterest", ("pinterest.com",))):
        if any(host == d or host.endswith("." + d) for d in domains):
            return name
    return ""


def parse(url: str) -> Profile | None:
    """Profile for a link, or None when it is not a profile/page link."""
    if not url or not url.lower().startswith(("http://", "https://", "//")):
        return None
    p = urlparse(url if not url.startswith("//") else "https:" + url)
    platform = _platform(p.netloc)
    if not platform:
        return None
    parts = [x for x in p.path.split("/") if x]
    if platform == "facebook" and parts[:1] in (["profile.php"],) and parse_qs(p.query).get("id"):
        pid = parse_qs(p.query)["id"][0]
        return Profile("facebook", pid, f"https://www.facebook.com/profile.php?id={pid}")
    if platform == "facebook" and parts[:1] == ["pages"] and len(parts) >= 2:
        parts = parts[1:]  # facebook.com/pages/Name/123
    if platform == "linkedin":
        if len(parts) < 2 or parts[0] not in ("company", "in", "school", "showcase"):
            return None
        handle = parts[1]
        return None if handle.lower() in BUILDER_HANDLES else Profile("linkedin", handle, f"https://www.linkedin.com/{parts[0]}/{handle}")
    if platform == "youtube":
        if not parts:
            return None
        if parts[0].startswith("@"):
            handle = parts[0]
        elif parts[0] in ("channel", "c", "user") and len(parts) > 1:
            handle = f"{parts[0]}/{parts[1]}"
        else:
            return None
        return Profile("youtube", handle, f"https://www.youtube.com/{handle}")
    if platform == "snapchat":
        if len(parts) < 2 or parts[0] != "add":
            return None
        return Profile("snapchat", parts[1], f"https://www.snapchat.com/add/{parts[1]}")
    if not parts:
        return None
    first = parts[0]
    blocked = _NOT_A_PROFILE.get(platform, set())
    if first.lower() in blocked or first.lower().removesuffix(".php") in blocked:
        return None
    if platform == "tiktok" and not first.startswith("@"):
        return None
    handle = first.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9._\-]{2,80}", handle) or handle.lower() in BUILDER_HANDLES:
        return None
    base = {"instagram": "https://www.instagram.com/", "facebook": "https://www.facebook.com/",
            "x": "https://x.com/", "pinterest": "https://www.pinterest.com/", "tiktok": "https://www.tiktok.com/@"}[platform]
    return Profile(platform, handle, base + handle)


def name_match(handle: str, business_name: str) -> float:
    """0..1: how much the account name looks like the business name (letters only, order kept)."""
    h = re.sub(r"[^a-z0-9]", "", handle.lower())
    words = [w for w in norm_name(business_name).split() if len(w) > 2 and w not in
             {"salon", "spa", "clinic", "centre", "center", "medical", "dental", "beauty", "ladies", "the", "and",
              "academy", "institute", "training", "llc", "dubai", "uae", "fz"}]
    if not h or not words:
        return 0.0
    joined = "".join(words)
    if joined and joined in h:
        return 1.0
    hits = sum(1 for w in words if w in h)
    return hits / len(words)
