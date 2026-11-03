"""Team (staff management): members, first-login passwords, lead owners, my work, performance, permissions."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import get_session
from .ingest.gulf import COUNTRIES, INDUSTRIES
from .models import Business, Role, User
from .routes import _AUDITED, _business_query
from .security import (PERMISSIONS, allow, check_password, client_ip, current_user, get_permissions, hash_password, log,
                       password_problem, require, set_permissions)
from .services import team

router = APIRouter()
ADMIN = Depends(require(Role.ADMIN))
PHONE = r"^[0-9+()\- ]{6,40}$"


class MemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    role: Role = Role.SALES
    title: str | None = Field(None, max_length=80)
    phone: str | None = Field(None, pattern=PHONE)
    whatsapp: str | None = Field(None, pattern=PHONE)
    countries: list[str] = Field(default_factory=list, max_length=20)
    industries: list[str] = Field(default_factory=list, max_length=20)
    daily_call_target: int = Field(30, ge=0, le=500)


class MemberPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    role: Role | None = None
    title: str | None = Field(None, max_length=80)
    phone: str | None = Field(None, pattern=PHONE)
    whatsapp: str | None = Field(None, pattern=PHONE)
    countries: list[str] | None = Field(None, max_length=20)
    industries: list[str] | None = Field(None, max_length=20)
    daily_call_target: int | None = Field(None, ge=0, le=500)
    away: bool | None = None
    is_active: bool | None = None
    reset_password: bool = False


class PasswordIn(BaseModel):
    current: str = Field(min_length=1, max_length=200)
    new: str = Field(min_length=1, max_length=200)


class AssignIn(BaseModel):
    business_ids: list[int] = Field(min_length=1, max_length=500)
    user_id: int | None = None


class Share(BaseModel):
    user_id: int
    count: int = Field(ge=0, le=5000)


class DistributeIn(BaseModel):
    """The All Leads filters, plus how many of the matching unassigned leads each member gets."""
    country: list[str] = Field(default_factory=list, max_length=20)
    city: str | None = Field(None, max_length=120)
    industry: str | None = Field(None, max_length=40)
    q: str | None = Field(None, max_length=100)
    audit: Literal["all", "new", "audited"] = "all"
    shares: list[Share] = Field(min_length=1, max_length=50)


class AutoAssignIn(BaseModel):
    audit: Literal["audited", "all"] = "audited"
    limit: int = Field(200, ge=1, le=1000)


def _check_cover(countries: list[str] | None, industries: list[str] | None) -> None:
    if bad := [c for c in countries or [] if c not in COUNTRIES]:
        raise HTTPException(400, f"Unknown countries {bad}")
    if bad := [i for i in industries or [] if i not in INDUSTRIES]:
        raise HTTPException(400, f"Unknown industries {bad}")


def member_out(u: User, owned: int = 0) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": str(u.role), "title": u.title, "phone": u.phone,
            "whatsapp": u.whatsapp, "countries": u.countries or [], "industries": u.industries or [], "away": u.away,
            "daily_call_target": u.daily_call_target, "is_active": u.is_active, "must_change_password": u.must_change_password,
            "created_at": u.created_at, "last_login_at": u.last_login_at, "leads_owned": owned}


def _admins_left(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(User).where(User.role == Role.ADMIN, User.is_active.is_(True))) or 0


# ------------------------------------------------------------------ members
@router.get("/team")
def list_team(session: Session = Depends(get_session), _: User = Depends(current_user)) -> list[dict]:
    """Everyone logged in sees the team (names, roles, who covers what) so leads can be handed over."""
    owned = team.owned_counts(session)
    return [member_out(u, owned.get(u.id, 0)) for u in session.scalars(select(User).order_by(User.is_active.desc(), User.name))]


@router.post("/team", status_code=201)
def add_member(body: MemberIn, request: Request, session: Session = Depends(get_session), admin: User = ADMIN) -> dict:
    email = body.email.lower()
    if session.scalars(select(User).where(User.email == email)).first():
        raise HTTPException(409, "A team member with this email exists")
    _check_cover(body.countries, body.industries)
    pw = team.temp_password()
    u = User(email=email, name=body.name.strip(), role=body.role, password_hash=hash_password(pw), title=body.title,
             phone=body.phone, whatsapp=body.whatsapp, countries=body.countries, industries=body.industries,
             daily_call_target=body.daily_call_target, must_change_password=True)
    session.add(u)
    session.commit()
    log(session, admin, "team_member_added", u.email, {"role": str(u.role)}, client_ip(request))
    return {**member_out(u), "temp_password": pw}  # shown once; the member must change it at first login


@router.patch("/team/{user_id}")
def change_member(user_id: int, body: MemberPatch, request: Request, session: Session = Depends(get_session),
                  admin: User = ADMIN) -> dict:
    u = session.get(User, user_id)
    if u is None:
        raise HTTPException(404, "No such team member")
    if u.role == Role.ADMIN and ((body.role and body.role != Role.ADMIN) or body.is_active is False) and _admins_left(session) <= 1:
        raise HTTPException(400, "Keep at least one active admin")
    _check_cover(body.countries, body.industries)
    changes = body.model_dump(exclude_unset=True, exclude={"reset_password"})
    for k, v in changes.items():
        setattr(u, k, v)
    out = {}
    if body.reset_password:
        pw = team.temp_password()
        u.password_hash, u.must_change_password = hash_password(pw), True
        out["temp_password"] = pw
    if body.is_active is False:  # leads of someone who leaves go back to the pool
        session.query(Business).filter(Business.owner_id == u.id).update({"owner_id": None, "assigned_at": None})
    session.commit()
    log(session, admin, "team_member_changed", u.email,
        {**{k: str(v) for k, v in changes.items()}, **({"password": "reset"} if body.reset_password else {})}, client_ip(request))
    return {**member_out(u, team.owned_counts(session).get(u.id, 0)), **out}


@router.post("/auth/password", status_code=204)
def change_my_password(body: PasswordIn, request: Request, session: Session = Depends(get_session),
                       user: User = Depends(current_user)) -> None:
    if not check_password(body.current, user.password_hash):
        raise HTTPException(400, "The current password is wrong")
    if problem := password_problem(body.new):
        raise HTTPException(400, problem)
    if body.new == body.current:
        raise HTTPException(400, "Pick a new password, not the same one")
    user.password_hash, user.must_change_password = hash_password(body.new), False
    session.commit()
    log(session, user, "password_changed", ip=client_ip(request))


# ------------------------------------------------------------------ permissions
@router.get("/team/permissions")
def read_permissions(session: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    return {"labels": PERMISSIONS, "roles": get_permissions(session)}


@router.put("/team/permissions")
def write_permissions(body: dict, request: Request, session: Session = Depends(get_session), admin: User = ADMIN) -> dict:
    roles = set_permissions(session, body, admin.email)
    log(session, admin, "permissions_changed", None, roles, client_ip(request))
    return {"labels": PERMISSIONS, "roles": roles}


# ------------------------------------------------------------------ lead owners
@router.post("/leads/assign")
def assign_leads(body: AssignIn, request: Request, session: Session = Depends(get_session),
                 user: User = Depends(allow("assign_leads"))) -> dict:
    if body.user_id is not None:
        to = session.get(User, body.user_id)
        if to is None or not to.is_active:
            raise HTTPException(400, "Pick an active team member")
    n = team.assign(session, body.business_ids, body.user_id)
    log(session, user, "leads_assigned", f"{n} leads", {"to": body.user_id}, client_ip(request))
    return {"assigned": n}


@router.post("/leads/distribute")
def distribute(body: DistributeIn, request: Request, session: Session = Depends(get_session),
               user: User = Depends(allow("assign_leads"))) -> dict:
    """Fareed 50, Waleed 30, ...: unassigned leads of the filter, best score first, handed out in that order."""
    shares = [s for s in body.shares if s.count]
    members = {u.id: u for u in session.scalars(select(User).where(User.id.in_([s.user_id for s in shares])))}
    if bad := [s.user_id for s in shares if s.user_id not in members or not members[s.user_id].is_active]:
        raise HTTPException(400, f"Pick active team members (unknown or inactive: {bad})")
    if len({s.user_id for s in shares}) != len(shares):
        raise HTTPException(400, "Each member only once")
    pool = session.scalars(_business_query(body.country, body.city, body.industry, body.q, body.audit, "none")).all()
    pool = sorted(pool, key=lambda b: (-(((b.details or {}).get("opportunity") or {}).get("score") or 0), -b.id))
    given, start = [], 0
    for s in shares:
        batch = [b.id for b in pool[start:start + s.count]]
        start += len(batch)
        if batch:
            team.assign(session, batch, s.user_id)
        given.append({"id": s.user_id, "name": members[s.user_id].name, "asked": s.count, "assigned": len(batch)})
    log(session, user, "leads_distributed", f"{start} leads", {"per_member": given}, client_ip(request))
    return {"available": len(pool), "assigned": start, "per_member": given}


@router.post("/businesses/{business_pk}/take")
def take_lead(business_pk: int, request: Request, session: Session = Depends(get_session),
              user: User = Depends(require(Role.SALES))) -> dict:
    """A salesperson picks a lead nobody owns."""
    b = session.get(Business, business_pk)
    if b is None:
        raise HTTPException(404, "No such business")
    if b.owner_id not in (None, user.id):
        raise HTTPException(409, "Someone else owns this lead; ask an admin to move it")
    team.assign(session, [b.id], user.id)
    log(session, user, "lead_taken", b.business_id, ip=client_ip(request))
    return {"owner_id": user.id}


@router.post("/leads/auto-assign")
def auto_assign(body: AutoAssignIn, request: Request, session: Session = Depends(get_session),
                user: User = Depends(allow("assign_leads"))) -> dict:
    stmt = select(Business).where(Business.owner_id.is_(None))
    if body.audit == "audited":
        stmt = stmt.where(Business.id.in_(_AUDITED))
    leads = sorted(session.scalars(stmt), key=lambda b: -(((b.details or {}).get("opportunity") or {}).get("score") or 0))
    given = team.auto_assign(session, leads[:body.limit])
    names = dict(session.execute(select(User.id, User.name).where(User.id.in_(given))).all()) if given else {}
    log(session, user, "leads_auto_assigned", f"{sum(given.values())} leads", {"per_member": given}, client_ip(request))
    return {"considered": min(len(leads), body.limit), "assigned": sum(given.values()),
            "per_member": [{"id": k, "name": names.get(k, ""), "leads": v} for k, v in given.items()]}


# ------------------------------------------------------------------ my work + performance
@router.get("/me/work")
def my_work(session: Session = Depends(get_session), user: User = Depends(current_user)) -> dict:
    return team.my_work(session, user)


@router.get("/team/performance")
def performance(days: int = 7, session: Session = Depends(get_session),
                _: User = Depends(current_user)) -> dict:
    if days not in (1, 7, 30):
        raise HTTPException(422, "days must be 1, 7 or 30")
    return {"days": days, "members": team.performance(session, days)}
