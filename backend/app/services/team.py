"""Sales team: who owns which lead, auto-assign, each member's day, and team performance."""
from __future__ import annotations

import secrets
import string
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Business, Role, SalesNote, SalesStatus, User
from . import sales as sales_service

SELLERS = (Role.SALES, Role.ADMIN, Role.CALLER)
WARM = {SalesStatus.INTERESTED.value, SalesStatus.FOLLOW_UP.value, SalesStatus.WON.value}


def temp_password() -> str:
    """12 characters, letters and digits (always both), shown once to the admin."""
    abc = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(abc) for _ in range(12))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


def _now() -> datetime:
    return datetime.now(UTC)


def owned_counts(session: Session) -> dict[int, int]:
    return dict(session.execute(select(Business.owner_id, func.count()).where(Business.owner_id.is_not(None))
                                .group_by(Business.owner_id)).all())


def assign(session: Session, business_ids: list[int], user_id: int | None) -> int:
    found = session.scalars(select(Business).where(Business.id.in_(business_ids))).all()
    for b in found:
        b.owner_id, b.assigned_at = user_id, (_now() if user_id else None)
    session.commit()
    return len(found)


def covers(u: User, b: Business) -> bool:
    return (not u.countries or b.country in u.countries) and (not u.industries or b.industry in u.industries)


def auto_assign(session: Session, leads: list[Business]) -> dict[int, int]:
    """Give each lead to an active, not-away salesperson who covers its country and industry; the member with
    the fewest leads gets the next one. Leads nobody covers stay unassigned."""
    members = [u for u in session.scalars(select(User).where(User.is_active.is_(True), User.role == Role.SALES,
                                                           User.away.is_(False)))]
    owned = owned_counts(session)
    load = {u.id: owned.get(u.id, 0) for u in members}
    given: Counter = Counter()
    for b in leads:
        able = [u for u in members if covers(u, b)]
        if not able:
            continue
        pick = min(able, key=lambda u: (load[u.id], u.id))
        b.owner_id, b.assigned_at = pick.id, _now()
        load[pick.id] += 1
        given[pick.id] += 1
    session.commit()
    return dict(given)


def _period_start(days: int) -> datetime:
    """Local midnight (this computer's time zone) `days - 1` days ago, in UTC — "today" means the team's today."""
    local_midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return (local_midnight - timedelta(days=days - 1)).astimezone(UTC)


def performance(session: Session, days: int) -> list[dict]:
    since = _period_start(days)
    today = _period_start(1)
    users = session.scalars(select(User).where(User.role.in_(SELLERS)).order_by(User.name)).all()
    notes = session.scalars(select(SalesNote).where(SalesNote.at >= since)).all()
    per: dict[str, Counter] = defaultdict(Counter)
    today_calls: Counter = Counter()
    for n in notes:
        per[n.by][str(n.status)] += 1
        at = n.at if n.at.tzinfo else n.at.replace(tzinfo=UTC)
        if at >= today:
            today_calls[n.by] += 1
    owned = owned_counts(session)
    due = set(sales_service.follow_ups_due(session))
    owner_of = dict(session.execute(select(Business.id, Business.owner_id).where(Business.id.in_(due))).all()) if due else {}
    out = []
    for u in users:
        c = per.get(u.email, Counter())
        calls = sum(c.values())
        out.append({"id": u.id, "name": u.name, "email": u.email, "role": str(u.role), "active": u.is_active, "away": u.away,
                    "calls": calls, "by_status": dict(c), "warm": sum(c[s] for s in WARM), "won": c[SalesStatus.WON.value],
                    "calls_today": today_calls[u.email], "daily_call_target": u.daily_call_target,
                    "leads_owned": owned.get(u.id, 0),
                    "follow_ups_due": sum(1 for bid in due if owner_of.get(bid) == u.id),
                    "hit_rate": round(100 * sum(c[s] for s in WARM) / calls) if calls else None})
    out.sort(key=lambda r: (-r["won"], -r["warm"], -r["calls"], r["name"]))
    return out


def my_work(session: Session, user: User) -> dict:
    """What one salesperson should do today: follow-ups due, then their best uncalled leads."""
    mine = session.scalars(select(Business).where(Business.owner_id == user.id)).all()
    status = sales_service.latest_status(session, {b.id for b in mine})
    due_ids = set(sales_service.follow_ups_due(session))

    def card(b: Business) -> dict:
        opp = (b.details or {}).get("opportunity") or {}
        return {"id": b.id, "business_id": b.business_id, "name": b.name, "city": b.city, "industry": b.industry,
                "phone": b.phone, "score": opp.get("score"), "band": opp.get("band"), "sales": status.get(b.id),
                "audited": bool(opp)}
    follow_ups = sorted((card(b) for b in mine if b.id in due_ids), key=lambda x: str(x["sales"]["follow_up_on"]))
    to_call = sorted((card(b) for b in mine if b.id not in status), key=lambda x: -(x["score"] or -1))
    in_progress = [card(b) for b in mine if b.id in status and b.id not in due_ids
                   and status[b.id]["status"] not in (SalesStatus.WON.value, SalesStatus.NOT_INTERESTED.value)]
    since_week = _period_start(7)
    my_notes = session.scalars(select(SalesNote).where(SalesNote.by == user.email, SalesNote.at >= since_week)).all()
    today = _period_start(1)
    calls_today = sum(1 for n in my_notes if (n.at if n.at.tzinfo else n.at.replace(tzinfo=UTC)) >= today)
    return {"owned": len(mine), "follow_ups": follow_ups, "to_call": to_call[:50], "to_call_total": len(to_call),
            "in_progress": in_progress[:50], "calls_today": calls_today, "calls_week": len(my_notes),
            "daily_call_target": user.daily_call_target,
            "won_week": sum(1 for n in my_notes if n.status == SalesStatus.WON),
            "next": follow_ups[0] if follow_ups else (to_call[0] if to_call else None), "today": date.today().isoformat()}
