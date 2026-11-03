"""Phase 1.8: bring the leads already collected by the old tool (leadgen/data/leads.db) into this platform.

The old database is opened READ-ONLY and never changed. By default only callable leads (keep / borderline)
come over; dropped ones (no phone, chains, ...) stay behind unless include_dropped=True.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from . import records
from .apify_maps import StandardRecord
from .gulf import COUNTRIES, INDUSTRIES
from .normalize import format_phone, normalize_url

# Desktop/RE/leadgen next to audit-platform on the laptop; inside the server container that folder does not exist
_UP = Path(__file__).resolve().parents
DEFAULT_DB = (_UP[4] if len(_UP) > 4 else _UP[-1]) / "leadgen" / "data" / "leads.db"
SOURCE_TYPE = "leadgen_import"


@dataclass(frozen=True)
class ImportResult:
    read: int
    skipped_dropped: int
    skipped_invalid: int
    new: int
    updated: int


def _num(v, kind):
    try:
        return kind(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _record(d: dict) -> StandardRecord | None:
    cc = (d.get("country") or "").upper()
    if cc not in COUNTRIES or not (d.get("business_name") or "").strip():
        return None
    phone, kind = format_phone(d.get("phone"), cc)
    try:
        collected = datetime.fromisoformat(d.get("date_collected") or "").replace(tzinfo=UTC)
    except ValueError:
        collected = datetime.now(UTC)
    socials = tuple(s.strip() for s in (d.get("social_links") or "").split(";") if s.strip().startswith("http"))
    industry = d.get("industry") if d.get("industry") in INDUSTRIES else ""
    return StandardRecord(
        name=d["business_name"].strip(), country=cc, city=d.get("city") or "", industry=industry,
        category=d.get("category") or "", area=d.get("area") or "", website_url=normalize_url(d.get("website")),
        phone=phone, phone_type=kind or d.get("phone_type") or "", email=d.get("email") or "",
        maps_url=d.get("google_maps_url") or "", rating=_num(d.get("rating"), float),
        review_count=_num(d.get("review_count"), int), last_review_date=d.get("last_review_date") or "",
        social_links=socials, lat=_num(d.get("_lat"), float), lon=_num(d.get("_lon"), float),
        source_url=d.get("google_maps_url") or f"leadgen:{d.get('lead_id') or 'unknown'}", collected_at=collected,
    )


def run(session: Session, db_path: Path = DEFAULT_DB, include_dropped: bool = False) -> ImportResult:
    if not db_path.exists():
        raise FileNotFoundError(f"old lead database not found: {db_path}")
    con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT data, status FROM leads").fetchall()
    finally:
        con.close()
    recs, extra, dropped, invalid = [], {}, 0, 0
    for raw, status in rows:
        if status == "drop" and not include_dropped:
            dropped += 1
            continue
        d = json.loads(raw)
        r = _record(d)
        if r is None:
            invalid += 1
            continue
        recs.append(r)
        extra[r.place_id or r.phone or r.name] = {"leadgen": {
            "lead_id": d.get("lead_id"), "status": status, "lead_score": d.get("lead_score"),
            "sources": d.get("source"), "whatsapp": d.get("whatsapp"), "decision_maker": d.get("decision_maker"),
            "competitor_found": d.get("competitor_found"), "website_status": d.get("website_status"),
        }}
    saved = records.save(session, recs, source="leadgen_import", source_type=SOURCE_TYPE,
                         method="import_from_leadgen", extra_details=extra)
    return ImportResult(len(rows), dropped, invalid + len(saved.rejected), saved.new, saved.updated)
