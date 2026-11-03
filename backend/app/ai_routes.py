"""AI provider set-up (admin) and report settings. Keys go to backend/.env only and are shown masked."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .ai import client as ai
from .db import get_session
from .ingest.apify_tokens import write_env
from .models import AppSetting, Role, User
from .security import client_ip, current_user, get_limits, log, require

router = APIRouter()
LANGUAGES = ("en", "roman_urdu")
DEFAULT_REPORT = {"languages": ["en"], "detail": "standard", "ai_wording": True}


class KeyIn(BaseModel):
    provider: Literal["gemini", "groq"]
    key: str = Field(min_length=20, max_length=300, pattern=r"^\S+$")
    as_backup: bool = False  # backup = used only when the main provider fails (limit, outage, retired model)


class ModelIn(BaseModel):
    model: str = Field(min_length=2, max_length=120)


class ReportSettings(BaseModel):
    languages: list[Literal["en", "roman_urdu"]] = Field(min_length=1, max_length=2)
    detail: Literal["summary", "standard", "detailed"] = "standard"
    ai_wording: bool = True


def get_report_settings(session: Session) -> dict:
    row = session.get(AppSetting, "report")
    return {**DEFAULT_REPORT, **((row.value or {}) if row else {})}


def _status(session: Session) -> dict:
    cfg = ai.config()
    return {"provider": cfg.provider if cfg.provider in ai.PROVIDERS else "none", "key": ai.mask(cfg.key),
            "model": cfg.model, "ready": cfg.ready, "backup": ai.backup_info(), "calls_today": ai.usage_today(session),
            "calls_per_day_max": get_limits(session)["ai_calls_per_day_max"]}


@router.get("/ai/status")
def ai_status(session: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    return _status(session)


@router.post("/ai/key")
def ai_set_key(body: KeyIn, request: Request, session: Session = Depends(get_session),
               admin: User = Depends(require(Role.ADMIN))) -> dict:
    """Test the key by listing its models, then save provider + key + a sensible default model."""
    try:
        models = ai.list_models(body.provider, body.key.strip())
    except ai.AIUnavailable as e:
        raise HTTPException(400, f"Key not saved: {e}") from e
    if not models:
        raise HTTPException(400, "Key works but has no text models")
    if body.as_backup:
        if body.provider == ai.config().provider:
            raise HTTPException(400, "The backup must be the other provider than the main one")
        write_env(ai.PROVIDERS[body.provider]["key_env"], body.key.strip())
        log(session, admin, "ai_backup_key_saved", f"{body.provider} {ai.mask(body.key)}", {"models": len(models)},
            client_ip(request))
        return {**_status(session), "models": models}
    write_env("AI_PROVIDER", body.provider)
    write_env(ai.PROVIDERS[body.provider]["key_env"], body.key.strip())
    current = ai.config().model
    write_env("AI_MODEL", current if current in models else ai.pick_default(models, body.provider))
    log(session, admin, "ai_key_saved", f"{body.provider} {ai.mask(body.key)}", {"models": len(models)},
        client_ip(request))
    return {**_status(session), "models": models}


@router.delete("/ai/key", status_code=204)
def ai_remove_key(request: Request, backup: bool = False, session: Session = Depends(get_session),
                  admin: User = Depends(require(Role.ADMIN))) -> None:
    if backup:
        info = ai.backup_info()
        if info:
            write_env(ai.PROVIDERS[info["provider"]]["key_env"], "")
            log(session, admin, "ai_backup_key_removed", f"{info['provider']} {info['key']}", ip=client_ip(request))
        return
    cfg = ai.config()
    if cfg.provider in ai.PROVIDERS:
        write_env(ai.PROVIDERS[cfg.provider]["key_env"], "")
    write_env("AI_PROVIDER", "none")
    log(session, admin, "ai_key_removed", f"{cfg.provider} {ai.mask(cfg.key)}", ip=client_ip(request))


@router.get("/ai/models")
def ai_models(session: Session = Depends(get_session), _: User = Depends(require(Role.ADMIN))) -> dict:
    cfg = ai.config()
    try:
        return {"models": ai.list_models(cfg.provider, cfg.key), "current": cfg.model}
    except ai.AIUnavailable as e:
        raise HTTPException(400, str(e)) from e


@router.put("/ai/model")
def ai_set_model(body: ModelIn, request: Request, session: Session = Depends(get_session),
                 admin: User = Depends(require(Role.ADMIN))) -> dict:
    cfg = ai.config()
    try:
        models = ai.list_models(cfg.provider, cfg.key)
    except ai.AIUnavailable as e:
        raise HTTPException(400, str(e)) from e
    if body.model not in models:
        raise HTTPException(400, "That model is not available for this key")
    write_env("AI_MODEL", body.model)
    log(session, admin, "ai_model_changed", body.model, ip=client_ip(request))
    return _status(session)


@router.post("/ai/test")
def ai_test(request: Request, session: Session = Depends(get_session),
            admin: User = Depends(require(Role.ADMIN))) -> dict:
    """One tiny real call (counts towards the daily limit) to prove the provider answers."""
    try:
        out = ai.complete_json(session, "Reply with JSON only.",
                               'Return {"ok": true, "roman_urdu": "<one short Roman Urdu greeting>"}',
                               get_limits(session)["ai_calls_per_day_max"])
    except ai.AIUnavailable as e:
        raise HTTPException(400, str(e)) from e
    log(session, admin, "ai_tested", ai.config().model, ip=client_ip(request))
    return {"ok": bool(out.get("ok")), "sample": str(out.get("roman_urdu", ""))[:120], **_status(session)}


@router.get("/settings/report")
def report_settings(session: Session = Depends(get_session), _: User = Depends(current_user)) -> dict:
    return get_report_settings(session)


@router.put("/settings/report")
def set_report_settings(body: ReportSettings, request: Request, session: Session = Depends(get_session),
                        admin: User = Depends(require(Role.ADMIN))) -> dict:
    value = {**body.model_dump(), "languages": list(dict.fromkeys(body.languages))}
    row = session.get(AppSetting, "report") or AppSetting(key="report")
    row.value, row.updated_by = value, admin.email
    session.add(row)
    session.commit()
    log(session, admin, "report_settings_changed", None, value, client_ip(request))
    return value
