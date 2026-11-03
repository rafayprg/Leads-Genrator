"""Outreach: send audited leads to Harvey on the VPS, and show what Harvey is doing."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .db import get_session
from .harvey import bridge
from .ingest.apify_tokens import write_env
from .ingest.gulf import INDUSTRIES
from .models import Business, Role, User
from .agents.reporting import pitch
from .routes import _AUDITED
from .services.audits import report_inputs
from .security import allow, client_ip, log, require

router = APIRouter()
ADMIN = Depends(require(Role.ADMIN))


class SendIn(BaseModel):
    business_ids: list[int] = Field(min_length=1, max_length=bridge.MAX_BATCH)
    check_only: bool = True


class HarveyConfigIn(BaseModel):
    host: str = Field(min_length=3, max_length=255, pattern=r"^[A-Za-z0-9.\-]+$")
    user: str = Field("root", min_length=1, max_length=32, pattern=r"^[a-z_][a-z0-9_\-]*$")
    key: str = Field("~/.ssh/techdeva_vps", min_length=1, max_length=300)
    folder: str = Field("/opt/harvey", min_length=1, max_length=200, pattern=r"^/[A-Za-z0-9._/\-]+$")
    public_url: str = Field("https://sales.techdeva.net", max_length=300, pattern=r"^https://[^\s]+$")


def _sent(b: Business) -> dict | None:
    return (b.details or {}).get("harvey")


def _row(b: Business, session: Session | None = None) -> dict:
    """One CSV row in Harvey's own column names. Only links we matched with high confidence are passed on.
    With a session, the proposal email's facts come along: two findings the audit saw and one TechDeva line."""
    social = {p.platform: p.profile_url for p in b.social_profiles if str(p.confidence) == "high"}
    row = {"name": b.name, "website": b.website_url, "city": b.city,
           "category": b.category or (INDUSTRIES.get(b.industry or "", {}).get("label") or ""),
           "phone": b.phone, "instagram": social.get("instagram", ""), "facebook": social.get("facebook", ""),
           "email": b.email}
    inp = report_inputs(session, b) if session is not None else None
    if inp is not None:
        row.update(pitch.proposal(inp.profile, inp.dataset, inp.summaries.get("automation_runner") or {}))
    return row


@router.get("/harvey/status")
def harvey_status(fresh: bool = False) -> dict:
    return bridge.status(fresh=fresh)


@router.get("/harvey/candidates")
def candidates(band: str | None = Query(None, max_length=40), min_score: int = Query(0, ge=0, le=100),
               country: str | None = Query(None, max_length=2), show_sent: bool = False,
               limit: int = Query(200, ge=1, le=500), session: Session = Depends(get_session)) -> dict:
    """Audited leads Harvey can work with (they need a website or an email), best score first."""
    stmt = select(Business).where(Business.id.in_(_AUDITED),
                                  or_(Business.website_url.is_not(None), Business.email.is_not(None)))
    if country:
        stmt = stmt.where(Business.country == country.upper())
    items = []
    for b in session.scalars(stmt):
        opp = (b.details or {}).get("opportunity") or {}
        if not (b.website_url or b.email) or (opp.get("score") or 0) < min_score or (band and opp.get("band") != band):
            continue
        if _sent(b) and not show_sent:
            continue
        items.append({"id": b.id, "business_id": b.business_id, "name": b.name, "city": b.city, "country": b.country,
                      "industry": b.industry, "website": b.website_url, "email": b.email,
                      "score": opp.get("score"), "band": opp.get("band"), "sent": _sent(b)})
    items.sort(key=lambda x: -(x["score"] or 0))
    return {"total": len(items), "items": items[:limit],
            "already_sent": sum(1 for b in session.scalars(select(Business).where(Business.id.in_(_AUDITED))) if _sent(b))}


@router.post("/harvey/send")
def send(body: SendIn, request: Request, session: Session = Depends(get_session),
         user: User = Depends(allow("send_to_harvey"))) -> dict:
    """check_only: Harvey reads the batch and says what it would add. Otherwise the leads are imported and
    marked as sent here, so they are never offered again."""
    found = session.scalars(select(Business).options(selectinload(Business.social_profiles))
                            .where(Business.id.in_(body.business_ids), Business.id.in_(_AUDITED))).all()
    usable = [b for b in found if (b.website_url or b.email) and not (_sent(b) and not body.check_only)]
    if not usable:
        raise HTTPException(400, "None of these leads can go to Harvey (not audited, already sent, or no website/email)")
    try:
        report = (bridge.import_rows([_row(b, session) for b in usable], check_only=True) if body.check_only
                  else send_batch(session, usable, user.email, client_ip(request)))
    except bridge.HarveyUnavailable as e:
        raise HTTPException(502, str(e)) from e
    return {**report, "leads": len(usable), "skipped": len(body.business_ids) - len(usable)}


def send_batch(session: Session, usable: list[Business], by: str, ip: str | None = None) -> dict:
    """Import into Harvey, then mark each lead as sent so it is never offered again."""
    report = bridge.import_rows([_row(b, session) for b in usable], check_only=False)
    audited = set(session.scalars(_AUDITED))
    batch = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    for b in usable:
        b.details = {**(b.details or {}), "harvey": {"sent_at": datetime.now(UTC).isoformat(timespec="seconds"),
                                                     "by": by, "batch": batch, "v": SEND_VERSION,
                                                     "audited": b.id in audited}}
    session.commit()
    log(session, by, "sent_to_harvey", f"{len(usable)} leads",
        {"batch": batch, "new": report.get("new"), "already_known": report.get("already_known")}, ip)
    return report


SEND_VERSION = 3  # 2: rows carry the proposal email's facts; 3: one finding per topic


def _needs_send(b: Business, audited: bool) -> bool:
    """Never sent, or sent before its audit (or before rows carried the proposal) and audited now:
    sending it again only refreshes the proposal facts, Harvey already knows the business."""
    sent = _sent(b)
    if not sent:
        return True
    return audited and not (sent.get("v") == SEND_VERSION and sent.get("audited"))


def auto_candidates(session: Session, limit: int) -> list[Business]:
    """Every lead Harvey can work with (a website or an email) that it has not had in its latest form.
    Audited leads go first (their emails can be the proposal), then the best score, then the newest."""
    audited = set(session.scalars(_AUDITED))
    pool = session.scalars(select(Business).options(selectinload(Business.social_profiles))
                           .where(or_(Business.website_url.is_not(None), Business.email.is_not(None))))
    picks = [b for b in pool if (b.website_url or b.email) and _needs_send(b, b.id in audited)]
    picks.sort(key=lambda b: (b.id not in audited,
                              -(((b.details or {}).get("opportunity") or {}).get("score") or 0), -b.id))
    return picks[:limit]


class AutoIn(BaseModel):
    enabled: bool


@router.get("/harvey/auto")
def get_auto(session: Session = Depends(get_session), _: User = ADMIN) -> dict:
    from .services import harvey_auto
    return harvey_auto.get_setting(session)


@router.put("/harvey/auto")
def set_auto(body: AutoIn, request: Request, session: Session = Depends(get_session), admin: User = ADMIN) -> dict:
    from .services import harvey_auto
    out = harvey_auto.set_setting(session, body.enabled, admin.email)
    log(session, admin, "harvey_auto_changed", "on" if body.enabled else "off", ip=client_ip(request))
    return out


@router.get("/settings/harvey")
def harvey_settings(_: User = ADMIN) -> dict:
    cfg = bridge.config()
    return {"host": cfg.host, "user": cfg.user, "key": cfg.key, "folder": cfg.folder, "public_url": cfg.public_url,
            "key_found": Path(cfg.key).is_file(), "ready": cfg.ready}


@router.put("/settings/harvey")
def set_harvey_settings(body: HarveyConfigIn, request: Request, session: Session = Depends(get_session),
                        admin: User = ADMIN) -> dict:
    if not Path(body.key).expanduser().is_file():
        raise HTTPException(400, f"SSH key not found on this computer: {body.key}")
    for name, value in (("HARVEY_SSH_HOST", body.host), ("HARVEY_SSH_USER", body.user), ("HARVEY_SSH_KEY", body.key),
                        ("HARVEY_DIR", body.folder), ("HARVEY_PUBLIC_URL", body.public_url)):
        write_env(name, value)
    log(session, admin, "harvey_settings_changed", body.host, ip=client_ip(request))
    return {**harvey_settings(admin), "status": bridge.status(fresh=True)}
