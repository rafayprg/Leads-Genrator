"""7.5 / 8.5 — AI wording on top of verified facts, never new facts.

Guards on every answer:
  1. the model only sees facts Agents 1–5 already validated;
  2. any number in the answer that is not in those facts -> the answer is thrown away;
  3. the owner-facing text may not sell TechDeva;
  4. on any problem the template wording stays (the caller gets None).
"""
from __future__ import annotations

import json
import re

from .client import AIUnavailable, complete_json

LANG = {
    "en": "simple, friendly English",
    "roman_urdu": ("Roman Urdu (Urdu written in English letters, the way people write on WhatsApp in Pakistan, India and the "
                   "Gulf); keep words like website, WhatsApp, booking, Google, Instagram in English"),
}
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
RULES = ("Use ONLY the facts given. Do not invent numbers, names, prices, results or causes. "
         "If an item is marked confirmed=false, say it should be confirmed. Never promise outcomes. "
         "Answer with JSON only.")


def _numbers(text: str) -> set[str]:
    return {str(float(n.replace(",", "."))) for n in NUMBER.findall(text)}


def grounded(answer: str, facts_text: str) -> bool:
    """Every number in the answer must already exist in the facts."""
    return _numbers(answer) <= _numbers(facts_text) | {"1.0", "2.0", "3.0"}  # small list counters are fine


def _facts(pkg: dict, top: int = 6) -> dict:
    s = pkg["sections"]
    o = s["overview"]
    return {"business": o["name"], "type": o["category"] or o["industry"], "location": o["location"],
            "issue_counts": {p: sum(1 for x in s["recommendations"] if x["priority"] == p) for p in ("High", "Medium", "Low")},
            "top_issues": [{"issue": r["issue"], "why": r["why"], "priority": r["priority"], "confirmed": r["confirmed"]}
                           for r in s["recommendations"][:top]],
            "not_checked": [r["section"] for r in s["evidence_limitations"]["completeness"]
                            if r["status"] in ("failed", "not_run", "skipped")],
            "social_media": "presence only; posts and engagement were not available"}


def summary(session, pkg: dict, language: str, cap: int) -> str | None:
    facts = _facts(pkg)
    facts_text = json.dumps(facts, ensure_ascii=False)
    system = (f"You write the executive summary of a website and digital-presence audit for the business owner, "
              f"in {LANG[language]}. 3 to 5 short sentences: what was checked, the most important problems and why "
              f"they matter, and what to do first. Warm, respectful, no jargon, no selling. {RULES}")
    try:
        out = complete_json(session, system, f'Facts: {facts_text}\nReturn {{"summary": "..."}}', cap)
    except AIUnavailable:
        return None
    text = str(out.get("summary") or "").strip()
    if not text or not grounded(text, facts_text) or "techdeva" in text.lower():
        return None
    return text[:1500]


def translate(session, items: list[str], cap: int, batch: int = 25) -> list[str]:
    """English report lines -> Roman Urdu. Lines that fail the checks stay in English."""
    out = list(items)
    for start in range(0, len(items), batch):
        chunk = items[start:start + batch]
        system = (f"Translate each line into {LANG['roman_urdu']}. Keep the meaning exact and keep every number. "
                  f"Return {{\"items\": [...]}} with exactly {len(chunk)} strings in the same order. {RULES}")
        try:
            got = complete_json(session, system, json.dumps({"items": chunk}, ensure_ascii=False), cap).get("items")
        except AIUnavailable:
            break  # keep English for the rest
        if not isinstance(got, list) or len(got) != len(chunk):
            continue
        for i, (src, dst) in enumerate(zip(chunk, got)):
            if isinstance(dst, str) and dst.strip() and grounded(dst, src):
                out[start + i] = dst.strip()
    return out


def sales_note(session, facts: dict, cap: int) -> dict | None:
    """8.5 — internal synthesis for the caller: what matters, and how to open the call."""
    facts_text = json.dumps(facts, ensure_ascii=False)
    system = ("You help a TechDeva sales caller prepare a call to a business in the Gulf or South Asia. From the audit facts, write: "
              "'synthesis' (2-3 sentences: the business's real situation and the strongest reason to talk), "
              "'opener_en' (one friendly first sentence for the call, in English), "
              "'opener_roman_urdu' (the same in Roman Urdu). Only mention TechDeva modules listed in the facts. "
              f"Do not claim the business needs anything for sure. {RULES}")
    try:
        out = complete_json(session, system, f"Facts: {facts_text}\nReturn {{\"synthesis\": \"...\", "
                                             f"\"opener_en\": \"...\", \"opener_roman_urdu\": \"...\"}}", cap)
    except AIUnavailable:
        return None
    note = {k: str(out.get(k) or "").strip()[:600] for k in ("synthesis", "opener_en", "opener_roman_urdu")}
    if not all(note.values()) or not all(grounded(v, facts_text) for v in note.values()):
        return None
    return note
