"""Background work on the laptop: one worker thread, a queue, and everything recorded in the database.

Redis/Celery replaces this in Phase 9; callers only use enqueue_* and the CollectionRun / AuditJob rows.
"""
from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..ingest import apify_maps, records
from ..models import AgentName, AgentTask, AuditJob, CollectionRun, JobStatus, TaskStatus

LOG_FLUSH_EVERY = 5
LOG_KEEP_LINES = 500
# agents that run for a business audit, in dependency order (Main Agent orchestration is Phase 8)
AUDIT_AGENTS = {
    "website": AgentName.WEBSITE_EXPERT,
    "social_finder": AgentName.SOCIAL_MEDIA_FINDER,
    "social": AgentName.SOCIAL_MEDIA_EXPERT,
    "automation": AgentName.AUTOMATION_RUNNER,
    "organizer": AgentName.DATA_ORGANIZER,
    "reporting": AgentName.REPORTING,
    "main": AgentName.MAIN,  # final step: central audit record + opportunity score
}

CollectFn = Callable[..., apify_maps.CollectResult]


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue_collection(session: Session, params: dict, requested_by: str) -> CollectionRun:
    run = CollectionRun(params=params, requested_by=requested_by, status=JobStatus.QUEUED,
                        log=[f"{_now():%H:%M:%S} queued"])
    session.add(run)
    session.commit()
    return run


def execute_collection(run_id: int, make_session: sessionmaker, collect: CollectFn = apify_maps.collect) -> None:
    """Run one collection end to end. Never raises: every failure ends up on the row."""
    session = make_session()
    try:
        run = session.get(CollectionRun, run_id)
        if run is None or run.status != JobStatus.QUEUED:
            return
        run.status, run.started_at = JobStatus.RUNNING, _now()
        session.commit()
        pending: list[str] = []

        def log(msg: str) -> None:
            pending.append(f"{_now():%H:%M:%S} {msg}")
            if len(pending) >= LOG_FLUSH_EVERY:
                flush()

        def flush() -> None:
            if pending:
                run.log = (run.log + pending)[-LOG_KEEP_LINES:]
                pending.clear()
                session.commit()

        p = run.params
        business_ids: list[int] = []

        def save_batch(batch: list, info: dict) -> None:
            """One city/industry finished: save its places now so they show up while the others still run."""
            saved = records.save(session, batch)
            business_ids.extend(i for i in saved.business_ids if i not in business_ids)
            run.actor_runs = [*run.actor_runs, info]
            run.spent_usd = round(run.spent_usd + info.get("cost_usd", 0), 4)
            run.records_found += len(batch)
            run.new_businesses += saved.new
            run.updated_businesses += saved.updated
            run.rejected = [*run.rejected, *({"name": n, "reason": why} for n, why in saved.rejected)]
            log(f"saved {info.get('city')} / {info.get('industry')}: {saved.new} new, {saved.updated} already known, "
                f"{len(saved.rejected)} rejected")
            flush()
            session.commit()

        result = collect([tuple(t) for t in p["targets"]], p["industries"], float(p["budget_usd"]),
                         int(p.get("per_search", 40)), log=log,
                         min_reviews=int(p.get("min_reviews", apify_maps.MIN_REVIEWS)),
                         max_reviews=int(p.get("max_reviews", apify_maps.MAX_REVIEWS)), on_batch=save_batch)
        log(f"done: {run.new_businesses} new, {run.updated_businesses} already known, {len(run.rejected)} rejected")
        flush()
        run.actor_runs = list(result.runs)  # includes runs that found nothing in the review range
        run.spent_usd = round(result.spent_usd, 4)
        run.problem = result.problem or None
        if result.problem:
            run.status = JobStatus.PARTIAL if result.records else JobStatus.FAILED
        else:
            run.status = JobStatus.COMPLETED
        if p.get("audit"):
            create_audit_jobs(session, business_ids, p["audit"], run.requested_by)
        run.completed_at = _now()
        session.commit()
    except Exception as exc:  # keep the worker alive; record what happened
        session.rollback()
        run = session.get(CollectionRun, run_id)
        if run is not None:
            run.status, run.problem, run.completed_at = JobStatus.FAILED, f"{type(exc).__name__}: {exc}", _now()
            run.log = run.log + [f"{_now():%H:%M:%S} ERROR {type(exc).__name__}: {exc}"]
            session.commit()
    finally:
        session.close()


def create_audit_jobs(session: Session, business_ids: list[int], configuration: dict,
                      requested_by: str, allow_parallel: bool = False, max_attempts: int = 3) -> list[AuditJob]:
    """Main Agent step B: queue an audit per business with one task per enabled agent.

    A business that already has a queued/running audit is skipped (no double work), unless allow_parallel
    (used when one agent is run by hand for one business).
    """
    agents = [a for key, a in AUDIT_AGENTS.items() if configuration.get(key, True)]
    # busy = some task of an earlier audit still waiting or running (a job can say "partial" meanwhile)
    busy = set() if allow_parallel else set(session.scalars(select(AuditJob.business_id).where(
        AuditJob.business_id.in_(business_ids),
        AuditJob.tasks.any(AgentTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING])))))
    jobs = []
    for bid in business_ids:
        if bid in busy:
            continue
        job = AuditJob(business_id=bid, requested_by=requested_by, configuration=configuration)
        job.tasks = [AgentTask(agent_name=a, status=TaskStatus.PENDING, max_attempts=max_attempts) for a in agents]
        session.add(job)
        jobs.append(job)
    session.commit()
    return jobs


def recover_stale(session: Session) -> int:
    """After a restart nothing is really running: mark leftovers failed instead of hanging forever."""
    stale = session.scalars(select(CollectionRun).where(CollectionRun.status == JobStatus.RUNNING)).all()
    for run in stale:
        run.status, run.problem, run.completed_at = JobStatus.FAILED, "stopped: the server restarted", _now()
    session.commit()
    return len(stale)


class Worker:
    """One thread, one job at a time, so two runs never spend Apify credit at once."""

    def __init__(self, make_session: sessionmaker, collect: CollectFn = apify_maps.collect):
        self.make_session, self.collect = make_session, collect
        self._q: queue.Queue[int | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        with self.make_session() as s:
            recover_stale(s)
            queued = s.scalars(select(CollectionRun.id).where(CollectionRun.status == JobStatus.QUEUED)).all()
        self._thread = threading.Thread(target=self._loop, name="collection-worker", daemon=True)
        self._thread.start()
        for rid in queued:
            self.submit(rid)

    def submit(self, run_id: int) -> None:
        self._q.put(run_id)

    def stop(self, timeout: float = 5) -> None:
        self._q.put(None)
        if self._thread:
            self._thread.join(timeout)

    def _loop(self) -> None:
        while True:
            rid = self._q.get()
            if rid is None:
                return
            execute_collection(rid, self.make_session, self.collect)
