"""AI provider client for 7.5 / 8.5 — Gemini or Groq (free tiers), chosen in Settings.

- Keys live only in backend/.env and are sent only in request headers (never in a URL).
- One small JSON-in/JSON-out call at a time; a daily call cap protects the free tier.
- Any failure (no key, limit, network, bad answer) raises AIUnavailable so callers fall back to
  the template wording — a report is never blocked by AI.
"""
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

import requests

PROVIDERS = {
    "gemini": {"key_env": "GEMINI_API_KEY", "base": "https://generativelanguage.googleapis.com/v1beta"},
    "groq": {"key_env": "GROQ_API_KEY", "base": "https://api.groq.com/openai/v1"},
}
TIMEOUT = 60
MAX_OUTPUT_TOKENS = 1500
_usage_lock = threading.Lock()


class AIUnavailable(Exception):
    """AI could not be used for this call; the reason is safe to show (no keys inside)."""


@dataclass(frozen=True)
class AIConfig:
    provider: str
    key: str
    model: str

    @property
    def ready(self) -> bool:
        return self.provider in PROVIDERS and bool(self.key) and bool(self.model)


def config() -> AIConfig:
    provider = os.getenv("AI_PROVIDER", "none").strip().lower()
    key = os.getenv(PROVIDERS[provider]["key_env"], "").strip() if provider in PROVIDERS else ""
    return AIConfig(provider, key, os.getenv("AI_MODEL", "").strip())


def mask(key: str) -> str:
    return f"…{key[-4:]}" if key else ""


# ------------------------------------------------------------------ provider calls
def _headers(provider: str, key: str) -> dict:
    if provider == "gemini":
        return {"x-goog-api-key": key, "Content-Type": "application/json"}
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _error(resp: requests.Response) -> str:
    try:
        body = resp.json()
        msg = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
    except ValueError:
        msg = resp.text[:200]
    return f"HTTP {resp.status_code}: {str(msg or '')[:200]}"


def list_models(provider: str, key: str) -> list[str]:
    """Text models this key can use. Raises AIUnavailable when the key does not work."""
    if provider not in PROVIDERS or not key:
        raise AIUnavailable("No provider or key")
    url = PROVIDERS[provider]["base"] + "/models"
    try:
        r = requests.get(url, headers=_headers(provider, key), timeout=20)
    except requests.RequestException as e:
        raise AIUnavailable(f"Network error: {type(e).__name__}") from e
    if r.status_code != 200:
        raise AIUnavailable(_error(r))
    data = r.json()
    if provider == "gemini":
        return sorted(m["name"].removeprefix("models/") for m in data.get("models", [])
                      if "generateContent" in (m.get("supportedGenerationMethods") or [])
                      and "embedding" not in m["name"])
    return sorted(m["id"] for m in data.get("data", []) if not re.search(r"whisper|tts|orpheus|guard|embed", m["id"], re.I))


def _version(model: str) -> tuple[float, ...]:
    return tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", model)[:1]) or (0.0,)


def pick_default(models: list[str], provider: str) -> str:
    if provider == "gemini":
        # Google retires old versions for new keys while still listing them, so prefer the "-latest" aliases,
        # then the newest plain text flash-lite / flash version
        for alias in ("gemini-flash-lite-latest", "gemini-flash-latest"):
            if alias in models:
                return alias
        for p in (r"^gemini-[\d.]+-flash-lite$", r"^gemini-[\d.]+-flash$"):
            hits = sorted((m for m in models if re.search(p, m)), key=_version, reverse=True)
            if hits:
                return hits[0]
        return models[0] if models else ""
    prefs = (r"qwen", r"llama.*instant", r"llama")
    for p in prefs:
        hit = next((m for m in models if re.search(p, m, re.I) and "preview" not in m.lower()), None) or \
            next((m for m in models if re.search(p, m, re.I)), None)
        if hit:
            return hit
    return models[0] if models else ""


def _call(cfg: AIConfig, system: str, user: str) -> str:
    if cfg.provider == "gemini":
        url = f"{PROVIDERS['gemini']['base']}/models/{cfg.model}:generateContent"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": MAX_OUTPUT_TOKENS,
                                     "responseMimeType": "application/json"}}
    else:
        url = f"{PROVIDERS['groq']['base']}/chat/completions"
        body = {"model": cfg.model, "temperature": 0.2, "max_tokens": MAX_OUTPUT_TOKENS,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    try:
        r = requests.post(url, headers=_headers(cfg.provider, cfg.key), json=body, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise AIUnavailable(f"Network error: {type(e).__name__}") from e
    if r.status_code == 429:
        raise AIUnavailable("Free-tier limit reached at the provider; try later")
    if r.status_code != 200:
        raise AIUnavailable(_error(r))
    data = r.json()
    try:
        if cfg.provider == "gemini":
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise AIUnavailable("The model returned no text") from e


def _parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()  # some models think out loud first
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AIUnavailable("The model did not answer in JSON")
    try:
        return json.loads(m.group(0))
    except ValueError as e:
        raise AIUnavailable("The model answered with broken JSON") from e


# ------------------------------------------------------------------ daily cap (counted in app_settings)
def _count_call(session, cap: int) -> None:
    from ..models import AppSetting  # local: models import is heavy and only needed here
    with _usage_lock:
        row = session.get(AppSetting, "ai_usage") or AppSetting(key="ai_usage", value={})
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        used = (row.value or {}).get(today, 0)
        if used >= cap:
            raise AIUnavailable(f"Daily AI limit reached ({cap} calls); an admin can raise it in Settings")
        row.value = {today: used + 1}  # keep only today
        session.add(row)
        session.commit()


def usage_today(session) -> int:
    from ..models import AppSetting
    row = session.get(AppSetting, "ai_usage")
    return ((row.value or {}) if row else {}).get(datetime.now(UTC).strftime("%Y-%m-%d"), 0)


# ------------------------------------------------------------------ backup provider (the other one, if it has a key)
_backup_models: dict[tuple[str, str], str] = {}  # (provider, key tail) -> model picked once per process
last_fallback: dict = {}  # shown in Settings: when and why the backup was last used


def _backup_key() -> tuple[str, str] | None:
    main = config().provider
    for provider, p in PROVIDERS.items():
        key = os.getenv(p["key_env"], "").strip()
        if provider != main and key:
            return provider, key
    return None


def backup() -> AIConfig | None:
    """The other provider when its key is in .env; its model is picked from its own list once per process."""
    found = _backup_key()
    if found is None:
        return None
    provider, key = found
    cache = (provider, key[-6:])
    if cache not in _backup_models:
        _backup_models[cache] = pick_default(list_models(provider, key), provider)
    return AIConfig(provider, key, _backup_models[cache])


def backup_info() -> dict | None:
    """For Settings, without any network call."""
    found = _backup_key()
    if found is None:
        return None
    provider, key = found
    return {"provider": provider, "key": mask(key), "model": _backup_models.get((provider, key[-6:]), ""),
            "last_used": dict(last_fallback) or None}


def complete_json(session, system: str, user: str, cap: int) -> dict:
    """One answer from the main provider; on any provider problem, one try with the backup provider.
    Both tries count towards the daily cap."""
    cfg = config()
    if not cfg.ready:
        raise AIUnavailable("No AI provider set up")
    _count_call(session, cap)
    try:
        return _parse_json(_call(cfg, system, user))
    except AIUnavailable as first:
        try:
            alt = backup()
        except AIUnavailable as e:
            raise AIUnavailable(f"{first} (backup not usable: {e})") from first
        if alt is None:
            raise
        _count_call(session, cap)
        last_fallback.clear()
        last_fallback.update({"at": datetime.now(UTC).isoformat(timespec="seconds"), "reason": str(first)[:160],
                              "used": f"{alt.provider} · {alt.model}"})
        try:
            return _parse_json(_call(alt, system, user))
        except AIUnavailable as second:
            raise AIUnavailable(f"{cfg.provider}: {first}; {alt.provider}: {second}") from second
