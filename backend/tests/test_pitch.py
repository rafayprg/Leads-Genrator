from urllib.parse import unquote

from app.models import Business
from app.services import audits
from app.services.pitch import _talking_point, _wa_link
from tests.test_main_agent import _business
from tests.test_reporting import _run_all


def test_pitch_needs_an_audit_and_404s_unknown(client, maker):
    bid = _business(maker)
    assert client.get(f"/businesses/{bid}/pitch").json() == {
        "ready": False, "reason": "Run a full audit first — the pitch is built from the audit."}
    assert client.get("/businesses/999/pitch").status_code == 404


def test_pitch_from_the_audit(client, maker, tmp_path, monkeypatch):
    monkeypatch.setattr(audits, "REPORTS_DIR", tmp_path)
    client.app.state.audit_worker.stop()  # this test runs the agents itself
    bid = _business(maker)
    _run_all(maker, bid)
    p = client.get(f"/businesses/{bid}/pitch").json()
    assert p["ready"] and p["score"] is not None and p["opener_by"] == "template"
    assert p["opener_roman_urdu"].startswith("Assalam o alaikum") and p["name"] in p["opener_en"]
    assert 1 <= len(p["talking_points"]) <= 3 and len(p["objections"]) >= 3
    assert {r["type"] for r in p["reports"]} == {"owner_summary", "internal_sales"}
    with maker() as s:  # an AI opener from the Main Agent wins over the template
        b = s.get(Business, bid)
        b.details = {**b.details, "opportunity": {**b.details["opportunity"],
                                                  "ai_note": {"opener_roman_urdu": "AI line", "opener_en": "AI en", "synthesis": "x"}}}
        s.commit()
    p = client.get(f"/businesses/{bid}/pitch").json()
    assert p["opener_roman_urdu"] == "AI line" and p["opener_by"] == "ai"


def test_unconfirmed_points_are_questions_and_whatsapp_only_for_mobiles():
    seen = _talking_point({"issue": "No WhatsApp link", "why": "x", "fix": "y", "priority": "High", "confirmed": True})
    guess = _talking_point({"issue": "No online booking system seen", "why": "x", "fix": "y", "priority": "High", "confirmed": False})
    assert seen["say"].startswith("Hum ne khud dekha") and guess["say"].startswith("Ek sawal") and "confirm" in guess["say"]
    link = _wa_link("+971 50 123 4567", "mobile", "Salam & hi")
    assert link.startswith("https://wa.me/971501234567?text=") and unquote(link.split("text=")[1]) == "Salam & hi"
    assert _wa_link("+97143808960", "landline", "x") is None and _wa_link(None, "mobile", "x") is None
