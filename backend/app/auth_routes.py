"""Login, first-time setup, users (admin), limits and the activity log."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import load_settings
from .db import get_session
from .models import ActivityLog, Role, User
from .security import (COOKIE, SESSION_HOURS, check_password, clear_failures, client_ip, current_user, end_session,
                       get_limits, hash_password, log, note_failure, password_problem, require, set_limits,
                       start_session, throttled)

router = APIRouter()
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class SetupIn(LoginIn):
    name: str = Field(min_length=1, max_length=120)


class UserIn(SetupIn):
    role: Role = Role.SALES


class UserPatch(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    must_change_password: bool = False


def _set_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True, samesite="strict",
                    secure=load_settings().cookie_secure, path="/")  # COOKIE_SECURE=1 once served over HTTPS


def _no_users(session: Session) -> bool:
    return (session.scalar(select(func.count()).select_from(User)) or 0) == 0


@router.get("/auth/status")
def auth_status(session: Session = Depends(get_session)) -> dict:
    return {"needs_setup": _no_users(session)}


@router.post("/auth/setup", response_model=UserOut, status_code=201)
def setup(body: SetupIn, request: Request, response: Response, session: Session = Depends(get_session)):
    """Create the very first admin. Refused once any user exists."""
    if not _no_users(session):
        raise HTTPException(409, "Setup is already done; log in instead")
    if problem := password_problem(body.password):
        raise HTTPException(400, problem)
    user = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password), role=Role.ADMIN)
    session.add(user)
    session.commit()
    _set_cookie(response, start_session(session, user, client_ip(request)))
    log(session, user, "setup_first_admin", user.email, ip=client_ip(request))
    return user


@router.post("/auth/login", response_model=UserOut)
def login(body: LoginIn, request: Request, response: Response, session: Session = Depends(get_session)):
    key = f"{client_ip(request)}|{body.email.lower()}"
    if throttled(key):
        raise HTTPException(429, "Too many wrong tries. Wait 15 minutes and try again.")
    user = session.scalars(select(User).where(User.email == body.email.lower())).first()
    if user is None or not user.is_active or not check_password(body.password, user.password_hash):
        note_failure(key)
        log(session, body.email.lower(), "login_failed", ip=client_ip(request))
        raise HTTPException(401, "Wrong email or password")
    clear_failures(key)
    _set_cookie(response, start_session(session, user, client_ip(request)))
    log(session, user, "login", ip=client_ip(request))
    return user


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, session: Session = Depends(get_session)) -> None:
    end_session(session, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


# ------------------------------------------------------------------ users (admin)
@router.get("/users", response_model=list[UserOut])
def list_users(session: Session = Depends(get_session), _: User = Depends(require(Role.ADMIN))):
    return session.scalars(select(User).order_by(User.id)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def add_user(body: UserIn, request: Request, session: Session = Depends(get_session),
             admin: User = Depends(require(Role.ADMIN))):
    if session.scalars(select(User).where(User.email == body.email.lower())).first():
        raise HTTPException(409, "A user with this email exists")
    if problem := password_problem(body.password):
        raise HTTPException(400, problem)
    user = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password), role=body.role)
    session.add(user)
    session.commit()
    log(session, admin, "user_added", user.email, {"role": str(user.role)}, client_ip(request))
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def change_user(user_id: int, body: UserPatch, request: Request, session: Session = Depends(get_session),
                admin: User = Depends(require(Role.ADMIN))):
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "No such user")
    losing_admin = user.role == Role.ADMIN and ((body.role and body.role != Role.ADMIN) or body.is_active is False)
    if losing_admin:
        admins = session.scalar(select(func.count()).select_from(User).where(User.role == Role.ADMIN,
                                                                             User.is_active.is_(True)))
        if admins <= 1:
            raise HTTPException(400, "Keep at least one active admin")
    changes = {}
    if body.role is not None:
        user.role, changes["role"] = body.role, str(body.role)
    if body.is_active is not None:
        user.is_active, changes["is_active"] = body.is_active, body.is_active
    if body.password:
        if problem := password_problem(body.password):
            raise HTTPException(400, problem)
        user.password_hash, changes["password"] = hash_password(body.password), "changed"
    session.commit()
    log(session, admin, "user_changed", user.email, changes, client_ip(request))
    return user


# ------------------------------------------------------------------ limits + activity
@router.get("/settings/limits")
def read_limits(session: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    return get_limits(session)


@router.put("/settings/limits")
def write_limits(body: dict, request: Request, session: Session = Depends(get_session),
                 admin: User = Depends(require(Role.ADMIN))) -> dict:
    before = get_limits(session)
    after = set_limits(session, body, admin.email)
    log(session, admin, "limits_changed", None, {k: [before[k], after[k]] for k in body if before[k] != after[k]},
        client_ip(request))
    return after


@router.get("/activity")
def activity(limit: int = Query(100, ge=1, le=1000), action: str | None = None, user_email: str | None = None,
             session: Session = Depends(get_session), _: User = Depends(require(Role.ADMIN))) -> list[dict]:
    stmt = select(ActivityLog).order_by(ActivityLog.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(ActivityLog.action == action)
    if user_email:
        stmt = stmt.where(ActivityLog.user_email == user_email.lower())
    return [{"id": a.id, "at": a.at, "user": a.user_email, "action": a.action, "target": a.target,
             "detail": a.detail, "ip": a.ip} for a in session.scalars(stmt)]
