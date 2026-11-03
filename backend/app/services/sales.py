"""Call tracking (latest status per lead), stale audits, and old report clean-up."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AgentName, AgentTask, AuditJob, Report, SalesNote, SalesStatus, TaskStatus

FINISHED = (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED)
REMOVED = "removed"


def latest_status(session: Session, business_ids: list[int] | set[int]) -> dict[int, dict]:
    """business id -> its newest sales note (status, note, follow-up date, who, when)."""
    if not business_ids:
        return {}
    newest = (select(SalesNote.business_id, func.max(SalesNote.id).label("id"))
              .where(SalesNote.business_id.in_(business_ids)).group_by(SalesNote.business_id).subquery())
    rows = session.scalars(select(SalesNote).join(newest, SalesNote.id == newest.c.id))
    return {n.business_id: note_out(n) for n in rows}


def note_out(n: SalesNote) -> dict:
    return {"id": n.id, "status": str(n.status), "note": n.note, "follow_up_on": n.follow_up_on, "by": n.by, "at": n.at}


def follow_ups_due(session: Session, today: date | None = None) -> list[int]:
    """Leads whose newest note asks for a follow-up today or earlier (today = this computer's local date,
    so a follow-up set for "today" in Karachi or Dubai is due from local midnight, not from UTC midnight)."""
    today = today or date.today()
    latest = latest_status(session, set(session.scalars(select(SalesNote.business_id).distinct())))
    return sorted(bid for bid, n in latest.items()
                  if n["status"] == SalesStatus.FOLLOW_UP and n["follow_up_on"] and n["follow_up_on"] <= today)


def _aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=UTC)  # SQLite gives naive UTC times


def last_full_audit(session: Session) -> dict[int, datetime]:
    """business id -> when its latest full audit (Main Agent step) finished."""
    rows = session.execute(select(AuditJob.business_id, func.max(AgentTask.completed_at))
                           .join(AgentTask, AgentTask.audit_job_id == AuditJob.id)
                           .where(AgentTask.agent_name == AgentName.MAIN, AgentTask.status.in_(FINISHED))
                           .group_by(AuditJob.business_id)).all()
    return {bid: _aware(at) for bid, at in rows if at}


def stale_ids(session: Session, days: int, now: datetime | None = None) -> list[int]:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=days)
    return sorted(bid for bid, at in last_full_audit(session).items() if at < cutoff)


def is_stale(finished_at: datetime | None, days: int, now: datetime | None = None) -> bool:
    at = _aware(finished_at)
    return bool(at and at < (now or datetime.now(UTC)) - timedelta(days=days))


# ------------------------------------------------------------------ storage
def _size(paths) -> int:
    return sum(p.stat().st_size for p in paths if p.is_file())


def storage(reports_dir: Path, artifacts_dir: Path) -> dict:
    mb = lambda n: round(n / 1e6, 1)  # noqa: E731
    return {"reports_mb": mb(_size(reports_dir.rglob("*"))) if reports_dir.exists() else 0,
            "screenshots_mb": mb(_size(artifacts_dir.rglob("*"))) if artifacts_dir.exists() else 0}


def old_report_versions(session: Session) -> list[Report]:
    """Every report except the newest version per business + type + language (those stay)."""
    keep = set(session.scalars(select(func.max(Report.id)).group_by(
        Report.business_id, Report.report_type, Report.language)))
    return list(session.scalars(select(Report).where(Report.id.not_in(keep), Report.status != REMOVED)))


def remove_old_reports(session: Session, reports_dir: Path) -> dict:
    """Delete the files of old report versions (HTML + PDF). Rows stay, marked 'removed', for the history."""
    root = reports_dir.resolve()
    freed, count = 0, 0
    for r in old_report_versions(session):
        base = Path(r.storage_path or "")
        for f in (base.with_suffix(".html"), base.with_suffix(".pdf")):
            if f.is_file() and f.resolve().is_relative_to(root):  # never touch anything outside data/reports
                freed += f.stat().st_size
                f.unlink()
        r.status = REMOVED
        count += 1
    session.commit()
    return {"reports_removed": count, "freed_mb": round(freed / 1e6, 1)}
