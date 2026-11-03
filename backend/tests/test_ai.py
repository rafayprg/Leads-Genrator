import json
import os
from pathlib import Path

import pytest

from app.ai import client as ai
from app.ai import writer
from app.ingest import apify_tokens
from app.models import AgentName, AgentTask, Business, Report
from app.services import audits
from tests.test_reporting import _business, _run_all

ENV_KEYS = ("AI_PROVIDER", "AI_MODEL", "GEMINI_API_KEY", "GROQ_API_KEY")
FAKE_KEY = "gsk_" + "T" * 30 + "9876"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """AI settings in a temporary .env; the real backend/.env is never touched."""
    before = {k: os.environ.get(k) for k in ENV_KEYS}
    for k in ENV_KEYS:  # the real keys loaded from backend/.env must not leak into a test
        os.environ.pop(k, None)
    monkeypatch.setattr(apify_tokens, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setattr(ai, "_backup_models", {})
    monkeypatch.setattr(ai, "last_fallback", {})
    yield tmp_path / ".env"
    for k, v in before.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture()
def fake_ai(env, monkeypatch):
    """A pretend model: answers by prompt type; `bad` makes it invent a number."""
    state = {"bad": False, "calls": 0}

    def call(cfg, system, user):
        state["calls"] += 1
        if "Translate" in system:
            items = json.loads(user)["items"]
            return json.dumps({"items": [f"[RU] {x}" for x in items]})
        if "sales caller" in system:
            return json.dumps({"synthesis": "Website slow hai aur WhatsApp nahi.", "opener_en": "Hello, quick question.",
                               "opener_roman_urdu": "Assalam o alaikum, ek chhota sa sawal tha."})
        if state["bad"]:
            return json.dumps({"summary": "You lost 4000 customers last year."})
        return json.dumps({"summary": "We checked the website. The most important fix is HTTPS."})

    monkeypatch.setattr(ai, "_call", call)
    os.environ.update({"AI_PROVIDER": "groq", "GROQ_API_KEY": FAKE_KEY, "AI_MODEL": "qwen/test"})
    return state


def test_no_provider_means_template(env):
    os.environ["AI_PROVIDER"] = "none"
    assert not ai.config().ready


def test_grounding_guard_and_daily_cap(maker, fake_ai):
    pkg = {"sections": {"overview": {"name": "Glow", "category": "Salon", "industry": "beauty", "location": "Dubai"},
                        "recommendations": [{"issue": "Website does not use HTTPS", "why": "x", "fix": "y",
                                             "priority": "High", "confirmed": True}],
                        "evidence_limitations": {"completeness": []}}}
    with maker() as s:
        assert writer.summary(s, pkg, "en", cap=10).startswith("We checked")
        fake_ai["bad"] = True
        assert writer.summary(s, pkg, "en", cap=10) is None  # invented "4000" -> thrown away
        assert writer.summary(s, pkg, "en", cap=2) is None   # 3rd call today > cap 2 -> no call at all
        assert fake_ai["calls"] == 2 and ai.usage_today(s) == 2


def test_list_models_and_default_pick(monkeypatch):
    class R:
        status_code = 200

        def __init__(self, data):
            self._d = data

        def json(self):
            return self._d

    seen = {}

    def get(url, headers, timeout):
        seen["headers"], seen["url"] = headers, url
        if "googleapis" in url:
            return R({"models": [{"name": "models/gemini-x-flash-lite", "supportedGenerationMethods": ["generateContent"]},
                                 {"name": "models/text-embedding", "supportedGenerationMethods": ["embedContent"]}]})
        return R({"data": [{"id": "whisper-large"}, {"id": "qwen/qwen3-32b"}, {"id": "llama-3.1-8b-instant"}]})

    monkeypatch.setattr(ai.requests, "get", get)
    assert ai.list_models("gemini", "k" * 30) == ["gemini-x-flash-lite"]
    assert "k" * 30 not in seen["url"] and seen["headers"]["x-goog-api-key"] == "k" * 30  # key only in a header
    groq = ai.list_models("groq", "k" * 30)
    assert groq == ["llama-3.1-8b-instant", "qwen/qwen3-32b"] and ai.pick_default(groq, "groq") == "qwen/qwen3-32b"


def test_gemini_default_skips_retired_and_non_text_models():
    listed = ["gemini-2.5-flash-lite", "gemini-3.1-flash-lite-image", "gemini-3.5-flash-lite", "gemini-3.8-flash",
              "gemini-3.8-flash-lite-tts", "gemini-10.0-flash-lite"]
    assert ai.pick_default(listed, "gemini") == "gemini-10.0-flash-lite"  # newest plain flash-lite, by number
    assert ai.pick_default([*listed, "gemini-flash-lite-latest"], "gemini") == "gemini-flash-lite-latest"
    assert ai.pick_default(["gemini-2.5-flash", "gemini-3.6-flash"], "gemini") == "gemini-3.6-flash"


def test_reports_with_ai_and_roman_urdu(client, maker, fake_ai, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path / "reports")
    assert client.put("/settings/report", json={"languages": ["en", "roman_urdu"], "detail": "summary",
                                                "ai_wording": True}).status_code == 200
    bid = _business(maker)
    ids = _run_all(maker, bid)
    with maker() as s:
        out = s.get(AgentTask, ids[AgentName.REPORTING]).output_data
        langs = {(r["report_type"], r["language"], r["wording"]) for r in out["reports"]}
        assert langs == {("owner_summary", "en", "ai"), ("owner_summary", "roman_urdu", "ai"), ("internal_sales", "en", "template")}
        ru = s.query(Report).filter_by(language="roman_urdu").one()
        html = Path(ru.storage_path).read_text(encoding="utf-8")
        assert "Pehle kya theek karein" in html and "[RU] " in html and 'lang="ur-Latn"' in html
        note = s.get(Business, bid).details["opportunity"]["ai_note"]
        assert note["opener_roman_urdu"].startswith("Assalam")


def test_roman_urdu_without_ai_is_skipped_with_a_note(client, maker, env, tmp_path, monkeypatch):
    os.environ["AI_PROVIDER"] = "none"
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path / "reports")
    client.put("/settings/report", json={"languages": ["en", "roman_urdu"], "detail": "standard", "ai_wording": True})
    bid = _business(maker)
    ids = _run_all(maker, bid)
    with maker() as s:
        out = s.get(AgentTask, ids[AgentName.REPORTING]).output_data
        assert {r["language"] for r in out["reports"]} == {"en"}
        assert any("Roman Urdu report skipped" in n for n in out["limitations"])


def test_ai_key_endpoint_saves_masked_and_logs(client, env, monkeypatch, maker):
    monkeypatch.setattr(ai, "list_models", lambda provider, key: ["llama-3.1-8b-instant", "qwen/qwen3-32b"])
    r = client.post("/ai/key", json={"provider": "groq", "key": FAKE_KEY})
    assert r.status_code == 200 and r.json()["key"] == "…9876" and FAKE_KEY not in r.text
    assert r.json()["model"] == "qwen/qwen3-32b" and r.json()["ready"]
    assert f"GROQ_API_KEY={FAKE_KEY}" in env.read_text()
    assert client.put("/ai/model", json={"model": "nope"}).status_code == 400
    acts = client.get("/activity").json()
    assert acts[0]["action"] == "ai_key_saved" and FAKE_KEY not in json.dumps(acts)

    monkeypatch.setattr(ai, "list_models", lambda p, k: (_ for _ in ()).throw(ai.AIUnavailable("HTTP 401: invalid")))
    bad = client.post("/ai/key", json={"provider": "gemini", "key": "A" * 39})
    assert bad.status_code == 400 and "not saved" in bad.json()["detail"]


GEMINI_KEY = "AQ." + "G" * 30 + "1234"


def test_backup_provider_answers_when_main_fails(maker, env, monkeypatch):
    os.environ.update({"AI_PROVIDER": "gemini", "GEMINI_API_KEY": GEMINI_KEY, "AI_MODEL": "gemini-flash-lite-latest",
                       "GROQ_API_KEY": FAKE_KEY})
    monkeypatch.setattr(ai, "list_models", lambda p, k: ["openai/gpt-oss-20b", "qwen/qwen3-32b"])
    used = []

    def call(cfg, system, user):
        used.append((cfg.provider, cfg.model))
        if cfg.provider == "gemini":
            raise ai.AIUnavailable("Free-tier limit reached at the provider; try later")
        return '{"ok": true}'

    monkeypatch.setattr(ai, "_call", call)
    with maker() as s:
        assert ai.complete_json(s, "sys", "user", cap=10) == {"ok": True}
        assert used == [("gemini", "gemini-flash-lite-latest"), ("groq", "qwen/qwen3-32b")]
        assert ai.usage_today(s) == 2  # both tries count towards the daily cap
    info = ai.backup_info()
    assert info["provider"] == "groq" and info["key"] == "…9876" and FAKE_KEY not in json.dumps(info)
    assert "Free-tier limit" in info["last_used"]["reason"] and info["last_used"]["used"] == "groq · qwen/qwen3-32b"


def test_no_backup_or_both_failing_raises(maker, env, monkeypatch):
    os.environ.update({"AI_PROVIDER": "gemini", "GEMINI_API_KEY": GEMINI_KEY, "AI_MODEL": "m"})
    monkeypatch.setattr(ai, "_call", lambda cfg, s, u: (_ for _ in ()).throw(ai.AIUnavailable(f"{cfg.provider} down")))
    with maker() as s:
        with pytest.raises(ai.AIUnavailable, match="^gemini down$"):
            ai.complete_json(s, "sys", "user", cap=10)
        assert ai.usage_today(s) == 1  # no backup -> no second try
        os.environ["GROQ_API_KEY"] = FAKE_KEY
        monkeypatch.setattr(ai, "list_models", lambda p, k: ["qwen/qwen3-32b"])
        with pytest.raises(ai.AIUnavailable, match="gemini: gemini down; groq: groq down"):
            ai.complete_json(s, "sys", "user", cap=10)
        with pytest.raises(ai.AIUnavailable, match="Daily AI limit"):  # 3 used, cap 3: not even the main try
            ai.complete_json(s, "sys", "user", cap=3)


def test_backup_key_endpoint(client, env, monkeypatch):
    os.environ.update({"AI_PROVIDER": "gemini", "GEMINI_API_KEY": GEMINI_KEY, "AI_MODEL": "m"})
    monkeypatch.setattr(ai, "list_models", lambda p, k: ["qwen/qwen3-32b"])
    same = client.post("/ai/key", json={"provider": "gemini", "key": GEMINI_KEY, "as_backup": True})
    assert same.status_code == 400
    r = client.post("/ai/key", json={"provider": "groq", "key": FAKE_KEY, "as_backup": True})
    assert r.status_code == 200 and FAKE_KEY not in r.text
    assert r.json()["provider"] == "gemini" and r.json()["backup"]["provider"] == "groq"  # main provider unchanged
    assert f"GROQ_API_KEY={FAKE_KEY}" in env.read_text() and "AI_PROVIDER" not in env.read_text()
    assert client.delete("/ai/key?backup=true").status_code == 204
    st = client.get("/ai/status").json()
    assert st["backup"] is None and st["ready"] and st["provider"] == "gemini"
    assert client.get("/activity").json()[0]["action"] == "ai_backup_key_removed"
