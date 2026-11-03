"""Settings read from environment / .env. Secrets never leave the backend."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
ENV_FILE = BACKEND_DIR / ".env"

load_dotenv(ENV_FILE)


@dataclass(frozen=True)
class Settings:
    database_url: str
    apify_tokens: tuple[str, ...]
    ai_provider: str
    cors_origins: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    cookie_secure: bool


def _split(raw: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(x.strip() for x in raw.split(",") if x.strip()))


def load_settings() -> Settings:
    DATA_DIR.mkdir(exist_ok=True)
    default_db = f"sqlite:///{(DATA_DIR / 'audit.db').as_posix()}"
    return Settings(
        database_url=os.getenv("DATABASE_URL", default_db).strip() or default_db,
        apify_tokens=_split(os.getenv("APIFY_API_TOKENS", "")),
        ai_provider=os.getenv("AI_PROVIDER", "none").strip().lower(),
        cors_origins=_split(os.getenv("CORS_ORIGINS", "http://localhost:5190,http://127.0.0.1:5190")),
        # host names the API answers to (blocks DNS-rebinding); add the domain when it runs on a server
        allowed_hosts=_split(os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1")),
        cookie_secure=os.getenv("COOKIE_SECURE", "0").strip() == "1",  # 1 when served over HTTPS
    )
