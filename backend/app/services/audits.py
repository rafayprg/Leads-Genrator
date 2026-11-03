"""Runs the built agents' tasks from the audit queue: Agents 1 (website), 3 (social finder),
2 (social, presence only) and 4 (automation, audit-only mode).

Full Main Agent orchestration (dependencies, parallel runs, Agent 2/4/5/6) is Phase 8; until then this
worker runs the tasks of built agents one by one (Agent 2 waits for Agent 3) and leaves the others pending.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from ..agents.automation import runner as automation_runner
from ..agents.findings import Finding
from ..ai import client as ai_client
from ..ai import writer as ai_writer
from ..agents.main_agent import score as opportunity
from ..agents.organizer import organize as organizer
from ..agents.reporting import builder as report_builder
from ..agents.reporting import render as report_render
from ..agents.social import expert as social_expert
from ..agents.social import finder
from ..agents.social.profiles import parse as parse_profile
from ..agents.website import agent as website_agent
from ..config import DATA_DIR
from ..security import get_limits
from ..models import (AgentName, AgentTask, AuditFinding, AuditJob, Business, Confidence, DataSource, JobStatus,
                      Report, SocialProfile, TaskStatus, Verification)

ARTIFACTS_DIR = DATA_DIR / "artifacts"
REPORTS_DIR = DATA_DIR / "reports"
IDLE_SECONDS = 3
WORKER_THREADS = 3
RETRY_BACKOFF_SECONDS = 30  # wait 30 s, then 60 s, ... before trying a failed task again
# heavy agents (they start Chromium) run one at a time; others share the worker threads
AGENT_LIMITS = {AgentName.WEBSITE_EXPERT: 1, AgentName.REPORTING: 1}
FINISHED = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED}

AuditFn = Callable[..., website_agent.WebsiteAudit]
FinderFn = Callable[..., finder.SocialDiscovery]
AutomationFn = Callable[..., automation_runner.AutomationReview]
# an agent may only start when these agents of the same audit have finished
DEPENDS_ON = {
    AgentName.SOCIAL_MEDIA_EXPERT: (AgentName.SOCIAL_MEDIA_FINDER,),
    AgentName.DATA_ORGANIZER: (AgentName.WEBSITE_EXPERT, AgentName.SOCIAL_MEDIA_FINDER,
                               AgentName.SOCIAL_MEDIA_EXPERT, AgentName.AUTOMATION_RUNNER),
    AgentName.REPORTING: (AgentName.DATA_ORGANIZER,),
    AgentName.MAIN: (AgentName.WEBSITE_EXPERT, AgentName.SOCIAL_MEDIA_FINDER, AgentName.SOCIAL_MEDIA_EXPERT,
                     AgentName.AUTOMATION_RUNNER, AgentName.DATA_ORGANIZER, AgentName.REPORTING),
}
SPECIALISTS = (AgentName.WEBSITE_EXPERT, AgentName.SOCIAL_MEDIA_FINDER, AgentName.SOCIAL_MEDIA_EXPERT,
               AgentName.AUTOMATION_RUNNER)


@dataclass
class Outcome:
    output: dict
    skipped: bool = False
    findings: list[Finding] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


def artifacts_for(business: Business, job_id: int) -> Path:
    return ARTIFACTS_DIR / business.business_id / f"job-{job_id}"


def refresh_job_status(job: AuditJob) -> None:
    """completed = every task finished; partial = some finished, others still waiting (their agents come later)."""
    states = [t.status for t in job.tasks]
    if any(s == TaskStatus.RUNNING for s in states):
        job.status = JobStatus.RUNNING
    elif all(s in FINISHED for s in states):
        job.status = JobStatus.PARTIAL if any(s == TaskStatus.FAILED for s in states) else JobStatus.COMPLETED
        job.completed_at = job.completed_at or _now()
    elif any(s in FINISHED for s in states):
        job.status = JobStatus.PARTIAL
    else:
        job.status = JobStatus.QUEUED


# ------------------------------------------------------------------ Agent 1
def website_work(audit_fn: AuditFn, use_browser: bool):
    def work(session: Session, task: AgentTask, b: Business) -> Outcome:
        limits = get_limits(session)
        result = audit_fn(b.website_url, b.industry or "", shots_dir=artifacts_for(b, task.audit_job_id),
                          use_browser=use_browser, max_pages=limits["website_max_pages"],
                          max_links=limits["website_max_links"])
        if result.status != "skipped":  # Agent 1 is the one who verifies the website collected by Apify
            for ds in session.scalars(select(DataSource).where(DataSource.business_id == b.id,
                                                               DataSource.field == "website_url")):
                ds.verification_status = (Verification.VERIFIED if result.status != "failed"
                                          else Verification.REQUIRES_REVIEW)
        return Outcome(result.summary(), result.status == "skipped", result.findings)
    return work


# ------------------------------------------------------------------ Agent 3
def save_profiles(session: Session, b: Business, found: finder.SocialDiscovery) -> None:
    """Upsert by the cleaned profile URL; links that are not profiles are kept but marked, never deleted."""
    by_url: dict[str, SocialProfile] = {}
    for row in list(b.social_profiles):
        p = parse_profile(row.profile_url)
        if p is None:
            row.verification_status, row.confidence = Verification.REQUIRES_REVIEW, Confidence.LOW
            row.evidence = list(row.evidence or []) + ["Not a profile link (share/post/builder link) — ignored by Agent 3"]
            continue
        if p.url in by_url:  # same account stored twice under different spellings
            b.social_profiles.remove(row)
            continue
        by_url[p.url] = row
    session.flush()  # delete duplicates before renaming rows to the clean URL (unique per business)
    for prof in found.profiles:
        row = by_url.get(prof["profile_url"])
        if row is None:
            row = SocialProfile(platform=prof["platform"], profile_url=prof["profile_url"])
            b.social_profiles.append(row)
        row.platform, row.profile_url, row.username = prof["platform"], prof["profile_url"], prof["handle"]
        row.confidence, row.verification_status = Confidence(prof["confidence"]), Verification(prof["verification"])
        row.evidence, row.last_checked_at = prof["evidence"], _now()


def social_work(finder_fn: FinderFn):
    def work(session: Session, task: AgentTask, b: Business) -> Outcome:
        known = [p.profile_url for p in b.social_profiles]
        found = finder_fn(b.name, b.website_url, known)
        save_profiles(session, b, found)
        return Outcome(found.summary(), found.status == "skipped")
    return work


# ------------------------------------------------------------------ Agent 2 (presence only) and Agent 4 (audit only)
def social_expert_work():
    def work(session: Session, task: AgentTask, b: Business) -> Outcome:
        finder_ran = any(t.agent_name == AgentName.SOCIAL_MEDIA_FINDER and t.status == TaskStatus.COMPLETED
                         for t in task.audit_job.tasks) or any(p.last_checked_at for p in b.social_profiles)
        profiles = [{"platform": p.platform, "profile_url": p.profile_url, "confidence": str(p.confidence),
                     "evidence": p.evidence or []} for p in b.social_profiles]
        res = social_expert.assess(b.industry or "", profiles, finder_ran)
        return Outcome(res.summary(), findings=res.findings)
    return work


def automation_work(review_fn: AutomationFn):
    def work(session: Session, task: AgentTask, b: Business) -> Outcome:
        res = review_fn(b.website_url, b.industry or "")
        return Outcome(res.summary(), res.status == "skipped", res.findings)
    return work


# ------------------------------------------------------------------ Agent 5 (data organizer)
def latest_outputs(session: Session, business_id: int) -> list[organizer.AgentOutput]:
    """Latest finished output of each specialist agent for this business (from any audit job)."""
    outs = []
    for agent in SPECIALISTS:
        t = session.scalars(select(AgentTask).join(AuditJob).where(
            AuditJob.business_id == business_id, AgentTask.agent_name == agent,
            AgentTask.status.in_([TaskStatus.COMPLETED, TaskStatus.SKIPPED])).order_by(AgentTask.id.desc()).limit(1)).first()
        if t is None:
            continue
        rows = session.scalars(select(AuditFinding).where(AuditFinding.agent_task_id == t.id)).all()
        outs.append(organizer.AgentOutput(
            agent=str(agent), task_id=t.id, status=str(t.status), finished_at=t.completed_at,
            summary=t.output_data or {},
            findings=[{"id": f.id, "category": f.category, "title": f.title, "description": f.description,
                       "severity": str(f.severity), "evidence": f.evidence, "source_url": f.source_url,
                       "confidence": str(f.confidence), "recommendation": f.recommendation,
                       "verification_status": str(f.verification_status), "observed_at": f.observed_at}
                      for f in rows]))
    return outs


def organizer_work():
    def work(session: Session, task: AgentTask, b: Business) -> Outcome:
        outputs = latest_outputs(session, b.id)
        profile = {"business_id": b.business_id, "phone": b.phone, "website_url": b.website_url, "city": b.city,
                   "category": b.category}
        if not outputs:
            return Outcome({"agent": "data_organizer", "business_id": b.business_id,
                            "limitations": ["No specialist agent has finished for this business yet"]}, skipped=True)
        return Outcome(organizer.organize(profile, outputs))
    return work


# ------------------------------------------------------------------ Agent 6 (reporting)
def _latest_done(session: Session, business_id: int, agent: AgentName) -> AgentTask | None:
    return session.scalars(select(AgentTask).join(AuditJob).where(
        AuditJob.business_id == business_id, AgentTask.agent_name == agent,
        AgentTask.status == TaskStatus.COMPLETED).order_by(AgentTask.id.desc()).limit(1)).first()


@dataclass
class ReportInputs:
    organizer_task_id: int
    profile: dict
    dataset: dict
    summaries: dict
    social: list
    shots: Path | None


def report_inputs(session: Session, b: Business) -> ReportInputs | None:
    """Everything Agent 6 needs: Agent 5's dataset + the exact agent outputs Agent 5 used."""
    org = _latest_done(session, b.id, AgentName.DATA_ORGANIZER)
    if org is None or not org.output_data or "issues" not in org.output_data:
        return None
    dataset = org.output_data
    used = {i["agent_name"]: i["task_id"] for i in dataset.get("inputs", [])}
    tasks = {name: session.get(AgentTask, tid) for name, tid in used.items()}
    summaries = {name: (t.output_data or {}) for name, t in tasks.items() if t is not None}
    social = [{"platform": p.platform, "profile_url": p.profile_url, "confidence": str(p.confidence)}
              for p in b.social_profiles]
    profile = {"name": b.name, "business_id": b.business_id, "industry": b.industry, "category": b.category,
               "city": b.city, "area": b.area, "country": b.country, "phone": b.phone, "email": b.email,
               "website_url": b.website_url, "maps_url": b.maps_url, "rating": b.rating,
               "review_count": b.review_count}
    web = tasks.get("website_expert")
    return ReportInputs(org.id, profile, dataset, summaries, social, artifacts_for(b, web.audit_job_id) if web else None)


def _localise(session: Session, pkg: dict, lang: str, detail: str, ai_on: bool, cap: int, notes: list) -> dict:
    """8.5 report settings (language, detail) + 7.5 AI wording. Falls back to the template on any AI problem."""
    pkg = {**pkg, "language": lang, "detail": detail, "wording": "template"}
    sec = pkg["sections"]
    if detail == "summary":
        sec["recommendations"] = sec["recommendations"][:5]
        sec["website"]["issues"] = []
    if ai_on and pkg["audience"] == "owner":
        text = ai_writer.summary(session, pkg, lang, cap)
        if text:
            sec["executive_summary"], pkg["wording"] = text, "ai"
        else:
            notes.append("AI summary not used (no answer, limit reached or failed the fact check); template kept")
    if lang == "roman_urdu":
        lines = [x for r in sec["recommendations"] for x in (r["issue"], r["why"], r["fix"])]
        tp = sec.get("techdeva_pitch")
        pitch_keys = [k for k in ("headline", "intro", "example", "care", "control", "cta") if tp and tp[k]]
        pitch_lines = [tp[k] for k in pitch_keys] + [x for b in tp["benefits"] for x in (b["because"], b["what"])] if tp else []
        if pkg["wording"] != "ai":
            lines.append(sec["executive_summary"])
        done = ai_writer.translate(session, lines + pitch_lines, cap)
        if pitch_lines:
            got = done[len(lines):]
            done = done[:len(lines)]
            tp = {**tp, **dict(zip(pitch_keys, got)),
                  "benefits": [{**b, "because": got[len(pitch_keys) + 2 * i], "what": got[len(pitch_keys) + 2 * i + 1]}
                               for i, b in enumerate(tp["benefits"])]}
            sec["techdeva_pitch"] = tp
        if pkg["wording"] != "ai":
            sec["executive_summary"] = done.pop()
        for i, r in enumerate(sec["recommendations"]):
            r["issue"], r["why"], r["fix"] = done[3 * i:3 * i + 3]
        if done == lines:
            notes.append("Roman Urdu translation not available this time; English text kept")
    return pkg


def reporting_work(make_pdf: bool = True):
    def work(session: Session, task: AgentTask, b: Business) -> Outcome:
        inp = report_inputs(session, b)
        if inp is None:
            return Outcome({"agent": "reporting", "limitations": ["Agent 5 has not built a summary yet"]}, skipped=True)
        profile, dataset, summaries, social, shots = inp.profile, inp.dataset, inp.summaries, inp.social, inp.shots
        folder = REPORTS_DIR / b.business_id
        folder.mkdir(parents=True, exist_ok=True)
        made, notes = [], []
        from ..ai_routes import get_report_settings  # local: ai_routes imports security which imports models
        rs = get_report_settings(session)
        cap = get_limits(session)["ai_calls_per_day_max"]
        ai_on = rs["ai_wording"] and ai_client.config().ready
        plans = [("owner", lang) for lang in rs["languages"]] + [("internal", "en")]
        for audience, lang in plans:
            if lang == "roman_urdu" and not ai_on:
                notes.append("Roman Urdu report skipped: it needs the AI provider (Settings → AI provider)")
                continue
            pkg = _localise(session, report_builder.build(profile, dataset, summaries, social, audience),
                            lang, rs["detail"], ai_on, cap, notes)
            version = 1 + len(session.scalars(select(Report.id).where(
                Report.business_id == b.id, Report.report_type == pkg["report_type"],
                Report.language == lang)).all())
            suffix = "" if lang == "en" else f"-{lang}"
            html_path = folder / f"{pkg['report_type']}{suffix}-v{version}.html"
            html_text = report_render.html(pkg, shots)
            html_path.write_text(html_text, encoding="utf-8")
            problem = report_render.pdf(html_text, html_path.with_suffix(".pdf")) if make_pdf else "PDF switched off"
            if problem:
                notes.append(problem)
            rep = Report(business_id=b.id, audit_job_id=task.audit_job_id, version=version,
                         report_type=pkg["report_type"], language=lang, status="ready", storage_path=str(html_path))
            session.add(rep)
            session.flush()
            made.append({"report_id": rep.id, "report_type": pkg["report_type"], "version": version,
                         "language": lang, "wording": pkg["wording"], "pdf": not problem,
                         "recommendations": len(pkg["sections"]["recommendations"])})
        if not ai_on:
            notes.append("Wording is template-based (AI provider not set up or switched off)")
        return Outcome({"agent": "reporting", "reports": made, "built_from_organizer_task": inp.organizer_task_id,
                        "settings": rs, "limitations": list(dict.fromkeys(notes))})
    return work


# ------------------------------------------------------------------ Main Agent (final step of a full audit)
RECORD_FIELDS = {AgentName.WEBSITE_EXPERT: "website_audit", AgentName.SOCIAL_MEDIA_FINDER: "social_discovery",
                 AgentName.SOCIAL_MEDIA_EXPERT: "social_audit", AgentName.AUTOMATION_RUNNER: "automation_evaluation",
                 AgentName.DATA_ORGANIZER: "data_quality", AgentName.REPORTING: "reporting"}


def main_work():
    def work(session: Session, task: AgentTask, b: Business) -> Outcome:
        statuses = {RECORD_FIELDS[t.agent_name]: str(t.status) for t in task.audit_job.tasks if t.agent_name in RECORD_FIELDS}
        failed = [k for k, v in statuses.items() if v == "failed"]
        inp = report_inputs(session, b)
        summaries = inp.summaries if inp else {}
        profile = {"phone": b.phone, "website_url": b.website_url, "email": b.email, "city": b.city,
                   "category": b.category, "phone_type": (b.details or {}).get("phone_type"),
                   "whatsapp": ((b.details or {}).get("leadgen") or {}).get("whatsapp")}
        opp = opportunity.score(profile, inp.dataset if inp else None, summaries)
        opp["at"] = _now().isoformat(timespec="seconds")
        from ..ai_routes import get_report_settings
        if get_report_settings(session)["ai_wording"] and ai_client.config().ready and inp:
            a4 = summaries.get("automation_runner") or {}
            facts = {"business": b.name, "industry": b.industry, "score": opp["score"], "band": opp["band"],
                     "score_reasons": {k: v["why"] for k, v in opp["breakdown"].items()},
                     "top_issues": [{"issue": i["issue"], "confirmed": i["status"] == "verified"}
                                    for i in inp.dataset.get("issues", [])[:6]],
                     "techdeva_modules_that_fit": [o["techdeva_capability"]["name"] for o in a4.get("opportunities") or []
                                                   if o["techdeva_capability"]["status"] == "existing"],
                     "already_uses": [t["name"] for t in a4.get("existing_automation") or [] if t.get("competitor")]}
            note = ai_writer.sales_note(session, facts, get_limits(session)["ai_calls_per_day_max"])
            if note:
                opp["ai_note"] = note
        b.details = {**(b.details or {}), "opportunity": opp}
        reports = [r.id for r in session.scalars(select(Report).where(Report.audit_job_id == task.audit_job_id))]
        return Outcome({"agent": "main", "business_id": b.business_id, "business_profile": b.name,
                        "statuses": statuses, "overall_audit_status": "partial" if failed else "completed",
                        "failed_parts": failed, "opportunity": opp, "reports": reports,
                        "rule": "Estimates are never presented as verified facts; see each report's evidence section."})
    return work


def retry_task(session: Session, task_id: int) -> AgentTask | None:
    """Give a failed task a fresh set of attempts (used by the Agent Monitor's Retry button)."""
    t = session.get(AgentTask, task_id)
    if t is None or t.status != TaskStatus.FAILED:
        return None
    t.status, t.attempt_count, t.error_message = TaskStatus.PENDING, 0, None
    t.input_data = {k: v for k, v in (t.input_data or {}).items() if k != "retry_after"}
    refresh_job_status(t.audit_job)
    session.commit()
    return t


# ------------------------------------------------------------------ shared task runner
def run_task(task_id: int, make_session: sessionmaker, work: Callable[[Session, AgentTask, Business], Outcome]) -> None:
    session = make_session()
    try:
        # claim atomically: if two worker threads pick the same task, only one UPDATE matches
        claimed = session.execute(update(AgentTask).where(
            AgentTask.id == task_id, AgentTask.status == TaskStatus.PENDING).values(
            status=TaskStatus.RUNNING, started_at=_now(), attempt_count=AgentTask.attempt_count + 1)).rowcount
        session.commit()
        if not claimed:
            return
        task = session.get(AgentTask, task_id)
        session.refresh(task)
        job = task.audit_job
        b = session.get(Business, job.business_id)
        job.started_at = job.started_at or _now()
        refresh_job_status(job)
        session.commit()
        try:
            out = work(session, task, b)
        except Exception as exc:  # agent crash: retry a few times, then give up with the reason
            session.rollback()
            task = session.get(AgentTask, task_id)
            task.error_message = f"{type(exc).__name__}: {exc}"[:2000]
            task.status = TaskStatus.PENDING if task.attempt_count < task.max_attempts else TaskStatus.FAILED
            wait = RETRY_BACKOFF_SECONDS * task.attempt_count
            task.input_data = {**(task.input_data or {}),
                               "retry_after": datetime.fromtimestamp(_now().timestamp() + wait, UTC).isoformat()}
            refresh_job_status(task.audit_job)
            session.commit()
            return
        for f in out.findings:
            session.add(AuditFinding(
                business_id=b.id, agent_task_id=task.id, category=f.category, title=f.title[:300],
                description=f.impact or None, severity=f.severity, evidence=f.evidence,
                source_url=f.source_url or None, confidence=f.confidence, recommendation=f.recommendation,
                verification_status=f.verification, observed_at=_now()))
        task.output_data = out.output
        task.status = TaskStatus.SKIPPED if out.skipped else TaskStatus.COMPLETED
        task.error_message, task.completed_at = None, _now()
        refresh_job_status(job)
        session.commit()
    finally:
        session.close()


def run_website_task(task_id: int, make_session: sessionmaker, audit_fn: AuditFn = website_agent.audit,
                     use_browser: bool = True) -> None:
    run_task(task_id, make_session, website_work(audit_fn, use_browser))


def run_social_task(task_id: int, make_session: sessionmaker, finder_fn: FinderFn = finder.find) -> None:
    run_task(task_id, make_session, social_work(finder_fn))


def _ready(task: AgentTask) -> bool:
    """Dependencies inside the same audit job must be finished (or not part of this job)."""
    needs = DEPENDS_ON.get(task.agent_name, ())
    return all(t.status in FINISHED for t in task.audit_job.tasks if t.agent_name in needs)


def _waiting_for_retry(task: AgentTask) -> bool:
    at = (task.input_data or {}).get("retry_after")
    return bool(at) and datetime.fromisoformat(at) > _now()


def ready_tasks(session: Session, agents: list[AgentName], limit: int = 200) -> list[AgentTask]:
    pending = session.scalars(select(AgentTask).join(AuditJob).where(
        AgentTask.agent_name.in_(agents), AgentTask.status == TaskStatus.PENDING,
        AuditJob.status != JobStatus.FAILED).order_by(AgentTask.id).limit(limit)).all()
    return [t for t in pending if _ready(t) and not _waiting_for_retry(t)]


def next_task(session: Session, agents: list[AgentName]) -> AgentTask | None:
    ready = ready_tasks(session, agents)
    return ready[0] if ready else None


def recover_running(session: Session) -> int:
    """A task left 'running' by a stopped server goes back to the queue (it counts as an attempt)."""
    stuck = session.scalars(select(AgentTask).where(AgentTask.status == TaskStatus.RUNNING)).all()
    for t in stuck:
        t.status = TaskStatus.PENDING if t.attempt_count < t.max_attempts else TaskStatus.FAILED
        t.error_message = "interrupted: the server restarted"
        refresh_job_status(t.audit_job)
    session.commit()
    return len(stuck)


class AuditWorker:
    def __init__(self, make_session: sessionmaker, audit_fn: AuditFn = website_agent.audit, use_browser: bool = True,
                 finder_fn: FinderFn = finder.find, automation_fn: AutomationFn = automation_runner.review,
                 make_pdf: bool = True, threads: int = WORKER_THREADS):
        self.make_session = make_session
        self.work = {AgentName.WEBSITE_EXPERT: website_work(audit_fn, use_browser),
                     AgentName.SOCIAL_MEDIA_FINDER: social_work(finder_fn),
                     AgentName.SOCIAL_MEDIA_EXPERT: social_expert_work(),
                     AgentName.AUTOMATION_RUNNER: automation_work(automation_fn),
                     AgentName.DATA_ORGANIZER: organizer_work(),
                     AgentName.REPORTING: reporting_work(make_pdf),
                     AgentName.MAIN: main_work()}
        self.threads_wanted = threads
        self._limits = {a: threading.Semaphore(n) for a, n in AGENT_LIMITS.items()}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.busy: dict[str, tuple[int, str]] = {}  # thread name -> (task id, agent) for the Agent Monitor

    def start(self) -> None:
        with self.make_session() as s:
            recover_running(s)
        for i in range(self.threads_wanted):
            t = threading.Thread(target=self._loop, name=f"audit-worker-{i + 1}", daemon=True)
            t.start()
            self._threads.append(t)

    def status(self) -> dict:
        return {"threads": [{"name": t.name, "alive": t.is_alive(),
                             "task": self.busy.get(t.name)} for t in self._threads],
                "limits": {str(a): n for a, n in AGENT_LIMITS.items()}}

    def wake(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 5) -> None:
        self._stop.set()
        self._wake.set()
        for t in self._threads:
            t.join(timeout)

    def _pick(self) -> tuple[int, AgentName, threading.Semaphore | None] | None:
        with self.make_session() as s:
            candidates = [(t.id, t.agent_name) for t in ready_tasks(s, list(self.work))]
        for tid, agent in candidates:
            sem = self._limits.get(agent)
            if sem is None or sem.acquire(blocking=False):
                return tid, agent, sem
        return None

    def _loop(self) -> None:
        name = threading.current_thread().name
        while not self._stop.is_set():
            picked = self._pick()
            if picked is None:
                self._wake.wait(IDLE_SECONDS)
                self._wake.clear()
                continue
            tid, agent, sem = picked
            self.busy[name] = (tid, str(agent))
            try:
                run_task(tid, self.make_session, self.work[agent])
            finally:
                self.busy.pop(name, None)
                if sem is not None:
                    sem.release()
                self._wake.set()  # a finished task may unblock others
