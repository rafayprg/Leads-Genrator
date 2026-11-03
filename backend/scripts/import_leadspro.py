"""One-time move of LeadsPro (OmniFlow CRM) leads into this platform's database.

Input: a JSON export of LeadsPro's R2 data ({"leads": [...], "agents": [...]}, PINs left out).
    python scripts/import_leadspro.py /path/leadspro-export.json [--dry-run]
Each lead becomes (or matches, by phone / website) a business; its owner is the team member with the same
name as the LeadsPro agent (only active members; others' leads stay in the pool), and a call status other
than "Pending" becomes one call note. Running it again adds nothing new for leads already imported.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import SessionLocal  # noqa: E402
from app.ingest.apify_maps import StandardRecord  # noqa: E402
from app.ingest.gulf import COUNTRIES  # noqa: E402
from app.ingest.normalize import format_phone, normalize_url  # noqa: E402
from app.ingest.records import save  # noqa: E402
from app.models import Business, SalesNote, SalesStatus, User  # noqa: E402

SOURCE = "leadspro"
LOCAL_TZ = ZoneInfo("Asia/Karachi")  # LeadsPro wrote times in the team's local clock
STATUS = {"Connected": SalesStatus.CONNECTED, "Not Connected": SalesStatus.NOT_CONNECTED,
          "Interested": SalesStatus.INTERESTED, "Not Interested": SalesStatus.NOT_INTERESTED,
          "Not on WhatsApp": SalesStatus.NOT_ON_WHATSAPP}
INDUSTRY_WORDS = [("digital marketing", "digital_marketing"), ("marketing agenc", "digital_marketing"),
                  ("salon", "beauty"), ("beauty", "beauty"), ("spa", "beauty"), ("clinic", "clinics"),
                  ("dental", "clinics"), ("gym", "fitness"), ("fitness", "fitness"), ("academ", "academies"),
                  ("institute", "academies"), ("restaurant", "restaurants"), ("cafe", "restaurants"),
                  ("real estate", "real_estate"), ("driving school", "driving_schools")]
AUTO_NOTE = re.compile(r"Imported with .*?preserved\.|Assigned (to \S+ )?on [\d-]+ [\d:]+ ?[AP]?M?|"
                       r"Directly entered by team member\.|Imported from raw data upload\.")


def country_code(name: str) -> str:
    name = (name or "Pakistan").strip()
    return next((cc for cc, c in COUNTRIES.items() if c["name"].lower() == name.lower() or cc == name.upper()), "PK")


def industry_of(category: str) -> str:
    low = (category or "").lower()
    return next((key for word, key in INDUSTRY_WORDS if word in low), "")


def when(text: str | None) -> datetime | None:
    for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime((text or "").strip(), fmt).replace(tzinfo=LOCAL_TZ).astimezone(UTC)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat((text or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def clean_note(text: str | None) -> str:
    return " ".join(p.strip() for p in AUTO_NOTE.sub("", text or "").split("•") if p.strip())


def record(lead: dict) -> StandardRecord:
    cc = country_code(lead.get("country"))
    phone, kind = format_phone(lead.get("phone"), cc)
    socials = tuple(v for v in (lead.get(k) for k in ("instagram", "facebook", "linkedin", "tiktok", "youtube", "twitter")) if v)
    return StandardRecord(
        # cut to the column sizes in app/models.py (PostgreSQL refuses longer text; SQLite does not check)
        name=(lead.get("name") or "").strip()[:300], country=cc, city=(lead.get("city") or "").strip()[:80],
        industry=industry_of(lead.get("category") or lead.get("industry")), category=(lead.get("category") or "")[:120],
        area=(lead.get("address") or "")[:120], website_url=normalize_url(lead.get("website")), phone=phone,
        phone_type=kind, email=(lead.get("email") or "").strip(), rating=lead.get("rating"),
        review_count=lead.get("reviewCount"), social_links=socials, source_url=f"leadspro://{lead.get('id')}")


def main(path: str, dry_run: bool) -> None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    with SessionLocal() as session:
        users = {u.name.strip().lower(): u for u in session.scalars(select(User).where(User.is_active.is_(True)))}
        done = {"new": 0, "matched": 0, "rejected": 0, "owned": 0, "notes": 0, "pool": 0}
        for lead in data["leads"]:
            rec = record(lead)
            if dry_run:
                continue
            r = save(session, [rec], source=SOURCE, source_type="leadspro_import", method="import")
            if not r.business_ids:
                done["rejected"] += 1
                print(f"skipped {rec.name!r}: {r.rejected[0][1] if r.rejected else 'unknown'}")
                continue
            done["new" if r.new else "matched"] += 1
            b = session.get(Business, r.business_ids[0])
            agent = (lead.get("assignedAgent") or "").strip().lower()
            owner = users.get(agent) or next((u for n, u in users.items() if agent and n.split()[0] == agent), None)
            if owner and b.owner_id is None:
                b.owner_id, b.assigned_at = owner.id, when(lead.get("assignedDate")) or datetime.now(UTC)
                done["owned"] += 1
            elif agent and not owner:
                done["pool"] += 1
            status = STATUS.get(lead.get("status") or "")
            already = session.scalar(select(func.count()).select_from(SalesNote).where(
                SalesNote.business_id == b.id, SalesNote.note.like("LeadsPro%")))
            if status and not already:
                note = clean_note(lead.get("notes"))
                session.add(SalesNote(business_id=b.id, status=status, by=owner.email if owner else "leadspro import",
                                      note=f"LeadsPro: {note}" if note else "LeadsPro import",
                                      at=when(lead.get("lastContactDate")) or datetime.now(UTC)))
                done["notes"] += 1
            session.commit()
    print("dry run, nothing saved" if dry_run else done)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    main(a.path, a.dry_run)
