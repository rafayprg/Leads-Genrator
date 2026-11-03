"""Calling desk (the old LeadsPro, inside this platform): hand out leads city by city, each member's call list,
and the call funnel. Call outcomes are SalesNote rows, so the lead page, My work and Team see the same history.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Business, SalesStatus, User
from . import sales as sales_service

PENDING = "pending"  # no call logged yet
# the order the call desk shows them in; anything older (called, no_answer) still counts
STATUSES = (PENDING, SalesStatus.CONNECTED.value, SalesStatus.NOT_CONNECTED.value, SalesStatus.INTERESTED.value,
            SalesStatus.FOLLOW_UP.value, SalesStatus.NOT_INTERESTED.value, SalesStatus.NOT_ON_WHATSAPP.value,
            SalesStatus.WON.value)
REACHED = {SalesStatus.CONNECTED.value, SalesStatus.CALLED.value, SalesStatus.INTERESTED.value,
           SalesStatus.FOLLOW_UP.value, SalesStatus.NOT_INTERESTED.value, SalesStatus.WON.value}
HOT = {SalesStatus.INTERESTED.value, SalesStatus.FOLLOW_UP.value, SalesStatus.WON.value}


def _filtered(session: Session, country: str | None, industry: str | None):
    stmt = select(Business)
    if country:
        stmt = stmt.where(Business.country == country.upper())
    if industry:
        stmt = stmt.where(Business.industry == industry)
    return session.scalars(stmt).all()


def cities(session: Session, country: str | None = None, industry: str | None = None) -> list[dict]:
    """Per (country, city): how many leads, how many nobody owns, and who owns the rest."""
    names = dict(session.execute(select(User.id, User.name)).all())
    rows: dict[tuple, dict] = {}
    for b in _filtered(session, country, industry):
        key = (b.country or "", b.city or "")
        r = rows.setdefault(key, {"country": key[0], "city": key[1] or "(no city)", "total": 0, "unassigned": 0,
                                  "owners": Counter()})
        r["total"] += 1
        if b.owner_id is None:
            r["unassigned"] += 1
        else:
            r["owners"][b.owner_id] += 1
    out = []
    for r in rows.values():
        out.append({**r, "owners": [{"id": uid, "name": names.get(uid, "?"), "leads": n}
                                    for uid, n in r["owners"].most_common()]})
    return sorted(out, key=lambda r: (r["country"], -r["total"], r["city"]))


def assign_city(session: Session, country: str, city: str, user_id: int | None, industry: str | None = None,
                limit: int | None = None, only_unassigned: bool = True) -> int:
    """Give the leads of one city to one member (best score first), or back to the pool when user_id is None."""
    leads = [b for b in _filtered(session, country, industry) if (b.city or "") == city
             and (not only_unassigned or b.owner_id is None or user_id is None)]
    if user_id is None:
        leads = [b for b in leads if b.owner_id is not None]
    leads.sort(key=lambda b: -(((b.details or {}).get("opportunity") or {}).get("score") or 0))
    now = datetime.now(UTC)
    for b in leads[:limit] if limit else leads:
        b.owner_id, b.assigned_at = user_id, (now if user_id else None)
    session.commit()
    return len(leads[:limit] if limit else leads)


def _status(note: dict | None) -> str:
    return note["status"] if note else PENDING


def call_list(session: Session, user_id: int, status: str | None = None, city: str | None = None) -> dict:
    """One member's leads with the latest call outcome, counts per status, newest-touched last."""
    mine = session.scalars(select(Business).where(Business.owner_id == user_id)).all()
    latest = sales_service.latest_status(session, {b.id for b in mine})
    counts = Counter(_status(latest.get(b.id)) for b in mine)
    cities = sorted({b.city or "" for b in mine})
    items = []
    for b in mine:
        st = _status(latest.get(b.id))
        if (status and st != status) or (city and (b.city or "") != city):
            continue
        opp = (b.details or {}).get("opportunity") or {}
        items.append({"id": b.id, "business_id": b.business_id, "name": b.name, "city": b.city, "area": b.area,
                      "country": b.country, "industry": b.industry, "category": b.category, "phone": b.phone,
                      "whatsapp": ((b.details or {}).get("leadgen") or {}).get("whatsapp") or "",
                      "website": b.website_url, "email": b.email, "maps_url": b.maps_url, "rating": b.rating,
                      "review_count": b.review_count, "score": opp.get("score"), "band": opp.get("band"),
                      "status": st, "last": latest.get(b.id), "assigned_at": b.assigned_at})
    # pending first (best score first), then the rest by when they were last touched
    items.sort(key=lambda x: (x["status"] != PENDING, -(x["score"] or 0) if x["status"] == PENDING else 0,
                              str((x["last"] or {}).get("at") or "")))
    return {"total": len(mine), "counts": {s: counts.get(s, 0) for s in STATUSES} | dict(counts),
            "cities": cities, "items": items}


def funnel(session: Session) -> dict:
    """Pipeline for everything that has an owner: per status, and per member with reach and hot rates."""
    owned = session.scalars(select(Business).where(Business.owner_id.is_not(None))).all()
    latest = sales_service.latest_status(session, {b.id for b in owned})
    total: Counter = Counter()
    per: dict[int, Counter] = defaultdict(Counter)
    for b in owned:
        st = _status(latest.get(b.id))
        total[st] += 1
        per[b.owner_id][st] += 1
    users = {u.id: u for u in session.scalars(select(User).where(User.id.in_(per.keys())))} if per else {}
    members = []
    for uid, c in per.items():
        leads = sum(c.values())
        called = leads - c[PENDING]
        members.append({"id": uid, "name": users[uid].name if uid in users else "?", "leads": leads, "called": called,
                        "reached": sum(c[s] for s in REACHED), "hot": sum(c[s] for s in HOT), "by_status": dict(c),
                        "hot_rate": round(100 * sum(c[s] for s in HOT) / called) if called else None})
    members.sort(key=lambda m: (-m["hot"], -m["called"], m["name"]))
    unowned = session.query(Business).filter(Business.owner_id.is_(None)).count()
    return {"assigned": len(owned), "unassigned": unowned,
            "by_status": {s: total.get(s, 0) for s in STATUSES} | dict(total), "members": members}
