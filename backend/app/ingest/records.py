"""Validate, de-duplicate and save collected records as businesses + per-field provenance."""
from __future__ import annotations

import math
from dataclasses import dataclass, fields, replace

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Business, Confidence, DataSource, SocialProfile, Verification
from .apify_maps import SOURCE_TYPE, StandardRecord
from .normalize import norm_name, own_domain

SAME_PLACE_METRES = 300
# record field -> businesses column; every one gets a DataSource row when present
PROVENANCE_FIELDS = {
    "name": "name", "category": "category", "website_url": "website_url", "phone": "phone", "email": "email",
    "maps_url": "maps_url", "rating": "rating", "review_count": "review_count", "city": "city", "area": "area",
}


@dataclass(frozen=True)
class SaveResult:
    new: int
    updated: int
    rejected: tuple[tuple[str, str], ...]  # (name, reason)
    business_ids: tuple[int, ...]


def problems(r: StandardRecord) -> list[str]:
    """Basic validation from the architecture doc, step 4. Empty list = usable."""
    out = []
    if not r.name.strip():
        out.append("missing business name")
    if not r.phone and not r.website_url:
        out.append("no valid phone and no website")
    if r.phone and not r.phone.startswith("+"):
        out.append("phone not in E.164")
    if not r.source_url and not r.place_id:
        out.append("no source reference")
    return out


def _distance_m(a: StandardRecord, b: StandardRecord) -> float:
    if None in (a.lat, a.lon, b.lat, b.lon):
        return math.inf
    dy = (a.lat - b.lat) * 111_000
    dx = (a.lon - b.lon) * 111_000 * math.cos(math.radians(a.lat))
    return math.hypot(dx, dy)


def _merge(base: StandardRecord, other: StandardRecord) -> StandardRecord:
    """Fill empty fields of base from other; never overwrite what base already has."""
    changes = {}
    for f in fields(StandardRecord):
        mine, theirs = getattr(base, f.name), getattr(other, f.name)
        if mine in (None, "", ()) and theirs not in (None, "", ()):
            changes[f.name] = theirs
    changes["social_links"] = tuple(dict.fromkeys(base.social_links + other.social_links))
    return replace(base, **changes)


def dedupe(records: list[StandardRecord]) -> list[StandardRecord]:
    """Same place id, same phone, same own website, or same name within 300 m = one business."""
    parent = list(range(len(records)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen: dict[str, int] = {}
    for i, r in enumerate(records):
        for key in (f"pid:{r.place_id}" if r.place_id else "", f"ph:{r.phone}" if r.phone else "",
                    f"web:{own_domain(r.website_url)}" if own_domain(r.website_url) else ""):
            if not key:
                continue
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i
    by_name: dict[str, list[int]] = {}
    for i, r in enumerate(records):
        by_name.setdefault(norm_name(r.name), []).append(i)
    for idxs in by_name.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                if _distance_m(records[idxs[a]], records[idxs[b]]) < SAME_PLACE_METRES:
                    parent[find(idxs[a])] = find(idxs[b])

    groups: dict[int, list[int]] = {}
    for i in range(len(records)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for idxs in groups.values():
        merged = records[idxs[0]]
        for i in idxs[1:]:
            merged = _merge(merged, records[i])
        out.append(merged)
    return out


def _platform(url: str) -> str:
    d = own_domain(url) or url.lower()
    for name in ("instagram", "facebook", "linkedin", "tiktok", "youtube", "twitter", "x.com"):
        if name in d:
            return "x" if name in ("twitter", "x.com") else name
    return "other"


def _existing(session: Session, r: StandardRecord) -> Business | None:
    conds = []
    if r.place_id:
        conds.append(Business.place_id == r.place_id)
    if r.phone:
        conds.append(Business.phone == r.phone)
    if not conds and not own_domain(r.website_url):
        return None
    if conds:
        hit = session.scalars(select(Business).where(or_(*conds)).limit(1)).first()
        if hit:
            return hit
    d = own_domain(r.website_url)
    if d:
        for b in session.scalars(select(Business).where(Business.website_url.like(f"%{d}%"))):
            if own_domain(b.website_url) == d:
                return b
    return None


def save(session: Session, records: list[StandardRecord], *, source: str = "apify_maps",
         source_type: str = SOURCE_TYPE, method: str = "actor_run",
         extra_details: dict[str, dict] | None = None) -> SaveResult:
    """Validate -> de-duplicate -> insert or fill-in businesses, with one DataSource row per field.

    extra_details: optional {place_id or phone or name: dict} merged into Business.details (used by imports).
    """
    rejected = []
    good = []
    for r in records:
        why = problems(r)
        if why:
            rejected.append((r.name or "(no name)", "; ".join(why)))
        else:
            good.append(r)
    new = updated = 0
    ids: list[int] = []
    for r in dedupe(good):
        b = _existing(session, r)
        is_new = b is None
        if is_new:
            b = Business(name=r.name, country=r.country, source=source, industry=r.industry,
                         verification_status=Verification.PENDING)
            session.add(b)
            new += 1
        else:
            updated += 1
        changed = []
        for rec_field, col in PROVENANCE_FIELDS.items():
            value = getattr(r, rec_field)
            if value in (None, "") or (not is_new and getattr(b, col) not in (None, "")):
                continue
            setattr(b, col, value)
            changed.append(col)
        if r.place_id and not b.place_id:
            b.place_id = r.place_id
        extra = {"phone_type": r.phone_type, "last_review_date": r.last_review_date,
                 "opening_hours": list(r.opening_hours), "lat": r.lat, "lon": r.lon,
                 "temporarily_closed": r.temporarily_closed}
        more = (extra_details or {}).get(r.place_id or r.phone or r.name, {})
        b.details = {**(b.details or {}), **{k: v for k, v in {**extra, **more}.items() if v not in (None, "", [])}}
        session.flush()
        known = {p.profile_url for p in b.social_profiles}
        for url in r.social_links:
            if url not in known:
                # only a candidate: Agent 3 decides whether it is the official account
                b.social_profiles.append(SocialProfile(
                    platform=_platform(url), profile_url=url, verification_status=Verification.UNVERIFIED,
                    confidence=Confidence.LOW, evidence=[f"found by {source_type}"]))
        for col in changed:
            # collected, not checked: website verification is Agent 1's job, social is Agent 3's
            b.data_sources.append(DataSource(field=col, source_type=source_type, source_url=r.source_url or None,
                                             collection_method=method, collected_at=r.collected_at,
                                             verification_status=Verification.UNVERIFIED))
        ids.append(b.id)
    session.commit()
    return SaveResult(new, updated, tuple(rejected), tuple(dict.fromkeys(ids)))
