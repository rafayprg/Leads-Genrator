"""Sales pitch for one audited lead: what to say, built only from the checked audit facts.

Same source as the internal sales brief (Agent 6), so the pitch never says more than the report.
Lines a caller reads out are in Roman Urdu (how the team talks to Gulf / South Asia owners), with English
where a lead prefers it. Things not seen directly are phrased as questions, never as facts.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.reporting import builder as report_builder
from ..models import Business, Report
from .audits import report_inputs
from .sales import REMOVED


def _short(text: str, n: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"


def _talking_point(r: dict) -> dict:
    if r["confirmed"]:
        say = f"Hum ne khud dekha: {_short(r['issue'])}. {_short(r['why'], 110)}"
    else:
        say = f"Ek sawal: kya {_short(r['issue']).rstrip('.').lower()}? (Bahar se aisa lagta hai — confirm karein.)"
    return {"issue": r["issue"], "priority": r["priority"], "confirmed": r["confirmed"], "why": r["why"],
            "fix": r["fix"], "say": say}


def _objections(name: str, points: list[dict], competitors: list[str], modules: list[dict]) -> list[dict]:
    seen = next((p["issue"] for p in points if p["confirmed"]), None)
    out = [
        {"they_say": "Hamari website to pehle se hai.",
         "answer": f"Bilkul — audit usi website ka hai. {('Masalan: ' + _short(seen) + '.') if seen else 'Report mein sab likha hai.'} "
                   "Theek ho jaye to wahi website zyada customers laayegi."},
        {"they_say": "Abhi budget nahi hai.",
         "answer": "Koi baat nahi — report free hai, aur kuch fixes aap ka apna developer bhi kar sakta hai. "
                   "Jab zaroorat ho, hum yahan hain."},
        {"they_say": "Abhi time nahi, baad mein baat karte hain.",
         "answer": f"Main {name} ki report WhatsApp par bhej deta hoon — 2 minute mein dekh lein. Kab call karoon?"},
    ]
    if competitors:
        tools = ", ".join(competitors[:2])
        out.insert(1, {"they_say": f"Hum {tools} use karte hain.",
                       "answer": f"Achhi baat hai. Hum {tools} band karne ko nahi keh rahe — sirf dikhayenge ke "
                                 f"{modules[0]['module'] if modules else 'TechDeva'} saath mein kya farq laata hai."})
    return out


def _wa_link(phone: str | None, phone_type: str | None, text: str) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    if not digits or (phone_type and phone_type not in ("mobile", "landline/mobile")):
        return None  # wa.me only works for a mobile number
    return f"https://wa.me/{digits}?text={quote(text)}"


def pitch(session: Session, b: Business) -> dict:
    inp = report_inputs(session, b)
    if inp is None:
        return {"ready": False, "reason": "Run a full audit first — the pitch is built from the audit."}
    pkg = report_builder.build(inp.profile, inp.dataset, inp.summaries, inp.social, "internal")
    sec = pkg["sections"]
    details = b.details or {}
    opp = details.get("opportunity") or {}
    note = opp.get("ai_note") or {}
    points = [_talking_point(r) for r in sec["recommendations"][:3]]
    o = sec.get("opportunities") or {}
    modules, competitors = o.get("techdeva_modules") or [], o.get("competitor_tools") or []
    first = points[0]["issue"] if points else ""
    opener_ru = note.get("opener_roman_urdu") or (
        f"Assalam o alaikum, main TechDeva se bol raha hoon. Hum ne {b.name} ki website ka free audit kiya"
        + (f" — {_short(first, 70).rstrip('.')}." if first else ".") + " Do minute baat ho sakti hai?")
    opener_en = note.get("opener_en") or (
        f"Hi, this is TechDeva. We did a free check of {b.name}'s website"
        + (f" and noticed: {_short(first, 70).rstrip('.')}." if first else ".") + " Do you have two minutes?")
    count = len(sec["recommendations"])
    wa_text = (f"Assalam o alaikum {b.name} team! Main TechDeva se. Hum ne aap ki website ka free audit kiya — "
               f"{count} cheezein mili jo customers ko rok sakti hain"
               + (f", jaise: {_short(first, 80).rstrip('.')}" if first else "") + ". Report bhej doon?")
    reports = [{"id": r.id, "type": r.report_type, "language": r.language, "version": r.version}
               for r in session.scalars(select(Report).where(Report.business_id == b.id, Report.status != REMOVED)
                                        .order_by(Report.id.desc()))]
    return {
        "ready": True, "name": b.name, "phone": b.phone, "phone_type": details.get("phone_type"),
        "score": opp.get("score"), "band": opp.get("band"), "label": opp.get("label"),
        "why_call": [{"part": k, "points": v.get("points"), "out_of": v.get("out_of"), "why": v.get("why")}
                     for k, v in (opp.get("breakdown") or {}).items()],
        "synthesis": note.get("synthesis"), "opener_roman_urdu": opener_ru, "opener_en": opener_en,
        "opener_by": "ai" if note.get("opener_roman_urdu") else "template",
        "first_topic": o.get("suggested_first_topic") or first,
        "talking_points": points, "modules": modules, "competitor_tools": competitors,
        "to_confirm": [r["issue"] for r in sec.get("needs_verification") or []][:5],
        "whatsapp_text": wa_text, "whatsapp_link": _wa_link(b.phone, details.get("phone_type"), wa_text),
        "angle": sec.get("pitch"),
        "objections": ([sec["pitch"]["likely_objection"]] if sec.get("pitch") else [])
                      + _objections(b.name, points, competitors, modules),
        "reports": reports, "note": o.get("note"),
    }
