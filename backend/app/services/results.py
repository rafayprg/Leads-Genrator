"""Audit Results: finished full audits as they complete, grouped into runs (one bulk click = one run).

A full audit is an AuditJob that has a Main Agent task; its output is the central audit record
(score, statuses, report ids). Only small columns are read for the run overview; the heavier
outputs are loaded just for the rows on screen.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AgentName, AgentTask, AuditJob, Business, Report, TaskStatus
from ..security import get_limits
from . import sales as sales_service

RECENT_JOBS = 3000  # how far back the page looks
SHOWN_RUNS = 12
FINISHED = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class JobInfo:
    id: int
    business_id: int
    requested_by: str
    created_at: datetime
    configuration: dict
    statuses: dict = field(default_factory=dict)  # agent -> status
    main_task: int | None = None
    main_done_at: datetime | None = None

    @property
    def finished(self) -> bool:
        return self.statuses.get(AgentName.MAIN) in FINISHED

    @property
    def active(self) -> bool:
        return any(s in (TaskStatus.PENDING, TaskStatus.RUNNING) for s in self.statuses.values())

    @property
    def failed_parts(self) -> int:
        return sum(1 for s in self.statuses.values() if s == TaskStatus.FAILED)

    @property
    def group(self) -> tuple:
        # bulk runs carry a run id; older jobs are grouped by who started them and the minute they started
        run = (self.configuration or {}).get("run")
        return ("run", run) if run else ("legacy", self.requested_by, self.created_at.strftime("%Y-%m-%d %H:%M"))


def _jobs(session: Session) -> list[JobInfo]:
    recent = (select(AuditJob.id).where(AuditJob.tasks.any(AgentTask.agent_name == AgentName.MAIN))
              .order_by(AuditJob.id.desc()).limit(RECENT_JOBS))
    rows = session.execute(
        select(AuditJob.id, AuditJob.business_id, AuditJob.requested_by, AuditJob.created_at, AuditJob.configuration,
               AgentTask.id, AgentTask.agent_name, AgentTask.status, AgentTask.completed_at)
        .select_from(AgentTask).join(AuditJob, AgentTask.audit_job_id == AuditJob.id)
        .where(AuditJob.id.in_(recent))).all()
    jobs: dict[int, JobInfo] = {}
    for jid, bid, by, created, cfg, tid, agent, st, done_at in rows:
        job = jobs.setdefault(jid, JobInfo(jid, bid, by, created, cfg or {}))
        job.statuses[agent] = st
        if agent == AgentName.MAIN:
            job.main_task, job.main_done_at = tid, done_at
    return sorted(jobs.values(), key=lambda j: j.id)


def _runs(jobs: list[JobInfo]) -> dict[str, dict]:
    groups: dict[tuple, list[JobInfo]] = defaultdict(list)
    for j in jobs:
        groups[j.group].append(j)
    runs = {}
    for members in groups.values():
        first = members[0]
        key = (first.configuration or {}).get("run") or f"g{first.id}"
        done = [j for j in members if j.finished]
        runs[key] = {
            "key": key, "label": first.configuration.get("run_label") or f"{len(members)} lead(s)",
            "requested_by": first.requested_by, "started_at": first.created_at,
            "total": len(members), "done": len(done), "active": sum(1 for j in members if j.active),
            "with_failed_parts": sum(1 for j in done if j.failed_parts),
            "finished_at": max((j.main_done_at for j in done if j.main_done_at), default=None)
            if len(done) == len(members) else None,
            "job_ids": {j.id for j in members},
        }
    return runs


def _ts(d: datetime | None) -> float:
    return d.timestamp() if d else 0.0  # works for SQLite (naive) and PostgreSQL (aware) values alike


def _report_rows(session: Session, ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    return {r.id: {"id": r.id, "type": r.report_type, "language": r.language,
                   "pdf": Path(r.storage_path or "").with_suffix(".pdf").is_file()}
            for r in session.scalars(select(Report).where(Report.id.in_(ids), Report.status != sales_service.REMOVED))}


def _issue_summary(organizer_output: dict | None) -> tuple[dict, list[dict]]:
    out = organizer_output or {}
    issues = sorted(out.get("issues") or [], key=lambda i: SEVERITY_ORDER.get(i.get("severity"), 9))
    top = [{"issue": i.get("issue", ""), "severity": i.get("severity", ""), "confirmed": i.get("status") == "verified"}
           for i in issues[:3]]
    return out.get("issue_counts") or {}, top


def results(session: Session, run: str | None = None, band: str | None = None, q: str | None = None,
            sort: str = "finished", limit: int = 100, sales: str | None = None) -> dict:
    jobs = _jobs(session)
    runs = _runs(jobs)
    if run is not None and run not in runs:
        run = None
    finished = [j for j in jobs if j.finished and (run is None or j.id in runs[run]["job_ids"])]
    if run is None:  # the latest audit per business
        latest: dict[int, JobInfo] = {}
        for j in finished:
            latest[j.business_id] = j
        finished = list(latest.values())

    mains = {t.audit_job_id: t.output_data or {} for t in session.scalars(
        select(AgentTask).where(AgentTask.id.in_([j.main_task for j in finished])))}
    businesses = {b.id: b for b in session.scalars(select(Business).where(
        Business.id.in_({j.business_id for j in finished})))}

    needle = (q or "").strip().lower()
    status = sales_service.latest_status(session, {j.business_id for j in finished})
    stale_days = get_limits(session)["audit_stale_days"]
    rows = []
    for j in finished:
        b = businesses.get(j.business_id)
        if b is None:
            continue
        opp = mains.get(j.id, {}).get("opportunity") or {}
        if band and opp.get("band") != band:
            continue
        if needle and needle not in " ".join(filter(None, [b.name, b.city, b.industry, b.category])).lower():
            continue
        if sales and (status.get(b.id, {}).get("status") or "not_called") != sales:
            continue
        rows.append((j, b, opp))
    key = (lambda r: (r[2].get("score") or -1, _ts(r[0].main_done_at))) if sort == "score" \
        else (lambda r: _ts(r[0].main_done_at))
    rows.sort(key=key, reverse=True)
    total = len(rows)
    rows = rows[:limit]

    shown = {j.id for j, _, _ in rows}
    organizer = {t.audit_job_id: t.output_data for t in session.scalars(select(AgentTask).where(
        AgentTask.audit_job_id.in_(shown), AgentTask.agent_name == AgentName.DATA_ORGANIZER))}
    reports = _report_rows(session, {rid for j in shown for rid in mains.get(j, {}).get("reports") or []})
    run_of = {jid: r["key"] for r in runs.values() for jid in r["job_ids"]}

    out = []
    for j, b, opp in rows:
        counts, top = _issue_summary(organizer.get(j.id))
        main = mains.get(j.id, {})
        note = opp.get("ai_note") or {}
        out.append({
            "job_id": j.id, "run": run_of.get(j.id), "finished_at": j.main_done_at,
            "business_pk": b.id, "business_id": b.business_id, "name": b.name, "city": b.city, "country": b.country,
            "owner_id": b.owner_id,
            "industry": b.industry or b.category, "website": b.website_url,
            "score": opp.get("score"), "band": opp.get("band"),
            "status": main.get("overall_audit_status") or str(j.statuses.get(AgentName.MAIN)),
            "failed_parts": main.get("failed_parts") or [],
            "issue_counts": counts, "top_issues": top,
            "opener_roman_urdu": note.get("opener_roman_urdu"), "opener_en": note.get("opener_en"),
            "reports": [reports[r] for r in main.get("reports") or [] if r in reports],
            "sales": status.get(b.id), "stale": sales_service.is_stale(j.main_done_at, stale_days),
        })

    shown_runs = sorted(runs.values(), key=lambda r: _ts(r["started_at"]), reverse=True)
    shown_runs = [{k: v for k, v in r.items() if k != "job_ids"} for r in shown_runs
                  if r["total"] > 1 or r["active"]][:SHOWN_RUNS]
    return {"runs": shown_runs, "run": run, "total": total, "results": out, "stale_days": stale_days,
            "active": sum(1 for j in jobs if j.active)}
