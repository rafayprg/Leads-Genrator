"""Agent 2 — Social Media Expert, PRESENCE-ONLY mode.

Decided 31 Oct 2026: no scraping of Instagram/Facebook. So this agent does not read posts, posting
frequency or engagement. It only judges what Agent 3 found: which official accounts exist, which are
missing, and which need a human check. Post analysis needs the business owner's authorised access later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...models import Confidence
from ..findings import C, Finding, S, V

LIMITATION = ("Posts, posting frequency and engagement were not analysed: there is no permitted data source "
              "(scraping declined on 31 Oct 2026). Possible later with the business owner's authorised "
              "Instagram/Facebook access.")
# industries where customers usually look at Instagram before booking
INSTAGRAM_FIRST = {"beauty", "clinics", "fitness", "academies", "restaurants", "veterinary"}


@dataclass
class SocialAssessment:
    status: str
    findings: list[Finding] = field(default_factory=list)
    platforms: list[dict] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: [LIMITATION])

    def summary(self) -> dict:
        return {"agent": "social_media_expert", "audit_status": self.status, "mode": "presence_only",
                "metrics_completeness": "none (no post data)", "platforms_analyzed": self.platforms,
                "issues_found": len(self.findings), "overall_limitations": self.limitations,
                "completed_at": datetime.now(UTC).isoformat(timespec="seconds")}


def assess(industry: str, profiles: list[dict], finder_ran: bool) -> SocialAssessment:
    """profiles: [{platform, profile_url, confidence, evidence}] as stored by Agent 3."""
    res = SocialAssessment("completed" if finder_ran else "partial")
    if not finder_ran:
        res.limitations.append("Agent 3 has not checked this business yet; used the links on record as they are")
    if not finder_ran and profiles:
        res.status = "skipped"
        res.limitations.append("Agent 3 has not checked these accounts yet, so nothing is judged")
        return res
    trusted = [p for p in profiles if p["confidence"] in (str(Confidence.HIGH), str(Confidence.MEDIUM))]
    doubtful = [p for p in profiles if p["confidence"] == str(Confidence.LOW)]
    res.platforms = [{"platform": p["platform"], "profile_url": p["profile_url"], "confidence": p["confidence"],
                      "posts_observed": None, "metrics_completeness": "none"} for p in trusted]
    platforms = {p["platform"] for p in trusted}
    if not trusted:
        res.findings.append(Finding(
            "social", "No official social media account found", S.MEDIUM,
            "Create (or link) an Instagram business account and show it on the website and Google Maps listing.",
            impact="People who check social media before contacting a business find nothing to trust.",
            evidence={"checked": "own website + links on record", "doubtful_accounts": [p["profile_url"] for p in doubtful]},
            confidence=C.MEDIUM, verification=V.INFERRED))
    elif industry in INSTAGRAM_FIRST and "instagram" not in platforms:
        res.findings.append(Finding(
            "social", "No Instagram account found", S.LOW,
            "Open an Instagram business account and link it from the website; it is where most customers in the Gulf and South Asia browse first.",
            impact="Fewer people discover the business or see its work before booking.",
            evidence={"found_platforms": sorted(platforms)}, confidence=C.MEDIUM, verification=V.INFERRED))
    if trusted and not any("own website" in " ".join(p.get("evidence") or []) for p in trusted):
        res.findings.append(Finding(
            "social", "Website does not link to the social accounts", S.LOW,
            "Add the Instagram/Facebook icons to the website footer and contact page.",
            impact="Visitors cannot easily see recent work or reviews on social media.",
            evidence={"accounts": [p["profile_url"] for p in trusted]}, confidence=C.MEDIUM, verification=V.INFERRED))
    if doubtful:
        res.findings.append(Finding(
            "social", f"{len(doubtful)} social account(s) need a manual check", S.LOW,
            "Open each link and confirm it belongs to this business before mentioning it to the owner.",
            impact="Talking about the wrong account in a sales call loses trust.",
            evidence={"accounts": [p["profile_url"] for p in doubtful]}, confidence=C.HIGH, verification=V.REQUIRES_REVIEW))
    return res
