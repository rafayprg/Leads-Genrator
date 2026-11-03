"""HTTP routes. Thin: validation in schemas, work in ingest/services."""
from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .db import get_session
from .ingest import apify_maps, apify_tokens
from .ingest.gulf import COUNTRIES, INDUSTRIES
from .models import (AgentName, AgentTask, AuditFinding, AuditJob, Business, CollectionRun, JobStatus, Report, Role,
                     TaskStatus, User)
from .schemas import (AuditJobOut, AuditRequest, BusinessDetail, BusinessPage, Estimate, RunOut, SearchRequest,
                      AgentResultOut, ReportOut, SocialFinderOut, TokenIn, WebsiteAuditOut)
from .security import allow, client_ip, get_limits, log, require
from .services import audits, export, jobs

router = APIRouter()
EXPORT_MAX_ROWS = 50_000
ARTIFACT_NAMES = {"desktop.png", "mobile.png", "desktop.jpg", "mobile.jpg"}


def get_worker(request: Request) -> jobs.Worker:
    return request.app.state.worker


ADMIN = Depends(require(Role.ADMIN))   # spends money / changes keys
SALES = Depends(require(Role.SALES))   # downloads reports
EXPORT = Depends(allow("export"))
AUDITS = Depends(allow("start_audits"))
# every route below also needs a logged-in user (router dependency in main.py) -> viewers can read


def _check_daily_audits(session: Session, adding: int) -> None:
    cap = get_limits(session)["audits_per_day_max"]
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    done = session.scalar(select(func.count()).select_from(AuditJob).where(AuditJob.created_at >= start)) or 0
    if done + adding > cap:
        raise HTTPException(429, f"Daily audit limit reached ({done} of {cap} today). An admin can raise it in Settings.")


def _apify_spent_this_month(session: Session) -> float:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return float(session.scalar(select(func.coalesce(func.sum(CollectionRun.spent_usd), 0.0)).where(
        CollectionRun.created_at >= start)) or 0.0)


# ------------------------------------------------------------------ reference data
@router.get("/meta")
def meta() -> dict:
    return {
        "countries": {cc: {"name": c["name"], "region": c["region"], "cities": list(c["cities"])}
                      for cc, c in COUNTRIES.items()},
        "industries": {k: {"label": v["label"], "tier": v["tier"], "searches": len(v["search_terms"])}
                       for k, v in INDUSTRIES.items()},
        "apify": {"price_per_place": apify_maps.PRICE_PER_PLACE, "price_per_review": apify_maps.PRICE_PER_REVIEW,
                  "min_run_usd": apify_maps.MIN_RUN_USD},
    }


# ------------------------------------------------------------------ overview numbers
@router.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    def grouped(col, model) -> dict:
        return {str(k): n for k, n in session.execute(select(col, func.count()).select_from(model).group_by(col))}

    failed_tasks = session.scalar(select(func.count()).select_from(AgentTask).where(
        AgentTask.status == TaskStatus.FAILED)) or 0
    last = session.scalars(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(5)).all()
    sts = apify_tokens.all_status()
    return {
        "businesses": session.scalar(select(func.count()).select_from(Business)) or 0,
        "by_country": grouped(Business.country, Business),
        "by_industry": grouped(Business.industry, Business),
        "audits": grouped(AuditJob.status, AuditJob),
        "failed_tasks": failed_tasks,
        "searches": [{"id": r.id, "status": r.status, "created_at": r.created_at, "spent_usd": r.spent_usd,
                      "new_businesses": r.new_businesses, "targets": r.params.get("targets", []),
                      "industries": r.params.get("industries", [])} for r in last],
        "apify": {"accounts": len(sts), "credit_left_usd": apify_tokens.total_remaining(sts)},
    }


# ------------------------------------------------------------------ Apify accounts
@router.get("/apify/accounts")
def apify_accounts(fresh: bool = False) -> dict:
    sts = apify_tokens.all_status(fresh)
    return {"accounts": [s.as_dict() for s in sts], "credit_left_usd": apify_tokens.total_remaining(sts)}


@router.post("/apify/accounts", status_code=status.HTTP_201_CREATED)
def add_apify_account(body: TokenIn, request: Request, user: User = ADMIN,
                      session: Session = Depends(get_session)) -> dict:
    if body.token in apify_tokens.tokens():
        raise HTTPException(409, "This token is already added")
    st = apify_tokens.status(body.token, fresh=True)
    if not st.ok:
        raise HTTPException(400, f"{st.message} (not saved)")
    apify_tokens.add_token(body.token)
    log(session, user, "apify_account_added", f"…{body.token[-4:]}", {"username": st.username}, client_ip(request))
    return st.as_dict()


@router.delete("/apify/accounts/{last4}", status_code=status.HTTP_204_NO_CONTENT)
def remove_apify_account(last4: str, request: Request, user: User = ADMIN,
                         session: Session = Depends(get_session)) -> None:
    if len(last4) != 4 or not apify_tokens.remove_token(last4):
        raise HTTPException(404, "No account with those last 4 characters")
    log(session, user, "apify_account_removed", f"…{last4}", ip=client_ip(request))


# ------------------------------------------------------------------ lead searches (Apify collection)
def _estimate(body: SearchRequest) -> Estimate:
    searches = sum(len(INDUSTRIES[i]["search_terms"]) for i in body.industries) * len(body.targets)
    return Estimate(cities=len(body.targets), searches=searches, max_places=searches * body.per_search,
                    estimate_usd=apify_maps.estimate_usd(len(body.targets), body.industries, body.per_search),
                    budget_usd=body.budget_usd,
                    credit_left_usd=apify_tokens.total_remaining(apify_tokens.all_status()))


@router.post("/searches/estimate", response_model=Estimate)
def estimate(body: SearchRequest) -> Estimate:
    return _estimate(body)


@router.post("/searches", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
def start_search(body: SearchRequest, request: Request, session: Session = Depends(get_session),
                 worker: jobs.Worker = Depends(get_worker), user: User = ADMIN) -> CollectionRun:
    limits = get_limits(session)
    if body.budget_usd > limits["apify_max_per_search_usd"]:
        raise HTTPException(400, f"Budget is above the per-search limit (${limits['apify_max_per_search_usd']}).")
    spent = _apify_spent_this_month(session)
    if spent + body.budget_usd > limits["apify_monthly_cap_usd"]:
        raise HTTPException(400, f"Monthly Apify limit: ${spent:.2f} of ${limits['apify_monthly_cap_usd']} used; "
                                 f"this search could add ${body.budget_usd:.2f}. An admin can raise it in Settings.")
    if not apify_tokens.tokens():
        raise HTTPException(400, "No Apify account saved. Add one first.")
    active = session.scalar(select(func.count()).select_from(CollectionRun).where(
        CollectionRun.status.in_(["queued", "running"])))
    if active:
        raise HTTPException(409, "A search is already running. Wait for it to finish.")
    params = {"targets": [[t.country.upper(), t.city] for t in body.targets], "industries": body.industries,
              "budget_usd": body.budget_usd, "per_search": body.per_search,
              "min_reviews": body.min_reviews, "max_reviews": body.max_reviews,
              "audit": body.audit.model_dump() if body.audit else None}
    if body.audit:
        _check_daily_audits(session, 0)
    run = jobs.enqueue_collection(session, params, user.email)
    log(session, user, "search_started", f"search #{run.id}",
        {"budget_usd": body.budget_usd, "cities": len(body.targets), "industries": body.industries}, client_ip(request))
    worker.submit(run.id)
    return run


@router.get("/searches", response_model=list[RunOut])
def list_searches(limit: int = Query(20, ge=1, le=100), session: Session = Depends(get_session)):
    return session.scalars(select(CollectionRun).order_by(CollectionRun.id.desc()).limit(limit)).all()


@router.get("/searches/{run_id}", response_model=RunOut)
def get_search(run_id: int, session: Session = Depends(get_session)):
    run = session.get(CollectionRun, run_id)
    if run is None:
        raise HTTPException(404, "No such search")
    return run


# ------------------------------------------------------------------ businesses
AuditFilter = Literal["all", "new", "audited"]
# "audited" = a full audit (its final Main Agent step) has finished; "new" = never fully audited yet,
# so a bulk run on the "new" list never repeats a business that was already audited
_AUDITED = select(AuditJob.business_id).join(AgentTask, AgentTask.audit_job_id == AuditJob.id).where(
    AgentTask.agent_name == AgentName.MAIN,
    AgentTask.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED]))


def _business_query(country: list[str], city: str | None, industry: str | None, q: str | None,
                    audit: AuditFilter = "all", owner: str | None = None):
    stmt = select(Business)
    if owner == "none":
        stmt = stmt.where(Business.owner_id.is_(None))
    elif owner == "any":
        stmt = stmt.where(Business.owner_id.is_not(None))
    elif owner and owner.isdigit():
        stmt = stmt.where(Business.owner_id == int(owner))
    if audit == "audited":
        stmt = stmt.where(Business.id.in_(_AUDITED))
    elif audit == "new":
        stmt = stmt.where(Business.id.not_in(_AUDITED))
    if country:
        stmt = stmt.where(Business.country.in_([c.upper() for c in country]))
    if city:
        stmt = stmt.where(func.lower(Business.city) == city.lower())
    if industry:
        stmt = stmt.where(Business.industry == industry)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Business.name.ilike(like), Business.phone.like(like), Business.website_url.ilike(like)))
    return stmt


@router.get("/businesses/export")
def export_businesses(request: Request, format: Literal["csv", "xlsx"] = "xlsx", country: list[str] = Query(default=[]),
                      city: str | None = None, industry: str | None = None,
                      q: str | None = Query(None, max_length=100), audit: AuditFilter = "all",
                      session: Session = Depends(get_session), user: User = EXPORT):
    stmt = _business_query(country, city, industry, q, audit).options(
        selectinload(Business.social_profiles), selectinload(Business.audit_jobs)).order_by(Business.id)
    found = session.scalars(stmt.limit(EXPORT_MAX_ROWS)).all()
    issues = dict(session.execute(select(AuditFinding.business_id, func.count()).where(
        AuditFinding.business_id.in_([b.id for b in found])).group_by(AuditFinding.business_id)).all())
    data = export.rows(list(found), issues)
    log(session, user, "leads_exported", format, {"rows": len(data), "filters": {"country": country, "city": city,
                                                                            "industry": industry, "q": q,
                                                                            "audit": audit}},
        client_ip(request))
    name = f"leads_{datetime.now(UTC):%Y%m%d_%H%M}"
    if format == "csv":
        return Response(export.to_csv(data), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    return Response(export.to_xlsx(data),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


@router.get("/businesses", response_model=BusinessPage)
def list_businesses(country: list[str] = Query(default=[]), city: str | None = None, industry: str | None = None,
                    q: str | None = Query(None, max_length=100), limit: int = Query(50, ge=1, le=500),
                    offset: int = Query(0, ge=0), sort: Literal["newest", "score"] = "newest",
                    audit: AuditFilter = "all", owner: str | None = Query(None, pattern=r"^(none|any|\d+)$"),
                    session: Session = Depends(get_session)) -> BusinessPage:
    stmt = _business_query(country, city, industry, q, audit, owner)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    order = (Business.details["opportunity"]["score"].as_integer().desc().nulls_last(), Business.id.desc()) \
        if sort == "score" else (Business.id.desc(),)
    items = session.scalars(stmt.order_by(*order).limit(limit).offset(offset)).all()
    return BusinessPage(total=total or 0, items=items)


@router.get("/businesses/{business_pk}", response_model=BusinessDetail)
def get_business(business_pk: int, session: Session = Depends(get_session)):
    b = session.scalars(select(Business).where(Business.id == business_pk).options(
        selectinload(Business.data_sources), selectinload(Business.social_profiles),
        selectinload(Business.audit_jobs).selectinload(AuditJob.tasks))).first()
    if b is None:
        raise HTTPException(404, "No such business")
    return b


# ------------------------------------------------------------------ run one agent for one business
RUNNABLE = {"website": AgentName.WEBSITE_EXPERT, "social_finder": AgentName.SOCIAL_MEDIA_FINDER,
            "social": AgentName.SOCIAL_MEDIA_EXPERT, "automation": AgentName.AUTOMATION_RUNNER,
            "organizer": AgentName.DATA_ORGANIZER, "reporting": AgentName.REPORTING, "main": AgentName.MAIN}
AGENT_NEEDS = {"social": ("social_finder",), "reporting": ("organizer",)}  # Agent 2 judges what Agent 3 found, so Agent 3 runs first


def _latest_task(session: Session, business_pk: int, agent: AgentName, done_only: bool = False) -> AgentTask | None:
    stmt = select(AgentTask).join(AuditJob).where(AuditJob.business_id == business_pk, AgentTask.agent_name == agent)
    if done_only:
        stmt = stmt.where(AgentTask.status.in_([TaskStatus.COMPLETED, TaskStatus.SKIPPED]))
    return session.scalars(stmt.order_by(AgentTask.id.desc()).limit(1)).first()


def _start_agent(session: Session, request: Request, business_pk: int, key: str, user: User) -> AgentTask:
    if session.get(Business, business_pk) is None:
        raise HTTPException(404, "No such business")
    agent = RUNNABLE[key]
    task = _latest_task(session, business_pk, agent)
    if task is None or task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED):
        needed = {key, *AGENT_NEEDS.get(key, ())}
        _check_daily_audits(session, 1)
        jobs.create_audit_jobs(session, [business_pk], {k: k in needed for k in jobs.AUDIT_AGENTS}, user.email,
                               allow_parallel=True, max_attempts=get_limits(session)["task_max_attempts"])
        log(session, user, "agent_started", f"BUS id {business_pk}", {"agent": key}, client_ip(request))
        task = _latest_task(session, business_pk, agent)
    request.app.state.audit_worker.wake()
    return task


@router.post("/businesses/{business_pk}/website-audit", response_model=WebsiteAuditOut,
             status_code=status.HTTP_202_ACCEPTED)
def start_website_audit(business_pk: int, request: Request, session: Session = Depends(get_session),
                        user: User = AUDITS):
    task = _start_agent(session, request, business_pk, "website", user)
    return WebsiteAuditOut(job_id=task.audit_job_id, task_status=str(task.status), attempts=task.attempt_count)


@router.post("/businesses/{business_pk}/social", response_model=SocialFinderOut, status_code=status.HTTP_202_ACCEPTED)
def start_social_finder(business_pk: int, request: Request, session: Session = Depends(get_session),
                        user: User = AUDITS):
    task = _start_agent(session, request, business_pk, "social_finder", user)
    return SocialFinderOut(job_id=task.audit_job_id, task_status=str(task.status), attempts=task.attempt_count)


@router.get("/businesses/{business_pk}/social", response_model=SocialFinderOut)
def get_social(business_pk: int, session: Session = Depends(get_session)):
    b = session.get(Business, business_pk)
    if b is None:
        raise HTTPException(404, "No such business")
    task = _latest_task(session, business_pk, AgentName.SOCIAL_MEDIA_FINDER)
    done = _latest_task(session, business_pk, AgentName.SOCIAL_MEDIA_FINDER, done_only=True)
    rank = {"high": 0, "medium": 1, "low": 2}
    return SocialFinderOut(job_id=task.audit_job_id if task else None, task_status=str(task.status) if task else None,
                           attempts=task.attempt_count if task else 0, error=task.error_message if task else None,
                           summary=done.output_data if done else None,
                           profiles=sorted(b.social_profiles, key=lambda p: (rank.get(str(p.confidence), 9), p.platform)))


@router.get("/businesses/{business_pk}/website-audit", response_model=WebsiteAuditOut)
def get_website_audit(business_pk: int, session: Session = Depends(get_session)):
    task = _latest_task(session, business_pk, AgentName.WEBSITE_EXPERT)
    if task is None:
        return WebsiteAuditOut(job_id=None, task_status=None)
    done = _latest_task(session, business_pk, AgentName.WEBSITE_EXPERT, done_only=True)
    findings = session.scalars(select(AuditFinding).where(AuditFinding.agent_task_id == done.id)).all() if done else []
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return WebsiteAuditOut(job_id=task.audit_job_id, task_status=str(task.status), attempts=task.attempt_count,
                           error=task.error_message, summary=done.output_data if done else None,
                           findings=sorted(findings, key=lambda f: order.get(str(f.severity), 9)))


@router.post("/businesses/{business_pk}/agents/{key}", response_model=AgentResultOut,
             status_code=status.HTTP_202_ACCEPTED)
def start_agent(business_pk: int, key: Literal["social", "automation", "organizer", "reporting", "main"],
                request: Request,
                session: Session = Depends(get_session), user: User = AUDITS):
    """Run Agent 2 (social, presence only), Agent 4 (automation, audit only) or Agent 5 (organizer)."""
    task = _start_agent(session, request, business_pk, key, user)
    return AgentResultOut(job_id=task.audit_job_id, task_status=str(task.status), attempts=task.attempt_count)


@router.get("/businesses/{business_pk}/agents/{key}", response_model=AgentResultOut)
def get_agent(business_pk: int, key: Literal["social", "automation", "organizer", "reporting", "main"],
              session: Session = Depends(get_session)):
    if session.get(Business, business_pk) is None:
        raise HTTPException(404, "No such business")
    task = _latest_task(session, business_pk, RUNNABLE[key])
    if task is None:
        return AgentResultOut(job_id=None, task_status=None)
    done = _latest_task(session, business_pk, RUNNABLE[key], done_only=True)
    findings = session.scalars(select(AuditFinding).where(AuditFinding.agent_task_id == done.id)).all() if done else []
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return AgentResultOut(job_id=task.audit_job_id, task_status=str(task.status), attempts=task.attempt_count,
                          error=task.error_message, summary=done.output_data if done else None,
                          findings=sorted(findings, key=lambda f: order.get(str(f.severity), 9)))


# ------------------------------------------------------------------ Agent 6 reports
def _report_file(session: Session, report_id: int, suffix: str) -> Path:
    rep = session.get(Report, report_id)
    if rep is None or not rep.storage_path:
        raise HTTPException(404, "No such report")
    path = Path(rep.storage_path).with_suffix(suffix)
    root = audits.REPORTS_DIR.resolve()
    if not path.resolve().is_relative_to(root) or not path.is_file():
        raise HTTPException(404, "Report file not found")
    return path


@router.get("/reports", response_model=list[ReportOut])
def list_reports(business_id: int | None = None, limit: int = Query(50, ge=1, le=500),
                 session: Session = Depends(get_session)):
    stmt = select(Report).where(Report.status != "removed").order_by(Report.id.desc()).limit(limit)
    if business_id is not None:
        stmt = stmt.where(Report.business_id == business_id)
    return [ReportOut(id=r.id, business_id=r.business_id, report_type=r.report_type, version=r.version,
                      language=r.language, status=r.status, created_at=r.created_at,
                      has_pdf=Path(r.storage_path or "").with_suffix(".pdf").is_file())
            for r in session.scalars(stmt)]


@router.get("/reports/export")
def export_reports(request: Request, format: Literal["csv", "xlsx"] = "xlsx", session: Session = Depends(get_session),
                   user: User = EXPORT):
    """Sales sheet: one row per business with its latest internal report."""
    rows = export.sales_rows(session)
    log(session, user, "sales_sheet_exported", format, {"rows": len(rows)}, client_ip(request))
    name = f"sales_sheet_{datetime.now(UTC):%Y%m%d_%H%M}"
    if format == "csv":
        return Response(export.sales_csv(rows), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})
    return Response(export.sales_xlsx(rows),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})


@router.get("/reports/{report_id}", response_model=ReportOut)
def report_meta(report_id: int, session: Session = Depends(get_session)):
    """One report's details for the in-app viewer (after /reports/export, so that path still wins)."""
    r = session.get(Report, report_id)
    if r is None or r.status == "removed":
        raise HTTPException(404, "No such report")
    return ReportOut(id=r.id, business_id=r.business_id, report_type=r.report_type, version=r.version,
                     language=r.language, status=r.status, created_at=r.created_at,
                     has_pdf=Path(r.storage_path or "").with_suffix(".pdf").is_file())


@router.get("/reports/{report_id}/html", response_class=HTMLResponse)
def report_html(report_id: int, session: Session = Depends(get_session)):
    return HTMLResponse(_report_file(session, report_id, ".html").read_text(encoding="utf-8"),
                        headers={"Content-Security-Policy": "default-src 'none'; img-src data:; style-src 'unsafe-inline'"})


@router.get("/reports/{report_id}/pdf")
def report_pdf(report_id: int, request: Request, session: Session = Depends(get_session), user: User = SALES):
    path = _report_file(session, report_id, ".pdf")
    log(session, user, "report_downloaded", f"report #{report_id}", ip=client_ip(request))
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.get("/artifacts/{business_code}/{job_id}/{name}")
def artifact(business_code: str, job_id: int, name: str):
    """Screenshots taken by Agent 1. Only these exact file names, only inside the artifacts folder."""
    if name not in ARTIFACT_NAMES or not re.fullmatch(r"BUS-\d{4,9}", business_code):
        raise HTTPException(404, "Not found")
    path = audits.ARTIFACTS_DIR / business_code / f"job-{job_id}" / name
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/jpeg" if name.endswith(".jpg") else "image/png")


# ------------------------------------------------------------------ Main Agent: full audits, monitor, retry


@router.post("/businesses/{business_pk}/full-audit", response_model=AuditJobOut, status_code=status.HTTP_202_ACCEPTED)
def full_audit(business_pk: int, request: Request, session: Session = Depends(get_session), user: User = AUDITS):
    """One click: every agent in order (1 and 3 first, then 2 and 4, then 5, 6 and the Main Agent's final step)."""
    if session.get(Business, business_pk) is None:
        raise HTTPException(404, "No such business")
    # a full audit is still going while its final Main Agent step has not finished (the job may say "partial")
    active = session.scalars(select(AuditJob).where(
        AuditJob.business_id == business_pk,
        AuditJob.tasks.any((AgentTask.agent_name == AgentName.MAIN)
                           & AgentTask.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]))).limit(1)).first()
    if active is None:
        _check_daily_audits(session, 1)
    job = active or jobs.create_audit_jobs(session, [business_pk], {}, user.email, allow_parallel=True,
                                           max_attempts=get_limits(session)["task_max_attempts"])[0]
    if active is None:
        log(session, user, "full_audit_started", f"BUS id {business_pk}", {"job": job.id}, client_ip(request))
    request.app.state.audit_worker.wake()
    return job


@router.post("/audits/bulk")
def bulk_audit(request: Request, country: list[str] = Query(default=[]), city: str | None = None,
               industry: str | None = None, q: str | None = Query(None, max_length=100),
               limit: int = Query(50, ge=1, le=200), audit: AuditFilter = "new",
               session: Session = Depends(get_session), user: User = AUDITS) -> dict:
    """Full audit for the leads matching the All Leads filters (no money is spent: websites only)."""
    limits = get_limits(session)
    limit = min(limit, limits["bulk_audit_max"])
    ids = list(session.scalars(_business_query(country, city, industry, q, audit).with_only_columns(Business.id)
                               .order_by(Business.id).limit(limit)))
    _check_daily_audits(session, len(ids))
    # one click = one run on the Audit Results page
    label = " · ".join(filter(None, [f"{len(ids)} lead{'' if len(ids) == 1 else 's'}",", ".join(country), city, industry, q and f"“{q}”"]))
    run = {"run": f"r{datetime.now(UTC):%Y%m%d%H%M%S}{secrets.token_hex(2)}", "run_label": label}
    created = jobs.create_audit_jobs(session, ids, run, user.email, max_attempts=limits["task_max_attempts"])
    log(session, user, "bulk_audit_started", f"{len(created)} leads",
        {"matched": len(ids), "filters": {"country": country, "city": city, "industry": industry, "q": q,
                                          "audit": audit}},
        client_ip(request))
    request.app.state.audit_worker.wake()
    return {"matched": len(ids), "queued": len(created), "skipped_already_waiting": len(ids) - len(created),
            "run": run["run"]}


@router.get("/monitor")
def monitor(request: Request, session: Session = Depends(get_session)) -> dict:
    rows = session.execute(select(AgentTask.agent_name, AgentTask.status, func.count()).group_by(
        AgentTask.agent_name, AgentTask.status)).all()
    by_agent: dict[str, dict] = {}
    for agent, st, n in rows:
        by_agent.setdefault(str(agent), {})[str(st)] = n
    running = session.execute(select(AgentTask, Business).select_from(AgentTask).join(AuditJob, AgentTask.audit_job_id == AuditJob.id).join(
        Business, AuditJob.business_id == Business.id).where(
        AgentTask.status == TaskStatus.RUNNING).order_by(AgentTask.started_at)).all()
    failed = session.execute(select(AgentTask, Business).select_from(AgentTask).join(AuditJob, AgentTask.audit_job_id == AuditJob.id).join(
        Business, AuditJob.business_id == Business.id).where(
        AgentTask.status == TaskStatus.FAILED).order_by(AgentTask.id.desc()).limit(25)).all()
    retrying = session.execute(select(AgentTask, Business).select_from(AgentTask).join(AuditJob, AgentTask.audit_job_id == AuditJob.id).join(
        Business, AuditJob.business_id == Business.id).where(
        AgentTask.status == TaskStatus.PENDING, AgentTask.attempt_count > 0).limit(25)).all()
    worker = request.app.state.audit_worker
    ready = audits.ready_tasks(session, list(worker.work), limit=500)

    stuck_after = get_limits(session)["task_stuck_minutes"] * 60

    def row(t, b):
        started = t.started_at if t.started_at is None or t.started_at.tzinfo else t.started_at.replace(tzinfo=UTC)
        return {"task_id": t.id, "agent": str(t.agent_name), "business_pk": b.id, "business_id": b.business_id,
                "business": b.name, "attempts": t.attempt_count, "error": t.error_message,
                "started_at": t.started_at, "retry_after": (t.input_data or {}).get("retry_after"),
                "stuck": bool(started and t.status == TaskStatus.RUNNING
                              and (datetime.now(UTC) - started).total_seconds() > stuck_after)}

    return {"agents": by_agent, "running": [row(t, b) for t, b in running], "failed": [row(t, b) for t, b in failed],
            "retrying": [row(t, b) for t, b in retrying], "ready_now": len(ready),
            "jobs": {str(k): n for k, n in session.execute(select(AuditJob.status, func.count()).group_by(AuditJob.status))},
            "workers": worker.status()}


@router.post("/tasks/{task_id}/retry")
def retry(task_id: int, request: Request, session: Session = Depends(get_session), user: User = AUDITS) -> dict:
    t = audits.retry_task(session, task_id)
    if t is None:
        raise HTTPException(409, "Only failed tasks can be retried")
    log(session, user, "task_retried", f"task #{task_id}", {"agent": str(t.agent_name)}, client_ip(request))
    request.app.state.audit_worker.wake()
    return {"task_id": t.id, "status": str(t.status)}


# ------------------------------------------------------------------ audits (queue; agents run as they are built)
@router.post("/audits", response_model=list[AuditJobOut], status_code=status.HTTP_201_CREATED)
def queue_audits(body: AuditRequest, request: Request, session: Session = Depends(get_session), user: User = AUDITS):
    found = set(session.scalars(select(Business.id).where(Business.id.in_(body.business_ids))))
    missing = sorted(set(body.business_ids) - found)
    if missing:
        raise HTTPException(404, f"Unknown business ids: {missing[:10]}")
    _check_daily_audits(session, len(found))
    created = jobs.create_audit_jobs(session, list(found), body.options.model_dump(), user.email,
                                     max_attempts=get_limits(session)["task_max_attempts"])
    log(session, user, "audits_queued", f"{len(created)} leads", {"options": body.options.model_dump()}, client_ip(request))
    request.app.state.audit_worker.wake()
    return created


@router.get("/audits/{job_id}", response_model=AuditJobOut)
def get_audit(job_id: int, session: Session = Depends(get_session)):
    job = session.get(AuditJob, job_id)
    if job is None:
        raise HTTPException(404, "No such audit")
    return job
