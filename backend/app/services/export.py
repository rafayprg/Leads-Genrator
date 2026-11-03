"""CSV / Excel export of businesses (Phase 1.7). Same filters as the All Leads page."""
from __future__ import annotations

import csv
import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.reporting import builder as report_builder
from ..models import Business, Report

COLUMNS = [
    ("business_id", "Business ID", 11), ("name", "Business", 34), ("phone", "Phone", 16), ("email", "Email", 26),
    ("website_url", "Website", 32), ("country", "Country", 8), ("city", "City", 14), ("area", "Area", 18),
    ("industry", "Industry", 12), ("category", "Category", 20), ("rating", "Rating", 7),
    ("review_count", "Reviews", 8), ("last_review_date", "Newest review", 12), ("maps_url", "Google Maps", 22),
    ("social", "Social links", 30), ("audit_status", "Audit", 10), ("website_issues", "Website issues", 10),
    ("verification_status", "Checked", 10), ("created_at", "Collected", 18),
]
HEAD_FILL = PatternFill("solid", fgColor="1F2937")


def _row(b: Business, audit_status: str, website_issues: int | str) -> dict:
    return {
        "business_id": b.business_id, "name": b.name, "phone": b.phone or "", "email": b.email or "",
        "website_url": b.website_url or "", "country": b.country, "city": b.city or "", "area": b.area or "",
        "industry": b.industry or "", "category": b.category or "", "rating": b.rating if b.rating is not None else "",
        "review_count": b.review_count if b.review_count is not None else "",
        "last_review_date": (b.details or {}).get("last_review_date", ""), "maps_url": b.maps_url or "",
        "social": "; ".join(p.profile_url for p in b.social_profiles), "audit_status": audit_status,
        "website_issues": website_issues, "verification_status": str(b.verification_status),
        "created_at": b.created_at.strftime("%Y-%m-%d %H:%M") if b.created_at else "",
    }


def rows(businesses: list[Business], issues: dict[int, int]) -> list[dict]:
    out = []
    for b in businesses:
        latest = max(b.audit_jobs, key=lambda j: j.id, default=None)
        out.append(_row(b, str(latest.status) if latest else "", issues.get(b.id, "")))
    return out


def to_csv(data: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label, _ in COLUMNS])
    for r in data:
        # a leading = + - @ would run as a formula in Excel/Sheets; prefix with ' to keep it plain text
        w.writerow(["'" + v if isinstance(v, str) and v[:1] in "=+-@" else v for v in (r[k] for k, _, _ in COLUMNS)])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel reads Arabic names correctly


def to_xlsx(data: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append([label for _, label, _ in COLUMNS])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
    for r in data:
        ws.append([r[k] for k, _, _ in COLUMNS])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("="):
                c.data_type = "s"  # scraped text must never run as an Excel formula
    for i, (key, _, width) in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
        if key in ("website_url", "maps_url"):
            for cell in ws.iter_cols(min_col=i, max_col=i, min_row=2):
                for c in cell:
                    if isinstance(c.value, str) and c.value.startswith(("http://", "https://")):
                        c.hyperlink = c.value
                        c.font = Font(color="1D4ED8", underline="single")
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ 7.4 sales sheet (one row per reported business)
SALES_COLUMNS = [
    ("business_id", "Business ID", 11), ("name", "Business", 30), ("phone", "Phone", 16), ("whatsapp", "WhatsApp", 16),
    ("website", "Website", 28), ("city", "City", 12), ("industry", "Industry", 11), ("report_date", "Report date", 11),
    ("high", "High", 6), ("medium", "Medium", 7), ("low", "Low", 6), ("top_issues", "Top issues", 50),
    ("first_topic", "Suggested first topic", 40), ("techdeva_modules", "TechDeva fit", 40),
    ("competitor_tools", "Already pays for", 20), ("social", "Social accounts", 10),
    ("to_confirm", "To confirm", 9), ("completeness", "Audit coverage", 16), ("score", "Score", 7),
    ("opener", "Call opener (AI, Roman Urdu)", 50), ("call_status", "Call status", 14), ("follow_up", "Follow-up", 12),
    ("report_html", "Report (HTML)", 30),
    ("report_pdf", "Report (PDF)", 30),
]
REPORT_LINK = "http://localhost:5190/api/reports/{id}/{kind}"


def sales_rows(session: Session) -> list[dict]:
    from .audits import report_inputs  # local import: audits imports this module's neighbours

    latest: dict[int, Report] = {}
    for r in session.scalars(select(Report).where(Report.report_type == "internal_sales", Report.language == "en")
                             .order_by(Report.id)):
        latest[r.business_id] = r
    from .sales import latest_status
    calls = latest_status(session, set(latest))
    rows = []
    for bid, rep in latest.items():
        b = session.get(Business, bid)
        inp = report_inputs(session, b) if b else None
        if inp is None:
            continue
        pkg = report_builder.build(inp.profile, inp.dataset, inp.summaries, inp.social, "internal")
        sec = pkg["sections"]
        counts = inp.dataset.get("issue_counts", {})
        rows.append({
            "business_id": b.business_id, "name": b.name, "phone": b.phone or "",
            "whatsapp": ((b.details or {}).get("leadgen") or {}).get("whatsapp") or "", "website": b.website_url or "",
            "city": b.city or "", "industry": b.industry or "", "report_date": rep.created_at.strftime("%Y-%m-%d"),
            "high": counts.get("critical", 0) + counts.get("high", 0), "medium": counts.get("medium", 0),
            "low": counts.get("low", 0),
            "top_issues": " · ".join(r["issue"] for r in sec["recommendations"][:3]),
            "first_topic": sec["opportunities"]["suggested_first_topic"],
            "techdeva_modules": " · ".join(f"{m['module']} ({m['offer']})" for m in sec["opportunities"]["techdeva_modules"]),
            "competitor_tools": ", ".join(sec["opportunities"]["competitor_tools"]),
            "social": len(sec["overview"]["social_profiles"]), "to_confirm": len(sec["needs_verification"]),
            "completeness": inp.dataset.get("overall_completeness", ""),
            "score": ((b.details or {}).get("opportunity") or {}).get("score", ""),
            "opener": (((b.details or {}).get("opportunity") or {}).get("ai_note") or {}).get("opener_roman_urdu", ""),
            "call_status": (calls.get(bid) or {}).get("status", "not called").replace("_", " "),
            "follow_up": str((calls.get(bid) or {}).get("follow_up_on") or ""),
            "report_html": REPORT_LINK.format(id=rep.id, kind="html"),
            "report_pdf": REPORT_LINK.format(id=rep.id, kind="pdf"),
        })
    rows.sort(key=lambda r: (-r["high"], -r["medium"], r["name"]))
    return rows


def _safe(v):
    return "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v


def sales_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label, _ in SALES_COLUMNS])
    for r in rows:
        w.writerow([_safe(r[k]) for k, _, _ in SALES_COLUMNS])
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


def sales_xlsx(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales sheet"
    ws.append([label for _, label, _ in SALES_COLUMNS])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = HEAD_FILL
    for r in rows:
        ws.append([r[k] for k, _, _ in SALES_COLUMNS])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if isinstance(c.value, str) and c.value.startswith("="):
                c.data_type = "s"
            elif isinstance(c.value, str) and c.value.startswith(("http://", "https://")):
                c.hyperlink = c.value
                c.font = Font(color="1D4ED8", underline="single")
    for i, (_, _, width) in enumerate(SALES_COLUMNS, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
