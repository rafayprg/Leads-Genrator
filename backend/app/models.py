"""The 8 tables from the architecture document. Statuses are closed lists so bad values fail early."""
from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum

from sqlalchemy import JSON, Date, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def _enum(e: type[StrEnum]) -> Enum:
    # stored as plain text (portable to PostgreSQL), values checked by SQLAlchemy
    return Enum(e, native_enum=False, validate_strings=True, length=32,
                values_callable=lambda cls: [m.value for m in cls])


class Verification(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    PROBABLE = "probable"
    INFERRED = "inferred"
    UNVERIFIED = "unverified"
    REQUIRES_REVIEW = "requires_review"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentName(StrEnum):
    WEBSITE_EXPERT = "website_expert"          # Agent 1
    SOCIAL_MEDIA_EXPERT = "social_media_expert"  # Agent 2
    SOCIAL_MEDIA_FINDER = "social_media_finder"  # Agent 3
    AUTOMATION_RUNNER = "automation_runner"      # Agent 4
    DATA_ORGANIZER = "data_organizer"            # Agent 5
    REPORTING = "reporting"                      # Agent 6
    MAIN = "main"


class AutomationMode(StrEnum):
    AUDIT_ONLY = "audit_only"
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class CollectionRun(Base):
    """One "Get leads" request: Apify runs, cost, counts and a readable log."""
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.QUEUED, index=True)
    requested_by: Mapped[str] = mapped_column(String(120))
    params: Mapped[dict] = mapped_column(JSON, default=dict)   # targets, industries, budget, per_search
    actor_runs: Mapped[list] = mapped_column(JSON, default=list)
    log: Mapped[list] = mapped_column(JSON, default=list)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    records_found: Mapped[int] = mapped_column(Integer, default=0)
    new_businesses: Mapped[int] = mapped_column(Integer, default=0)
    updated_businesses: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[list] = mapped_column(JSON, default=list)
    problem: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = (UniqueConstraint("place_id", name="uq_business_place_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    category: Mapped[str | None] = mapped_column(String(120))
    industry: Mapped[str | None] = mapped_column(String(60))
    country: Mapped[str] = mapped_column(String(2))  # ISO code: AE, SA, QA, KW, BH, OM
    city: Mapped[str | None] = mapped_column(String(80))
    area: Mapped[str | None] = mapped_column(String(120))
    website_url: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(20))  # E.164, public business number only
    email: Mapped[str | None] = mapped_column(String(200))
    maps_url: Mapped[str | None] = mapped_column(String(500))
    place_id: Mapped[str | None] = mapped_column(String(200))
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    # extra collected facts without their own column: phone_type, last_review_date, opening_hours, lat, lon, ...
    details: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    source: Mapped[str] = mapped_column(String(60))
    collection_status: Mapped[str] = mapped_column(String(20), default="completed")
    verification_status: Mapped[Verification] = mapped_column(_enum(Verification), default=Verification.PENDING)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    social_profiles: Mapped[list[SocialProfile]] = relationship(back_populates="business", cascade="all, delete-orphan")
    audit_jobs: Mapped[list[AuditJob]] = relationship(back_populates="business", cascade="all, delete-orphan")
    data_sources: Mapped[list[DataSource]] = relationship(back_populates="business", cascade="all, delete-orphan")

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    assigned_at: Mapped[datetime | None] = mapped_column()

    @property
    def business_id(self) -> str:
        """Public id shown to people, e.g. BUS-0001."""
        return f"BUS-{self.id:04d}" if self.id is not None else ""


class DataSource(Base):
    """Where each piece of data came from, per field (provenance)."""
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    field: Mapped[str | None] = mapped_column(String(60))  # None = the whole record
    source_type: Mapped[str] = mapped_column(String(60))   # e.g. apify:compass/crawler-google-places
    source_url: Mapped[str | None] = mapped_column(String(500))
    collection_method: Mapped[str] = mapped_column(String(60))
    verification_status: Mapped[Verification] = mapped_column(_enum(Verification), default=Verification.UNVERIFIED)
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)

    business: Mapped[Business] = relationship(back_populates="data_sources")


class SocialProfile(Base):
    __tablename__ = "social_profiles"
    __table_args__ = (UniqueConstraint("business_id", "profile_url", name="uq_social_business_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(30))
    profile_url: Mapped[str] = mapped_column(String(500))
    username: Mapped[str | None] = mapped_column(String(120))
    verification_status: Mapped[Verification] = mapped_column(_enum(Verification), default=Verification.UNVERIFIED)
    confidence: Mapped[Confidence] = mapped_column(_enum(Confidence), default=Confidence.LOW)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column()

    business: Mapped[Business] = relationship(back_populates="social_profiles")


class AuditJob(Base):
    __tablename__ = "audit_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.QUEUED, index=True)
    requested_by: Mapped[str] = mapped_column(String(120))
    configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()

    business: Mapped[Business] = relationship(back_populates="audit_jobs")
    tasks: Mapped[list[AgentTask]] = relationship(back_populates="audit_job", cascade="all, delete-orphan")
    reports: Mapped[list[Report]] = relationship(back_populates="audit_job", cascade="all, delete-orphan")


class AgentTask(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (UniqueConstraint("audit_job_id", "agent_name", name="uq_task_job_agent"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_job_id: Mapped[int] = mapped_column(ForeignKey("audit_jobs.id", ondelete="CASCADE"), index=True)
    agent_name: Mapped[AgentName] = mapped_column(_enum(AgentName))
    status: Mapped[TaskStatus] = mapped_column(_enum(TaskStatus), default=TaskStatus.PENDING, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    input_data: Mapped[dict] = mapped_column(JSON, default=dict)
    output_data: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()

    audit_job: Mapped[AuditJob] = relationship(back_populates="tasks")
    findings: Mapped[list[AuditFinding]] = relationship(back_populates="agent_task", cascade="all, delete-orphan")


class AuditFinding(Base):
    __tablename__ = "audit_findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    agent_task_id: Mapped[int] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[Severity] = mapped_column(_enum(Severity))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    source_url: Mapped[str | None] = mapped_column(String(500))
    confidence: Mapped[Confidence] = mapped_column(_enum(Confidence))
    recommendation: Mapped[str | None] = mapped_column(Text)
    verification_status: Mapped[Verification] = mapped_column(_enum(Verification), default=Verification.INFERRED)
    observed_at: Mapped[datetime] = mapped_column(default=utcnow)

    agent_task: Mapped[AgentTask] = relationship(back_populates="findings")


class AutomationRun(Base):
    __tablename__ = "automation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    agent_task_id: Mapped[int | None] = mapped_column(ForeignKey("agent_tasks.id", ondelete="SET NULL"))
    workflow: Mapped[str] = mapped_column(String(120))
    mode: Mapped[AutomationMode] = mapped_column(_enum(AutomationMode), default=AutomationMode.AUDIT_ONLY)
    status: Mapped[TaskStatus] = mapped_column(_enum(TaskStatus), default=TaskStatus.PENDING)
    executions: Mapped[int] = mapped_column(Integer, default=0)
    successes: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    avg_duration_ms: Mapped[float | None] = mapped_column(Float)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # never credentials or tokens
    started_at: Mapped[datetime | None] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column()


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("audit_job_id", "report_type", "language", "version", name="uq_report_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    audit_job_id: Mapped[int] = mapped_column(ForeignKey("audit_jobs.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    report_type: Mapped[str] = mapped_column(String(40))  # owner_summary, technical, sales, internal
    language: Mapped[str] = mapped_column(String(20), default="en")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    storage_path: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    audit_job: Mapped[AuditJob] = relationship(back_populates="reports")


# ------------------------------------------------------------------ Phase 9: users, sessions, activity log, settings
class Role(StrEnum):
    ADMIN = "admin"    # everything: Apify accounts, spending, users, limits
    SALES = "sales"    # leads, audits (free), reports, exports — cannot spend Apify credit or change settings
    VIEWER = "viewer"  # read only
    CALLER = "caller"  # calling desk only: their own assigned leads and the call buttons, nothing else


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[Role] = mapped_column(_enum(Role), default=Role.VIEWER)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column()
    # team profile (Phase 10C)
    phone: Mapped[str | None] = mapped_column(String(40))
    whatsapp: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str | None] = mapped_column(String(80))
    countries: Mapped[list] = mapped_column(JSON, default=list)   # country codes this member covers ([] = all)
    industries: Mapped[list] = mapped_column(JSON, default=list)  # industry keys ([] = all)
    away: Mapped[bool] = mapped_column(default=False)             # on leave: skipped by auto-assign
    daily_call_target: Mapped[int] = mapped_column(Integer, default=30)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    pin_hash: Mapped[str | None] = mapped_column(String(300))  # team login: pick your name + PIN (set by the admin)


class UserSession(Base):
    """Server-side login sessions. Only a SHA-256 of the cookie value is stored."""
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column()
    ip: Mapped[str | None] = mapped_column(String(64))

    user: Mapped[User] = relationship()


class ActivityLog(Base):
    """Who did what, when. Never stores passwords or keys (only the last 4 characters of a key)."""
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    user_email: Mapped[str | None] = mapped_column(String(200), index=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target: Mapped[str | None] = mapped_column(String(120))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(200))


# ------------------------------------------------------------------ sales follow-up (call tracking)
class SalesStatus(StrEnum):
    CALLED = "called"
    NO_ANSWER = "no_answer"
    CONNECTED = "connected"              # the calling desk's statuses (from LeadsPro)
    NOT_CONNECTED = "not_connected"
    NOT_ON_WHATSAPP = "not_on_whatsapp"
    INTERESTED = "interested"
    FOLLOW_UP = "follow_up"
    NOT_INTERESTED = "not_interested"
    WON = "won"


class SalesNote(Base):
    """One row per call / update; the newest row is the lead's current sales status. Rows are never edited."""
    __tablename__ = "sales_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    status: Mapped[SalesStatus] = mapped_column(_enum(SalesStatus))
    note: Mapped[str | None] = mapped_column(Text)
    follow_up_on: Mapped[date | None] = mapped_column(Date, index=True)
    by: Mapped[str] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
