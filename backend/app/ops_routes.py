"""Sales follow-up, stale re-audits, storage clean-up and database backups (all need a login)."""
from __future__ import annotations

import secrets
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_session
from .models import Business, Role, SalesNote, SalesStatus, User
from .routes import _check_daily_audits
from .security import allow, client_ip, current_user, get_limits, log, require
from .services import audits, backup, jobs
from .services import sales as sales_service

router = APIRouter()
ADMIN = Depends(require(Role.ADMIN))
SALES = Depends(require(Role.SALES))


class NoteIn(BaseModel):
    status: SalesStatus
    note: str | None = Field(None, max_length=2000)
    follow_up_on: date | None = None


# ------------------------------------------------------------------ call tracking
def _caller_owns(user: User, b: Business | None) -> None:
    """A caller works only on leads assigned to them."""
    if b is not None and user.role == Role.CALLER and b.owner_id != user.id:
        raise HTTPException(403, "This lead is not assigned to you")


def seller(user: User = Depends(current_user)) -> User:
    if user.role not in (Role.SALES, Role.ADMIN, Role.CALLER):
        raise HTTPException(403, "Needs the sales role")
    return user


@router.get("/businesses/{business_pk}/sales")
def sales_history(business_pk: int, session: Session = Depends(get_session),
                  user: User = Depends(current_user)) -> list[dict]:
    b = session.get(Business, business_pk)
    if b is None:
        raise HTTPException(404, "No such business")
    _caller_owns(user, b)
    notes = session.scalars(select(SalesNote).where(SalesNote.business_id == business_pk).order_by(SalesNote.id.desc()))
    return [sales_service.note_out(n) for n in notes]


@router.post("/businesses/{business_pk}/sales", status_code=201)
def add_sales_note(business_pk: int, body: NoteIn, request: Request, session: Session = Depends(get_session),
                   user: User = Depends(seller)) -> dict:
    b = session.get(Business, business_pk)
    if b is None:
        raise HTTPException(404, "No such business")
    _caller_owns(user, b)
    if body.status == SalesStatus.FOLLOW_UP and body.follow_up_on is None:
        raise HTTPException(400, "Pick a follow-up date")
    n = SalesNote(business_id=business_pk, status=body.status, note=(body.note or "").strip() or None,
                  follow_up_on=body.follow_up_on, by=user.email)
    session.add(n)
    session.commit()
    log(session, user, "sales_note_added", f"BUS id {business_pk}", {"status": str(body.status)}, client_ip(request))
    return sales_service.note_out(n)


@router.get("/sales/summary")
def sales_summary(session: Session = Depends(get_session)) -> dict:
    """Counts per status (newest note per lead) and follow-ups due today or earlier."""
    ids = set(session.scalars(select(SalesNote.business_id).distinct()))
    counts: dict[str, int] = {}
    for n in sales_service.latest_status(session, ids).values():
        counts[n["status"]] = counts.get(n["status"], 0) + 1
    due = sales_service.follow_ups_due(session)
    names = dict(session.execute(select(Business.id, Business.name).where(Business.id.in_(due))).all())
    return {"by_status": counts, "follow_ups_due": [{"business_pk": b, "name": names.get(b, "")} for b in due]}


# ------------------------------------------------------------------ stale audits
@router.get("/audits/stale")
def stale(session: Session = Depends(get_session)) -> dict:
    days = get_limits(session)["audit_stale_days"]
    return {"days": days, "count": len(sales_service.stale_ids(session, days))}


@router.post("/audits/reaudit-stale")
def reaudit_stale(request: Request, session: Session = Depends(get_session), user: User = Depends(allow("start_audits"))) -> dict:
    """Run a fresh full audit for leads whose last full audit is older than the stale limit (oldest first)."""
    limits = get_limits(session)
    last = sales_service.last_full_audit(session)
    ids = sorted(sales_service.stale_ids(session, limits["audit_stale_days"]), key=lambda b: last[b])
    ids = ids[:limits["bulk_audit_max"]]
    if not ids:
        return {"matched": 0, "queued": 0, "run": None}
    _check_daily_audits(session, len(ids))
    run = {"run": f"r{datetime.now(UTC):%Y%m%d%H%M%S}{secrets.token_hex(2)}",
           "run_label": f"Re-audit · {len(ids)} stale lead{'' if len(ids) == 1 else 's'}"}
    created = jobs.create_audit_jobs(session, ids, run, user.email, max_attempts=limits["task_max_attempts"])
    log(session, user, "stale_reaudit_started", f"{len(created)} leads", {"matched": len(ids)}, client_ip(request))
    request.app.state.audit_worker.wake()
    return {"matched": len(ids), "queued": len(created), "run": run["run"]}


# ------------------------------------------------------------------ storage + backups (admin)
@router.get("/settings/storage")
def storage_status(request: Request, session: Session = Depends(get_session), _: User = ADMIN) -> dict:
    old = sales_service.old_report_versions(session)
    db = backup.sqlite_file(session.get_bind())
    keeper = request.app.state.backup
    return {**sales_service.storage(audits.REPORTS_DIR, audits.ARTIFACTS_DIR), "old_report_versions": len(old),
            "backups": backup.list_backups(db) if db else [], "backup_keep": backup.KEEP,
            "backup_error": keeper.last_error, "backups_supported": db is not None}


@router.post("/reports/cleanup")
def cleanup_reports(request: Request, session: Session = Depends(get_session), admin: User = ADMIN) -> dict:
    out = sales_service.remove_old_reports(session, audits.REPORTS_DIR)
    log(session, admin, "old_reports_removed", f"{out['reports_removed']} reports", out, client_ip(request))
    return out


@router.post("/settings/backups", status_code=201)
def backup_now(request: Request, session: Session = Depends(get_session), admin: User = ADMIN) -> dict:
    db = backup.sqlite_file(session.get_bind())
    if db is None:
        raise HTTPException(400, "Backups here are for the SQLite database; PostgreSQL is backed up on the server")
    path = backup.backup_now(db)
    log(session, admin, "backup_made", path.name, ip=client_ip(request))
    return {"name": path.name}
