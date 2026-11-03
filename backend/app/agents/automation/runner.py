"""Agent 4 — Automation Runner, Mode A (audit only).

Reads the public website, lists the tools already in use (booking, chat, WhatsApp tools, forms, CRM,
tracking) and the steps that look manual, then maps each gap to a TechDeva capability.
It changes nothing anywhere and runs no workflow. Sandbox (Mode B) and live systems (Mode C) are separate,
permission-gated steps that are not built.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from ..findings import C, Finding, S, V
from ..website.discover import discover
from ..website.fetch import SafeFetcher
from .capabilities import label
from .signatures import SIGNATURES

PAGES = ("home", "contact", "booking", "services")
BOOKING_INDUSTRIES = {"beauty", "clinics", "fitness", "veterinary", "academies", "driving_schools", "automotive",
                      "restaurants"}
BOOKING_TEXT = re.compile(r"(?i)book (now|online|an appointment)|book appointment|reserve (now|a table)|حجز")
LIMITATION = ("Mode A (audit only): no workflow was run and no business system was touched, so success rates and "
              "business impact are not measured.")


@dataclass
class AutomationReview:
    status: str
    tools: list[dict] = field(default_factory=list)          # [{name, kind, competitor, seen_on}]
    signals: dict = field(default_factory=dict)
    opportunities: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: [LIMITATION])

    def summary(self) -> dict:
        return {"agent": "automation_runner", "evaluation_status": self.status, "execution_mode": "audit_only",
                "existing_automation": self.tools, "signals": self.signals, "opportunities": self.opportunities,
                "limitations": self.limitations, "completed_at": datetime.now(UTC).isoformat(timespec="seconds")}


def detect(pages: dict[str, str]) -> tuple[list[dict], dict]:
    """Tools + simple signals (forms, tel/WhatsApp links, booking wording) across the given pages."""
    tools: dict[str, dict] = {}
    signals = {"forms": 0, "tel_links": 0, "whatsapp_links": 0, "booking_wording": False}
    for kind, html in pages.items():
        low = html.lower()
        soup = BeautifulSoup(html, "html.parser")
        refs = " ".join(t.get("src", "") for t in soup.find_all(["script", "iframe", "img"])) + " " + \
            " ".join(t.get("href", "") for t in soup.find_all(["a", "link"])) + " " + \
            " ".join(t.get("action", "") for t in soup.find_all("form"))
        haystack = refs.lower() + " " + " ".join(s.string or "" for s in soup.find_all("script")).lower()
        for needle, (name, tkind, competitor) in SIGNATURES.items():
            if needle in haystack or (needle.endswith("(") and needle in low):
                t = tools.setdefault(name, {"name": name, "kind": tkind, "competitor": competitor, "seen_on": []})
                if kind not in t["seen_on"]:
                    t["seen_on"].append(kind)
        hrefs = [a.get("href", "").lower() for a in soup.find_all("a", href=True)]
        signals["forms"] += len(soup.find_all("form"))
        signals["tel_links"] += sum(h.startswith("tel:") for h in hrefs)
        signals["whatsapp_links"] += sum("wa.me" in h or "api.whatsapp.com" in h or h.startswith("whatsapp:") for h in hrefs)
        signals["booking_wording"] |= bool(BOOKING_TEXT.search(soup.get_text(" ", strip=True)))
    return sorted(tools.values(), key=lambda t: (t["kind"], t["name"])), signals


def _opp(workflow: str, problem: str, solution: str, cap: str | None, severity: S, evidence: dict) -> tuple[dict, Finding]:
    capability = label(cap)
    opp = {"workflow": workflow, "business_problem": problem, "recommended_solution": solution,
           "techdeva_capability": capability, "execution_status": "not_tested", "business_impact": "not_measured",
           "evidence": evidence}
    rec = f"{solution} — {capability['name']} ({capability['offer']})."
    finding = Finding("automation", problem, severity, rec,
                      impact="Manual steps cost staff time and lose enquiries outside working hours.",
                      evidence=evidence, confidence=C.MEDIUM, verification=V.INFERRED)
    return opp, finding


def opportunities(industry: str, tools: list[dict], s: dict) -> list[tuple[dict, Finding]]:
    kinds = {t["kind"] for t in tools}
    out = []
    if industry in BOOKING_INDUSTRIES and "booking" not in kinds:
        out.append(_opp("appointment_request_processing",
                        "No online booking system seen — bookings probably come by phone or message",
                        "Online booking with instant confirmation and reminders", "bookings", S.MEDIUM,
                        {"booking_tool": None, "booking_wording_on_site": s["booking_wording"]}))
    if "whatsapp_tool" not in kinds:
        if s["whatsapp_links"]:
            out.append(_opp("whatsapp_inquiry_handling", "WhatsApp enquiries are likely answered by hand",
                            "An AI WhatsApp assistant that answers common questions and collects bookings 24/7",
                            "whatsapp_ai_agent", S.MEDIUM, {"whatsapp_links": s["whatsapp_links"], "whatsapp_tool": None}))
        else:
            out.append(_opp("whatsapp_channel", "No WhatsApp channel on the website",
                            "Add a WhatsApp button backed by an AI assistant so enquiries never wait",
                            "whatsapp_ai_agent", S.MEDIUM, {"whatsapp_links": 0}))
    if s["forms"] and "crm_form" not in kinds:
        out.append(_opp("lead_capture_to_crm", "Website enquiries probably land in an email inbox with no follow-up tracking",
                        "Send every enquiry into one lead inbox with status and follow-up", "lead_inbox", S.LOW,
                        {"forms": s["forms"], "crm_or_form_tool": None}))
    if not s["forms"] and "booking" not in kinds and not s["whatsapp_links"]:
        out.append(_opp("website_lead_capture", "Visitors cannot leave their details online",
                        "A short enquiry form or WhatsApp entry point that saves each lead", "lead_inbox", S.MEDIUM,
                        {"forms": 0, "whatsapp_links": 0}))
    if not kinds & {"analytics", "ads_pixel"}:
        out.append(_opp("lead_source_tracking", "No visitor tracking seen — the business cannot tell which ads or pages bring customers",
                        "Install basic analytics and track enquiries by source", None, S.LOW,
                        {"analytics_tools": None}))
    return out


def review(website_url: str | None, industry: str = "", fetcher: SafeFetcher | None = None) -> AutomationReview:
    if not website_url:
        return AutomationReview("skipped", limitations=["No website on record", LIMITATION])
    fetcher = fetcher or SafeFetcher()
    d = discover(fetcher, website_url)
    if not d.home.ok:
        return AutomationReview("failed", limitations=[f"Website could not be read ({d.home.blocked or d.home.error or d.home.status})",
                                                       LIMITATION])
    pages = {"home": d.home.text}
    for kind in PAGES[1:]:
        if d.pages.get(kind):
            r = fetcher.get(d.pages[kind])
            if r.ok:
                pages[kind] = r.text
    res = AutomationReview("completed")
    res.tools, res.signals = detect(pages)
    res.signals["pages_read"] = sorted(pages)
    for opp, finding in opportunities(industry, res.tools, res.signals):
        res.opportunities.append(opp)
        res.findings.append(finding)
    competitors = [t["name"] for t in res.tools if t["competitor"]]
    if competitors:
        res.signals["competitor_tools"] = competitors
    return res
