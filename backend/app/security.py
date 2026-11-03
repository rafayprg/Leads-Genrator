"""Phase 9.1–9.3: passwords, login sessions, roles, login throttling, activity log, limits.

- Passwords: scrypt (Python standard library), random salt, constant-time compare.
- Sessions: random token in an HttpOnly, SameSite=Strict cookie; only its SHA-256 is stored; 12 h life.
- Roles: admin > sales > viewer.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .db import get_session
from .models import ActivityLog, AppSetting, Role, User, UserSession

COOKIE = "td_session"
SESSION_HOURS = 12
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
MIN_PASSWORD = 10
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5
RANK = {Role.CALLER: 0, Role.VIEWER: 0, Role.SALES: 1, Role.ADMIN: 2}

DEFAULT_LIMITS = {
    "apify_monthly_cap_usd": 20.0,     # all searches together, per calendar month
    "apify_max_per_search_usd": 10.0,
    "bulk_audit_max": 50,              # leads per "Full audit for these leads" click
    "audits_per_day_max": 300,         # audit jobs created per day, all users
    "website_max_pages": 8,            # pages Agent 1 inspects per site
    "website_max_links": 25,           # internal links Agent 1 tests per site
    "task_max_attempts": 3,
    "task_stuck_minutes": 10,          # Agent Monitor flags a task running longer than this
    "ai_calls_per_day_max": 150,       # protects the Gemini/Groq free tier
    "audit_stale_days": 30,            # an audit older than this is shown as stale and can be re-run
}
LIMIT_BOUNDS = {
    "apify_monthly_cap_usd": (0, 1000), "apify_max_per_search_usd": (0.5, 200), "bulk_audit_max": (1, 200),
    "audits_per_day_max": (1, 5000), "website_max_pages": (1, 20), "website_max_links": (0, 100),
    "task_max_attempts": (1, 5), "task_stuck_minutes": (1, 120), "ai_calls_per_day_max": (0, 5000),
    "audit_stale_days": (1, 365),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return "scrypt${}${}${}${}${}".format(SCRYPT["n"], SCRYPT["r"], SCRYPT["p"],
                                         base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(got, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str:
    if len(password) < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters"
    if password.isdigit() or password.isalpha():
        return "Use letters and numbers (or symbols) together"
    return ""


# ------------------------------------------------------------------ login throttling (per IP + email)
_failures: dict[str, list[float]] = {}
_lock = threading.Lock()


def throttled(key: str) -> bool:
    with _lock:
        recent = [t for t in _failures.get(key, []) if time.time() - t < LOGIN_WINDOW_SECONDS]
        _failures[key] = recent
        return len(recent) >= LOGIN_MAX_FAILURES


def note_failure(key: str) -> None:
    with _lock:
        _failures.setdefault(key, []).append(time.time())


def clear_failures(key: str) -> None:
    with _lock:
        _failures.pop(key, None)


# ------------------------------------------------------------------ sessions
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(session: Session, user: User, ip: str | None) -> str:
    token = secrets.token_urlsafe(32)
    session.execute(delete(UserSession).where(UserSession.expires_at < _now()))
    session.add(UserSession(token_hash=_hash(token), user_id=user.id, ip=ip,
                            expires_at=_now() + timedelta(hours=SESSION_HOURS)))
    user.last_login_at = _now()
    session.commit()
    return token


def end_session(session: Session, token: str | None) -> None:
    if token:
        session.execute(delete(UserSession).where(UserSession.token_hash == _hash(token)))
        session.commit()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


FIRST_LOGIN_PATHS = {"/auth/me", "/auth/password", "/auth/logout"}  # all a member may do before a new password
# a caller (calling desk only) may use nothing but these routes; own-lead checks are in the routes themselves
CALLER_ROUTES = FIRST_LOGIN_PATHS | {"/calling/list", "/businesses/{business_pk}/sales"}


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please log in")
    row = session.scalars(select(UserSession).where(UserSession.token_hash == _hash(token))).first()
    if row is None or _aware(row.expires_at) < _now() or not row.user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again")
    if row.user.must_change_password and request.url.path not in FIRST_LOGIN_PATHS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Change your temporary password first")
    route = request.scope.get("route")
    if row.user.role == Role.CALLER and getattr(route, "path", request.url.path) not in CALLER_ROUTES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Callers only have the calling desk")
    return row.user


def require(role: Role) -> Callable[..., User]:
    def dep(user: User = Depends(current_user)) -> User:
        if RANK[user.role] < RANK[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Needs the {role} role")
        return user
    return dep


# ------------------------------------------------------------------ activity log
def log(session: Session, user: User | str | None, action: str, target: str | None = None,
        detail: dict | None = None, ip: str | None = None, commit: bool = True) -> None:
    email = user.email if isinstance(user, User) else user
    session.add(ActivityLog(user_email=email, action=action, target=target, detail=detail or {}, ip=ip))
    if commit:
        session.commit()


# ------------------------------------------------------------------ limits
def get_limits(session: Session) -> dict:
    row = session.get(AppSetting, "limits")
    return {**DEFAULT_LIMITS, **((row.value or {}) if row else {})}


def set_limits(session: Session, changes: dict, by: str) -> dict:
    current = get_limits(session)
    for k, v in changes.items():
        if k not in DEFAULT_LIMITS:
            raise HTTPException(400, f"Unknown limit {k}")
        lo, hi = LIMIT_BOUNDS[k]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not lo <= v <= hi:
            raise HTTPException(400, f"{k} must be a number between {lo} and {hi}")
        current[k] = type(DEFAULT_LIMITS[k])(v)
    row = session.get(AppSetting, "limits") or AppSetting(key="limits")
    row.value, row.updated_by = current, by
    session.add(row)
    session.commit()
    return current


# ------------------------------------------------------------------ permissions per role (admin can do everything)
PERMISSIONS = {
    "export": "Download lead lists and the sales sheet",
    "start_audits": "Start audits (single, bulk, re-audit) — free, reads websites",
    "send_to_harvey": "Send audited leads to Harvey for cold email",
    "assign_leads": "Assign leads to team members",
}
DEFAULT_PERMISSIONS = {
    Role.SALES.value: {"export": True, "start_audits": True, "send_to_harvey": True, "assign_leads": False},
    Role.VIEWER.value: dict.fromkeys(PERMISSIONS, False),
}


def get_permissions(session: Session) -> dict:
    row = session.get(AppSetting, "permissions")
    saved = (row.value or {}) if row else {}
    return {role: {**perms, **{k: v for k, v in (saved.get(role) or {}).items() if k in PERMISSIONS}}
            for role, perms in DEFAULT_PERMISSIONS.items()}


def set_permissions(session: Session, changes: dict, by: str) -> dict:
    current = get_permissions(session)
    for role, perms in changes.items():
        if role not in current or not isinstance(perms, dict):
            raise HTTPException(400, f"Unknown role {role}")
        for k, v in perms.items():
            if k not in PERMISSIONS or not isinstance(v, bool):
                raise HTTPException(400, f"Unknown permission {k}")
            current[role][k] = v
    row = session.get(AppSetting, "permissions") or AppSetting(key="permissions")
    row.value, row.updated_by = current, by
    session.add(row)
    session.commit()
    return current


def allow(action: str) -> Callable[..., User]:
    """Admins always; other roles only when Settings → Team → Permissions turns the action on."""
    if action not in PERMISSIONS:
        raise ValueError(action)

    def dep(user: User = Depends(current_user), session: Session = Depends(get_session)) -> User:
        if user.role == Role.ADMIN or get_permissions(session).get(str(user.role), {}).get(action):
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            f"Your role ({user.role}) may not: {PERMISSIONS[action].lower()}. An admin can allow it in Team.")
    return dep
