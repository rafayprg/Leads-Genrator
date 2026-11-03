"""Phone, URL and name clean-up (ported from leadgen/leadgen/model.py)."""
from __future__ import annotations

import re
from urllib.parse import urlparse

import phonenumbers
from phonenumbers import PhoneNumberType as T

# Not the business's own website: never used to merge two businesses.
NON_OWN_DOMAINS = (
    "facebook.com", "instagram.com", "linktr.ee", "wa.me", "whatsapp.com", "business.site", "google.com",
    "goo.gl", "sites.google.com", "tiktok.com", "twitter.com", "x.com", "youtube.com", "linkedin.com",
    "fresha.com", "booksy.com", "vagaro.com", "bit.ly", "yellowpages-uae.com", "talabat.com",
    "deliveroo.ae", "noon.com", "careem.com",
)

_PHONE_TYPES = {
    T.MOBILE: "mobile", T.FIXED_LINE: "landline", T.FIXED_LINE_OR_MOBILE: "landline/mobile",
    T.TOLL_FREE: "toll-free", T.SHARED_COST: "call centre", T.UAN: "call centre", T.VOIP: "voip",
    T.PREMIUM_RATE: "premium",
}


def format_phone(raw: str | None, country: str) -> tuple[str, str]:
    """Return (E.164, type) or ("", "") when the number is not valid."""
    if not raw:
        return "", ""
    raw = re.sub(r"(?i)(ext|x)\.?\s*\d+$", "", str(raw)).strip()
    raw = raw.split(";")[0].split(",")[0].split("/")[0]
    try:
        n = phonenumbers.parse(raw, country)
    except phonenumbers.NumberParseException:
        return "", ""
    if not phonenumbers.is_valid_number(n):
        return "", ""
    e164 = phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)
    kind = _PHONE_TYPES.get(phonenumbers.number_type(n), "other")
    nat = str(n.national_number)
    # UAE 600/800 and KSA 920/800 are call-centre / toll-free numbers
    if (n.country_code == 971 and nat[:3] in ("600", "800")) or (n.country_code == 966 and nat[:3] in ("920", "800")):
        kind = "call centre" if nat.startswith(("600", "920")) else "toll-free"
    return e164, kind


def domain(url: str | None) -> str:
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def own_domain(url: str | None) -> str:
    """Domain only if it looks like the business's own site (not facebook, linktree, ...)."""
    d = domain(url)
    if not d or any(d == x or d.endswith("." + x) for x in NON_OWN_DOMAINS):
        return ""
    return d


def normalize_url(url: str | None) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc or " " in p.netloc:
        return ""
    return url


def norm_name(name: str | None) -> str:
    s = (name or "").lower()
    s = re.sub(r"\b(llc|l\.l\.c|fz|fze|fzco|dmcc|est|establishment|co|company|trading|branch|the)\b", " ", s)
    s = re.sub(r"[^a-z0-9؀-ۿ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()
