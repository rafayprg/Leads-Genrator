"""Agent 6 — Reporting. Turns Agent 5's validated dataset into a report-ready package (no AI, no new claims).

Two audiences:
  owner    — for the business owner: plain words, problem → why it matters → what to do.
  internal — for TechDeva sales: adds unconfirmed items, competitor tools, TechDeva fit and a first call topic.
Rules: only Agent 5 issues are used; anything not seen directly is labelled; product suggestions are kept
apart from confirmed needs (nothing is "confirmed" until the owner says so).
"""
from __future__ import annotations

from datetime import UTC, datetime

from ...ingest.gulf import INDUSTRIES
from . import pitch

AUDIENCES = ("owner", "internal")
USABLE = {"verified", "requires_verification", "requires_review"}
PRIORITY_ORDER = ("High", "Medium", "Low")


def _priority(issue: dict) -> str:
    if issue["severity"] in ("critical", "high") and issue["status"] == "verified":
        return "High"
    if issue["severity"] in ("critical", "high", "medium"):
        return "Medium"
    return "Low"


def _rec(issue: dict) -> dict:
    return {"priority": _priority(issue), "issue": issue["issue"], "why": issue.get("impact") or "",
            "fix": issue.get("recommendation") or "", "category": issue.get("category", ""),
            "confirmed": issue["status"] == "verified", "status": issue["status"], "agents": issue.get("agents", []),
            "source_url": issue.get("source_url") or ""}


def _overview(p: dict, social: list[dict], built: str) -> dict:
    return {"name": p["name"], "business_id": p["business_id"], "industry": p.get("industry") or "",
            "category": p.get("category") or INDUSTRIES.get(p.get("industry") or "", {}).get("label", ""), "location": ", ".join(x for x in (p.get("area"), p.get("city")) if x),
            "country": p.get("country") or "", "website": p.get("website_url") or "", "phone": p.get("phone") or "",
            "email": p.get("email") or "", "maps_url": p.get("maps_url") or "",
            "rating": p.get("rating"), "review_count": p.get("review_count"),
            "social_profiles": [{"platform": s["platform"], "url": s["profile_url"], "confidence": s["confidence"]}
                                for s in social if s["confidence"] in ("high", "medium")],
            "data_collected": built[:10]}


def _summary(p: dict, ds: dict, recs: list[dict], audience: str) -> str:
    c = ds.get("issue_counts", {})
    where = ", ".join(x for x in (p.get("area"), p.get("city")) if x)
    who = f"{p['name']}{f' ({where})' if where else ''}"
    top = [r["issue"] for r in recs if r["priority"] == "High"][:2] or [r["issue"] for r in recs][:2]
    parts = [f"We reviewed the website, social media presence and the tools visible online for {who}."]
    if sum(c.values()):
        parts.append(f"We found {c.get('critical', 0) + c.get('high', 0)} important, {c.get('medium', 0)} medium "
                     f"and {c.get('low', 0)} minor issue(s).")
    else:
        parts.append("We did not find issues worth raising.")
    if top:
        parts.append("Most important: " + "; ".join(t.rstrip(".") for t in top) + ".")
    gaps = [r["section"] for r in ds.get("completeness", []) if r["status"] in ("failed", "not_run", "skipped")]
    if gaps:
        parts.append(f"Some checks could not be completed ({', '.join(gaps).lower()}); see Evidence & limitations.")
    if audience == "owner":
        parts.append("Post-level social media results (reach, engagement) were not available to us from outside.")
    return " ".join(parts)


def _website(ds: dict, a1: dict) -> dict:
    items = [_rec(i) for i in ds.get("issues", []) if "website_expert" in i.get("agents", []) and i["status"] in USABLE]
    m = a1.get("metrics") or {}
    return {"status": a1.get("status", "not run"), "pages_inspected": len(a1.get("pages") or {}),
            "pages": a1.get("pages") or {}, "issues": items,
            "by_severity": a1.get("by_severity") or {},
            "metrics": {"html_seconds": round((m.get("home_html_ms") or 0) / 1000, 1),
                        "main_content_seconds": round(((m.get("desktop") or {}).get("lcp_ms") or 0) / 1000, 1),
                        "page_weight_mb": round(((m.get("desktop") or {}).get("bytes") or 0) / 1e6, 1),
                        "phone_overflow": (m.get("mobile") or {}).get("overflow_px"),
                        "phone_cta_first_screen": (m.get("mobile") or {}).get("cta_above_fold")},
            "screenshots": list((a1.get("screenshots") or {}).keys())}


def _social(ds: dict, social: list[dict], a2: dict) -> dict:
    items = [_rec(i) for i in ds.get("issues", []) if "social_media_expert" in i.get("agents", []) and i["status"] in USABLE]
    return {"mode": "presence only", "profiles": social, "issues": items,
            "not_available": (a2.get("overall_limitations") or ["Social media audit has not run"])[0]}


def _automation(a4: dict, audience: str) -> dict:
    opps = []
    for o in a4.get("opportunities") or []:
        cap = o["techdeva_capability"]
        item = {"problem": o["business_problem"], "suggestion": o["recommended_solution"],
                "tested": False, "impact_measured": False}
        if audience == "internal":
            item["techdeva"] = cap
        opps.append(item)
    tools = a4.get("existing_automation") or []
    return {"mode": "audit only (nothing was run on the business's systems)",
            "tools_in_use": [t["name"] for t in tools if t["kind"] != "builder"],
            "competitor_tools": [t["name"] for t in tools if t.get("competitor")] if audience == "internal" else [],
            "opportunities": opps, "status": a4.get("evaluation_status", "not run")}


def _opportunities(a4: dict, recs: list[dict], ds: dict) -> dict:
    fit = [o for o in (a4.get("opportunities") or []) if o["techdeva_capability"]["id"]]
    existing = [o for o in fit if o["techdeva_capability"]["status"] == "existing"]
    pains = [r["issue"] for r in recs if r["priority"] in ("High", "Medium")][:3]
    first = (existing[0]["business_problem"] if existing else (pains[0] if pains else ""))
    return {"pain_points_seen": pains,
            "techdeva_modules": [{"module": o["techdeva_capability"]["name"], "offer": o["techdeva_capability"]["offer"],
                                  "because": o["business_problem"]} for o in fit],
            "competitor_tools": (ds.get("_competitors") or []),
            "suggested_first_topic": first,
            "note": "These are opportunities seen from outside, not confirmed needs. Confirm with the owner before proposing."}


def build(profile: dict, dataset: dict, summaries: dict, social: list[dict], audience: str) -> dict:
    if audience not in AUDIENCES:
        raise ValueError(f"audience must be one of {AUDIENCES}")
    built = datetime.now(UTC).isoformat(timespec="seconds")
    issues = [i for i in dataset.get("issues", []) if i["status"] in USABLE]
    if audience == "owner":
        issues = [i for i in issues if i["status"] != "requires_review"]  # our own doubts stay internal
    recs = sorted((_rec(i) for i in issues), key=lambda r: (PRIORITY_ORDER.index(r["priority"]), not r["confirmed"]))
    a1, a2, a4 = (summaries.get(k) or {} for k in ("website_expert", "social_media_expert", "automation_runner"))
    left_out = [i["issue"] for i in dataset.get("issues", []) if i["status"] not in USABLE]
    pkg = {
        "report_type": "owner_summary" if audience == "owner" else "internal_sales", "audience": audience,
        "language": "en", "generated_at": built, "agent": "reporting",
        "sections": {
            "overview": _overview(profile, social, built),
            "executive_summary": _summary(profile, dataset, recs, audience),
            "website": _website(dataset, a1),
            "social": _social(dataset, social if audience == "internal" else
                              [x for x in social if x["confidence"] in ("high", "medium")], a2),
            "automation": _automation(a4, audience),
            "recommendations": recs,
            "evidence_limitations": {
                "completeness": dataset.get("completeness", []),
                "contradictions": dataset.get("contradictions", []),
                "left_out": left_out,
                "limitations": [x for s in summaries.values() for x in (s.get("limitations") or s.get("overall_limitations") or [])],
                "sources": {"website_pages": a1.get("pages") or {}, "agents": [i["agent_name"] for i in dataset.get("inputs", [])]},
            },
        },
    }
    if audience == "owner":
        pkg["sections"]["techdeva_pitch"] = pitch.owner_pitch(profile, a4)
    if audience == "internal":
        pkg["sections"]["pitch"] = pitch.internal_pitch(profile, a4)
        dataset = {**dataset, "_competitors": [t["name"] for t in (a4.get("existing_automation") or []) if t.get("competitor")]}
        pkg["sections"]["opportunities"] = _opportunities(a4, recs, dataset)
        pkg["sections"]["needs_verification"] = [r for r in recs if not r["confirmed"]]
    return pkg
