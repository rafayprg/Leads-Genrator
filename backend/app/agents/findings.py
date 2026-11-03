"""The finding every agent produces: issue + evidence + impact + severity + fix + confidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..models import Confidence, Severity, Verification


@dataclass(frozen=True)
class Finding:
    category: str            # availability, https, links, seo, mobile, performance, accessibility, conversion, ...
    title: str
    severity: Severity
    recommendation: str
    impact: str = ""
    evidence: dict = field(default_factory=dict)
    source_url: str = ""
    confidence: Confidence = Confidence.HIGH
    # VERIFIED = we observed it directly; INFERRED = a reasonable reading of what we saw
    verification: Verification = Verification.VERIFIED

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(severity=str(self.severity), confidence=str(self.confidence), verification=str(self.verification))
        return d


S, C, V = Severity, Confidence, Verification
