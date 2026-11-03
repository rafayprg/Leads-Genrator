"""TechDeva capabilities that Agent 4 may recommend. Never recommend something that is not on this list.

status:
  existing   — live in the TechDeva platform (checked against the project notes, 31 Oct 2026)
  to_confirm — mentioned in TechDeva plans/skills but not confirmed live; reports label it "proposed"
Faheem/Rafay: change a status here when a module ships or is withdrawn.
"""
from __future__ import annotations

CAPABILITIES: dict[str, dict] = {
    "whatsapp_ai_agent": {"name": "WhatsApp AI agent (answers customers 24/7, hands over to staff)", "status": "existing"},
    "lead_inbox": {"name": "Lead inbox / CRM (every enquiry saved with its source and notes)", "status": "existing"},
    "human_takeover": {"name": "Staff can take over any WhatsApp chat from the dashboard", "status": "existing"},
    "social_publishing": {"name": "Content gallery + Instagram/Facebook publishing", "status": "existing"},
    "bookings": {"name": "Online booking / appointments", "status": "to_confirm"},
    "reminders": {"name": "Automatic appointment reminders and follow-ups", "status": "to_confirm"},
}


def label(cap_id: str | None) -> dict:
    if not cap_id:
        return {"id": None, "name": "General advice (not a TechDeva module)", "status": "none", "offer": "advice only"}
    cap = CAPABILITIES[cap_id]
    return {"id": cap_id, "name": cap["name"], "status": cap["status"],
            "offer": "TechDeva module" if cap["status"] == "existing" else "proposed (confirm before promising)"}
