"""Agent 5 — Data Organizer & Quality Controller.

Takes the latest finished output of every specialist agent for one business and builds the
Unified Business Audit Dataset: normalised findings, the same issue merged across agents (sources kept),
an evidence check, contradictions, a completeness table and next steps.
It never invents conclusions and never deletes an agent's original finding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

SEVERITIES = ("critical", "high", "medium", "low")
STALE_AFTER = timedelta(days=30)
# same issue seen by different agents: topic -> words in the finding title (lower case)
TOPICS: dict[str, tuple[str, ...]] = {
    "whatsapp": ("whatsapp",),
    "online_booking": ("book an appointment", "online booking", "booking system"),
    "lead_capture": ("enquiry form", "leave their details", "enquiries probably land"),
    "phone_link": ("tap-to-call",),
    "social_presence": ("social media account", "instagram account", "link to the social"),
    "tracking": ("visitor tracking",),
    "availability": ("did not load", "could not be found", "unsafe location"),
}
AGENT_LABEL = {"website_expert": "Agent 1 · website", "social_media_finder": "Agent 3 · social finder",
               "social_media_expert": "Agent 2 · social", "automation_runner": "Agent 4 · automation"}


@dataclass(frozen=True)
class AgentOutput:
    agent: str
    task_id: int
    status: str                    # task status: completed / skipped / failed
    finished_at: datetime | None
    summary: dict
    findings: list[dict] = field(default_factory=list)  # AuditFinding rows as dicts


def _short(dt) -> str:
    if not isinstance(dt, datetime):
        return "time unknown"
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).strftime("%d %b %H:%M UTC")


def _iso(dt) -> str:
    if isinstance(dt, datetime):
        return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat(timespec="seconds")
    return str(dt or "")


# ------------------------------------------------------------------ 6.1 normalise
def normalise(agent: str, f: dict) -> dict:
    sev = str(f.get("severity", "")).lower()
    notes = []
    if sev not in SEVERITIES:
        notes.append(f"unknown severity '{f.get('severity')}' treated as low")
        sev = "low"
    evidence = f.get("evidence") or {}
    return {
        "finding_id": f"F-{f['id']}", "agent_name": agent, "category": str(f.get("category", "")).lower(),
        "issue": f.get("title", ""), "impact": f.get("description") or "", "severity": sev, "evidence": evidence,
        "source_url": f.get("source_url") or evidence.get("url") or "",
        "recommendation": f.get("recommendation") or "", "confidence": str(f.get("confidence", "")).lower(),
        "verification_status": str(f.get("verification_status", "")).lower(),
        "audit_timestamp": _iso(f.get("observed_at")), "notes": notes,
    }


def topic_of(f: dict) -> str:
    title = f["issue"].lower()
    for topic, words in TOPICS.items():
        if any(w in title for w in words):
            return topic
    return f"{f['agent_name']}:{f['finding_id']}"  # no shared topic: stands alone


# ------------------------------------------------------------------ 6.2 merge + 6.3 evidence check
def _quality(group: list[dict], now: datetime) -> tuple[str, str]:
    if not any(f["evidence"] or f["source_url"] for f in group):
        return "missing_evidence", "No evidence or page recorded — not used in reports until re-checked"
    times = [datetime.fromisoformat(f["audit_timestamp"]) for f in group if f["audit_timestamp"]]
    if times and now - max(times) > STALE_AFTER:
        return "stale", f"Last observed {max(times):%d %b %Y}; re-run before using"
    states = {f["verification_status"] for f in group}
    if "verified" in states:
        return "verified", "Seen directly by an agent"
    if "requires_review" in states:
        return "requires_review", "An agent asked for a human check"
    agents = {f["agent_name"] for f in group}
    if len(agents) > 1:
        return "requires_verification", f"Inferred by {len(agents)} agents independently — likely, but confirm on the call"
    return "requires_verification", "Inferred, not seen directly — confirm before telling the owner"


def consolidate(findings: list[dict], now: datetime) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for f in findings:
        groups.setdefault(topic_of(f), []).append(f)
    items = []
    for topic, group in groups.items():
        group.sort(key=lambda f: (SEVERITIES.index(f["severity"]), f["verification_status"] != "verified"))
        primary = group[0]
        quality, why = _quality(group, now)
        items.append({
            **{k: primary[k] for k in ("issue", "impact", "severity", "category", "recommendation", "source_url")},
            "topic": topic if ":" not in topic else None, "status": quality, "status_reason": why,
            "agents": sorted({f["agent_name"] for f in group}),
            "source_finding_ids": [f["finding_id"] for f in group],
            "related": [{"finding_id": f["finding_id"], "agent_name": f["agent_name"], "issue": f["issue"],
                         "severity": f["severity"]} for f in group[1:]],
            "evidence": primary["evidence"], "confidence": primary["confidence"],
        })
    items.sort(key=lambda i: (SEVERITIES.index(i["severity"]), i["status"] != "verified", i["issue"]))
    return items


# ------------------------------------------------------------------ 6.4 contradictions
def contradictions(out: dict[str, AgentOutput], findings: list[dict]) -> list[dict]:
    found = []
    reads = []  # (agent, could read the website?, when)
    a1, a3, a4 = out.get("website_expert"), out.get("social_media_finder"), out.get("automation_runner")
    if a1 and a1.summary.get("status") in ("completed", "partial", "failed"):
        reads.append(("website_expert", a1.summary["status"] != "failed", a1.finished_at))
    if a4 and a4.summary.get("evaluation_status") in ("completed", "failed"):
        reads.append(("automation_runner", a4.summary["evaluation_status"] == "completed", a4.finished_at))
    if a3 and a3.summary.get("discovery_status") in ("completed", "partial") and a3.summary.get("pages_read") is not None:
        reads.append(("social_media_finder", bool(a3.summary.get("pages_read")), a3.finished_at))
    ok = [r for r in reads if r[1]]
    bad = [r for r in reads if not r[1]]
    if ok and bad:
        found.append({"topic": "availability",
                      "statement": "Website was readable for " + ", ".join(f"{AGENT_LABEL[a]} ({_short(t)})" for a, _, t in ok)
                                   + " but not for " + ", ".join(f"{AGENT_LABEL[a]} ({_short(t)})" for a, _, t in bad)
                                   + ". It may be intermittent (or our connection failed); re-check before reporting.",
                      "agents": sorted({r[0] for r in reads})})
    titles = {f["issue"].lower(): f for f in findings if f["agent_name"] == "website_expert"}
    sig = (a4.summary.get("signals") or {}) if a4 else {}
    tools = {t["kind"] for t in (a4.summary.get("existing_automation") or [])} if a4 else set()
    if "no whatsapp contact link" in titles and sig.get("whatsapp_links"):
        found.append({"topic": "whatsapp", "agents": ["website_expert", "automation_runner"],
                      "statement": "Agent 1 saw no WhatsApp link but Agent 4 did — they read different pages "
                                   f"({', '.join(sig.get('pages_read') or [])}). Treat WhatsApp as present; check where it is shown."})
    if "no clear way to book an appointment online" in titles and "booking" in tools:
        found.append({"topic": "online_booking", "agents": ["website_expert", "automation_runner"],
                      "statement": "Agent 1 found no booking wording but Agent 4 found a booking tool on the site. "
                                   "Booking exists; it may be hard to find."})
    return found


# ------------------------------------------------------------------ 6.5 completeness + next steps
def completeness(business: dict, out: dict[str, AgentOutput]) -> list[dict]:
    rows = []
    missing = [k for k in ("phone", "website_url", "city", "category") if not business.get(k)]
    rows.append({"section": "Business profile", "status": "partial" if missing else "complete",
                 "reason": f"Missing: {', '.join(missing)}" if missing else "Name, phone, website, city and category on record"})

    def row(section: str, agent: str, key: str, ok_status: str = "complete", note: str = ""):
        o = out.get(agent)
        if o is None:
            return {"section": section, "status": "not_run", "reason": "Agent has not run yet"}
        st = o.summary.get(key, o.status)
        lim = (o.summary.get("limitations") or o.summary.get("overall_limitations") or [""])[0]
        if o.status == "skipped" or st == "skipped":
            return {"section": section, "status": "skipped", "reason": lim or "Nothing to check"}
        if st == "failed":
            return {"section": section, "status": "failed", "reason": lim or "Agent could not finish"}
        if st == "partial":
            return {"section": section, "status": "partial", "reason": lim}
        return {"section": section, "status": ok_status, "reason": note or "Done"}

    rows.append(row("Website audit", "website_expert", "status",
                    note=f"{len((out.get('website_expert') or AgentOutput('', 0, '', None, {})).summary.get('pages') or {})} page(s) inspected"))
    rows.append(row("Social media discovery", "social_media_finder", "discovery_status",
                    note="Own website + links on record (no platform search)"))
    rows.append(row("Social media audit", "social_media_expert", "audit_status", ok_status="partial",
                    note="Presence only: posts and engagement not available (no scraping)"))
    rows.append(row("Automation evaluation", "automation_runner", "evaluation_status", ok_status="limited",
                    note="Audit only: no workflow run, impact not measured"))
    return rows


def next_steps(items: list[dict], table: list[dict]) -> list[str]:
    steps = [f"Re-run: {r['section']} ({r['reason']})" for r in table if r["status"] in ("failed", "not_run")
             and r["section"] != "Business profile"]
    top = [i for i in items if i["severity"] in ("critical", "high", "medium") and i["status"] != "missing_evidence"][:5]
    steps += [f"{'Confirm, then raise' if i['status'] != 'verified' else 'Raise'}: {i['issue']}" for i in top]
    if any(i["status"] == "requires_review" for i in items):
        steps.append("Check by hand the items marked 'requires review' before the sales call")
    return steps


def organize(business: dict, outputs: list[AgentOutput], now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    out = {o.agent: o for o in outputs}
    findings = [normalise(o.agent, f) for o in outputs for f in o.findings]
    items = consolidate(findings, now)
    table = completeness(business, out)
    counts = {s: sum(1 for i in items if i["severity"] == s) for s in SEVERITIES}
    return {
        "agent": "data_organizer", "business_id": business.get("business_id"), "built_at": _iso(now),
        "inputs": [{"agent_name": o.agent, "task_id": o.task_id, "status": o.status, "finished_at": _iso(o.finished_at)}
                   for o in outputs],
        "completeness": table,
        "overall_completeness": f"{sum(r['status'] in ('complete', 'partial', 'limited') for r in table)}/{len(table)} sections usable",
        "issues": items, "issue_counts": counts,
        "needs_verification": sum(1 for i in items if i["status"] in ("requires_verification", "requires_review")),
        "contradictions": contradictions(out, findings),
        "findings_normalised": findings,
        "next_steps": next_steps(items, table),
    }
