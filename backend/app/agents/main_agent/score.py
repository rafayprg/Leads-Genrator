"""8.4 — Lead Opportunity Score (0-100). A RULE-BASED FIT SCORE, not a chance of buying.

Weights from the architecture document (tune them here once real call results exist):
  website opportunities 25 · social opportunities 25 · automation opportunities 30 ·
  business information completeness 10 · verified contact availability 10
More fixable problems that TechDeva can solve = more opportunity. A competitor tool already in use lowers it.
"""
from __future__ import annotations

WEIGHTS = {"website": 25, "social": 25, "automation": 30, "completeness": 10, "contact": 10}
BANDS = ((80, "High priority"), (60, "Medium-high"), (40, "Qualify further"), (0, "Lower priority"))
LABEL = "Rule-based fit score — not a probability of buying"


def _cap(v: float, top: int) -> int:
    return max(0, min(top, round(v)))


def _website(dataset: dict, a1: dict) -> tuple[int, str]:
    if not a1:
        return 0, "website not audited"
    if a1.get("status") == "failed":
        if any("dns lookup failed" in (x or "").lower() for x in a1.get("limitations") or []):
            return 0, "website could not be checked from here"
        return 15, "website did not load (big problem, but the business may be inactive)"
    sev = [i["severity"] for i in dataset.get("issues", []) if "website_expert" in i.get("agents", [])
           and i["status"] in ("verified", "requires_verification")]
    pts = sev.count("critical") * 10 + sev.count("high") * 8 + sev.count("medium") * 4 + sev.count("low") * 1
    return _cap(pts, WEIGHTS["website"]), f"{len(sev)} website issue(s)"


def _social(dataset: dict, a2: dict) -> tuple[int, str]:
    if not a2 or a2.get("audit_status") == "skipped":
        return 0, "social presence not checked"
    titles = " ".join(i["issue"].lower() for i in dataset.get("issues", []) if "social_media_expert" in i.get("agents", []))
    pts, why = 0, []
    if "no official social media account" in titles:
        pts, why = 20, ["no official account"]
    elif "no instagram account" in titles:
        pts, why = 12, ["no Instagram"]
    if "does not link to the social" in titles:
        pts += 5
        why.append("site does not link socials")
    return _cap(pts, WEIGHTS["social"]), ", ".join(why) or "social presence looks fine"


def _automation(a4: dict) -> tuple[int, str]:
    if not a4 or a4.get("evaluation_status") != "completed":
        return 0, "automation not checked"
    pts = 0
    for o in a4.get("opportunities") or []:
        status = o["techdeva_capability"]["status"]
        pts += 12 if status == "existing" else 6 if status == "to_confirm" else 2
    competitors = [t["name"] for t in a4.get("existing_automation") or [] if t.get("competitor")]
    if competitors:
        pts -= 10
    why = f"{len(a4.get('opportunities') or [])} gap(s)" + (f"; already uses {', '.join(competitors)}" if competitors else "")
    return _cap(pts, WEIGHTS["automation"]), why


def _completeness(profile: dict) -> tuple[int, str]:
    have = [k for k in ("phone", "website_url", "email", "city", "category") if profile.get(k)]
    return 2 * len(have), f"{len(have)}/5 details on record"


def _contact(profile: dict) -> tuple[int, str]:
    kind = (profile.get("phone_type") or "").lower()
    pts = {"mobile": 8, "landline/mobile": 7, "landline": 6, "call centre": 2, "toll-free": 2}.get(kind, 4 if profile.get("phone") else 0)
    if profile.get("whatsapp"):
        pts += 2
    return _cap(pts, WEIGHTS["contact"]), (kind or ("phone" if profile.get("phone") else "no phone")) + \
        (" + WhatsApp" if profile.get("whatsapp") else "")


def score(profile: dict, dataset: dict | None, summaries: dict) -> dict:
    dataset = dataset or {}
    parts = {
        "website": _website(dataset, summaries.get("website_expert") or {}),
        "social": _social(dataset, summaries.get("social_media_expert") or {}),
        "automation": _automation(summaries.get("automation_runner") or {}),
        "completeness": _completeness(profile),
        "contact": _contact(profile),
    }
    total = sum(p[0] for p in parts.values())
    band = next(name for floor, name in BANDS if total >= floor)
    return {"score": total, "band": band, "label": LABEL,
            "breakdown": {k: {"points": v[0], "out_of": WEIGHTS[k], "why": v[1]} for k, v in parts.items()}}
