"""Calling desk API (the old LeadsPro): city-wise assignment, call lists, funnel, and the team PIN login."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth_routes import UserOut, _set_cookie
from .db import get_session
from .models import Role, User
from .security import (allow, check_password, clear_failures, client_ip, current_user, hash_password, log,
                       note_failure, require, start_session, throttled)
from .services import calling

router = APIRouter()
PIN = re.compile(r"^\d{4,8}$")


class AssignCityIn(BaseModel):
    country: str = Field(min_length=2, max_length=2)
    city: str = Field(max_length=120)
    user_id: int | None = None          # None = back to the pool
    industry: str | None = Field(None, max_length=40)
    limit: int | None = Field(None, ge=1, le=5000)
    only_unassigned: bool = True


class PinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=8)


class PinLoginIn(BaseModel):
    user_id: int
    pin: str = Field(min_length=1, max_length=8)


# ------------------------------------------------------------------ team PIN login (public)
@router.get("/auth/team")
def team_for_login(session: Session = Depends(get_session)) -> list[dict]:
    """Names on the login page's Team tab: active members that have a PIN. Never the PIN itself."""
    users = session.scalars(select(User).where(User.is_active.is_(True), User.pin_hash.is_not(None))
                            .order_by(User.name)).all()
    return [{"id": u.id, "name": u.name} for u in users]


@router.post("/auth/pin-login", response_model=UserOut)
def pin_login(body: PinLoginIn, request: Request, response: Response, session: Session = Depends(get_session)):
    key = f"{client_ip(request)}|pin|{body.user_id}"
    if throttled(key):
        raise HTTPException(429, "Too many wrong tries. Wait 15 minutes and try again.")
    user = session.get(User, body.user_id)
    if user is None or not user.is_active or not user.pin_hash or not check_password(body.pin, user.pin_hash):
        note_failure(key)
        log(session, user.email if user else f"user {body.user_id}", "pin_login_failed", ip=client_ip(request))
        raise HTTPException(401, "Wrong PIN")
    clear_failures(key)
    _set_cookie(response, start_session(session, user, client_ip(request)))
    log(session, user, "pin_login", ip=client_ip(request))
    return user


@router.put("/team/{user_id}/pin", status_code=204)
def set_pin(user_id: int, body: PinIn, request: Request, session: Session = Depends(get_session),
            admin: User = Depends(require(Role.ADMIN))) -> None:
    if not PIN.fullmatch(body.pin):
        raise HTTPException(400, "PIN must be 4 to 8 digits")
    u = session.get(User, user_id)
    if u is None:
        raise HTTPException(404, "No such team member")
    # a PIN login replaces the temporary password, so the first-login password step is not needed any more
    u.pin_hash, u.must_change_password = hash_password(body.pin), False
    session.commit()
    log(session, admin, "team_pin_set", u.email, ip=client_ip(request))


@router.delete("/team/{user_id}/pin", status_code=204)
def remove_pin(user_id: int, request: Request, session: Session = Depends(get_session),
               admin: User = Depends(require(Role.ADMIN))) -> None:
    u = session.get(User, user_id)
    if u is None:
        raise HTTPException(404, "No such team member")
    u.pin_hash = None
    session.commit()
    log(session, admin, "team_pin_removed", u.email, ip=client_ip(request))


# ------------------------------------------------------------------ calling desk (logged in)
@router.get("/calling/cities")
def cities(country: str | None = Query(None, max_length=2), industry: str | None = Query(None, max_length=40),
           session: Session = Depends(get_session), _: User = Depends(current_user)) -> list[dict]:
    return calling.cities(session, country, industry)


@router.post("/calling/assign-city")
def assign_city(body: AssignCityIn, request: Request, session: Session = Depends(get_session),
                user: User = Depends(allow("assign_leads"))) -> dict:
    if body.user_id is not None:
        to = session.get(User, body.user_id)
        if to is None or not to.is_active:
            raise HTTPException(400, "Pick an active team member")
    n = calling.assign_city(session, body.country.upper(), body.city, body.user_id, body.industry, body.limit,
                            body.only_unassigned)
    log(session, user, "city_assigned", f"{body.city}: {n} leads", {"to": body.user_id, "industry": body.industry},
        client_ip(request))
    return {"assigned": n}


@router.get("/calling/list")
def call_list(user_id: int | None = None, status: str | None = Query(None, max_length=32),
              city: str | None = Query(None, max_length=120), session: Session = Depends(get_session),
              user: User = Depends(current_user)) -> dict:
    """Your own call list; an admin may look at anyone's."""
    who = user.id
    if user_id is not None and user_id != user.id:
        if user.role != Role.ADMIN:
            raise HTTPException(403, "Only an admin can see another member's list")
        who = user_id
    return calling.call_list(session, who, status, city)


@router.get("/calling/funnel")
def funnel(session: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    return calling.funnel(session)
