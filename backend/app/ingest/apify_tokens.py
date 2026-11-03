"""Apify tokens: real credit per account, masked display, save/remove in backend/.env.

Ported from leadgen/leadgen/keys.py. Tokens go only in the Authorization header, never in a URL,
and are never returned to the browser in full.
"""
from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict, dataclass

import requests

from ..config import ENV_FILE, load_settings

APIFY_API = "https://api.apify.com/v2"
STATUS_CACHE_SECONDS = 60
LOW_CREDIT_USD = 0.05


@dataclass(frozen=True)
class TokenStatus:
    key: str           # masked, e.g. "…a1b2"
    last4: str
    ok: bool
    message: str
    username: str = ""
    plan: str = ""
    limit_usd: float | None = None
    used_usd: float | None = None
    remaining_usd: float | None = None
    cycle_ends: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def mask(token: str) -> str:
    return f"…{token[-4:]}" if token else ""


def tokens() -> tuple[str, ...]:
    return load_settings().apify_tokens


def apify_get(token: str, path: str, timeout: int = 20) -> requests.Response:
    return requests.get(APIFY_API + path, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)


def apify_post(token: str, path: str, **kw) -> requests.Response:
    return requests.post(APIFY_API + path, headers={"Authorization": f"Bearer {token}"}, timeout=30, **kw)


_cache: dict[str, tuple[float, TokenStatus]] = {}


def status(token: str, fresh: bool = False) -> TokenStatus:
    """Real plan, used and remaining USD for one token (cached 60 s unless fresh)."""
    hit = _cache.get(token)
    if hit and not fresh and time.time() - hit[0] < STATUS_CACHE_SECONDS:
        return hit[1]
    base = {"key": mask(token), "last4": token[-4:]}
    try:
        lim = apify_get(token, "/users/me/limits")
        if lim.status_code in (401, 403):
            result = TokenStatus(**base, ok=False, message="Invalid token")
        elif lim.status_code != 200:
            result = TokenStatus(**base, ok=False, message=f"HTTP {lim.status_code}")
        else:
            d = lim.json().get("data", {})
            limit = float(d.get("limits", {}).get("maxMonthlyUsageUsd") or 0)
            used = float(d.get("current", {}).get("monthlyUsageUsd") or 0)
            remaining = round(max(0.0, limit - used), 3)
            username = plan = ""
            me = apify_get(token, "/users/me")
            if me.status_code == 200:
                u = me.json().get("data", {})
                username, plan = u.get("username", ""), (u.get("plan") or {}).get("id", "")
            result = TokenStatus(**base, ok=True,
                                 message="OK" if remaining > LOW_CREDIT_USD else "No credit left this month",
                                 username=username, plan=plan, limit_usd=round(limit, 2), used_usd=round(used, 3),
                                 remaining_usd=remaining,
                                 cycle_ends=(d.get("monthlyUsageCycle", {}).get("endAt") or "")[:10])
    except requests.RequestException as e:
        result = TokenStatus(**base, ok=False, message=f"Network error: {type(e).__name__}")
    _cache[token] = (time.time(), result)
    return result


def all_status(fresh: bool = False) -> list[TokenStatus]:
    return [status(t, fresh) for t in tokens()]


def total_remaining(statuses: list[TokenStatus]) -> float:
    return round(sum(s.remaining_usd or 0 for s in statuses if s.ok), 3)


# ------------------------------------------------------------------ .env
def write_env(name: str, value: str) -> None:
    """Set one variable in backend/.env (owner-only file) and in this process."""
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    out, done = [], False
    for line in lines:
        if line.split("=", 1)[0].strip() == name:
            out.append(f"{name}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.environ[name] = value
    if os.name == "nt":  # only this Windows user may read the file
        subprocess.run(["icacls", str(ENV_FILE), "/inheritance:r", "/grant:r",
                        f"{os.environ.get('USERNAME', '')}:(R,W)"], capture_output=True, check=False)
    else:
        ENV_FILE.chmod(0o600)


def add_token(token: str) -> bool:
    token = token.strip()
    current = list(tokens())
    if not token or token in current:
        return False
    write_env("APIFY_API_TOKENS", ",".join(current + [token]))
    return True


def remove_token(last4: str) -> bool:
    current = list(tokens())
    keep = [t for t in current if not t.endswith(last4)]
    if len(keep) == len(current):
        return False
    write_env("APIFY_API_TOKENS", ",".join(keep))
    return True
