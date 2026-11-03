"""Request / response shapes. Responses never contain a full Apify token."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .ingest.gulf import COUNTRIES, INDUSTRIES


class Target(BaseModel):
    country: str = Field(min_length=2, max_length=2)
    city: str = Field(min_length=1, max_length=80)

    @field_validator("city")
    @classmethod
    def _known_city(cls, v: str, info) -> str:
        cc = (info.data.get("country") or "").upper()
        if cc not in COUNTRIES or v not in COUNTRIES[cc]["cities"]:
            raise ValueError(f"unknown city {v!r} for {cc!r}")
        return v


class AuditOptions(BaseModel):
    website: bool = True
    social_finder: bool = True
    social: bool = True
    automation: bool = True
    organizer: bool = True
    reporting: bool = True
    main: bool = True


class SearchRequest(BaseModel):
    targets: list[Target] = Field(min_length=1, max_length=80)
    industries: list[str] = Field(min_length=1, max_length=len(INDUSTRIES))
    budget_usd: float = Field(ge=0.5, le=200, description="hard cap for Apify spend in this run")
    per_search: int = Field(default=40, ge=5, le=500)
    min_reviews: int = Field(default=50, ge=0, le=100_000, description="keep places with at least this many Google reviews")
    max_reviews: int = Field(default=1000, ge=0, le=100_000, description="and at most this many")
    audit: AuditOptions | None = Field(default=None, description="queue an audit for every business found")

    @model_validator(mode="after")
    def _review_range(self) -> SearchRequest:
        if self.min_reviews > self.max_reviews:
            raise ValueError("Minimum reviews cannot be more than maximum reviews")
        return self

    @field_validator("industries")
    @classmethod
    def _known_industries(cls, v: list[str]) -> list[str]:
        bad = [i for i in v if i not in INDUSTRIES]
        if bad:
            raise ValueError(f"unknown industries {bad}")
        return list(dict.fromkeys(v))


class Estimate(BaseModel):
    cities: int
    searches: int
    max_places: int
    estimate_usd: float
    budget_usd: float
    credit_left_usd: float


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    params: dict
    actor_runs: list
    log: list
    spent_usd: float
    records_found: int
    new_businesses: int
    updated_businesses: int
    rejected: list
    problem: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class BusinessOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: str
    name: str
    category: str | None
    industry: str | None
    country: str
    city: str | None
    area: str | None
    website_url: str | None
    phone: str | None
    email: str | None
    maps_url: str | None
    rating: float | None
    review_count: int | None
    details: dict
    owner_id: int | None = None
    assigned_at: datetime | None = None
    source: str
    verification_status: str
    created_at: datetime


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: str | None
    source_type: str
    source_url: str | None
    collection_method: str
    verification_status: str
    collected_at: datetime


class SocialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    platform: str
    profile_url: str
    username: str | None = None
    verification_status: str
    confidence: str
    evidence: list
    last_checked_at: datetime | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    agent_name: str
    status: str
    attempt_count: int
    error_message: str | None


class AuditJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime
    tasks: list[TaskOut]


class BusinessDetail(BusinessOut):
    data_sources: list[SourceOut]
    social_profiles: list[SocialOut]
    audit_jobs: list[AuditJobOut]


class BusinessPage(BaseModel):
    total: int
    items: list[BusinessOut]


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=200, pattern=r"^\S+$")


class AuditRequest(BaseModel):
    business_ids: list[int] = Field(min_length=1, max_length=1000)
    options: AuditOptions = AuditOptions()


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    title: str
    description: str | None
    severity: str
    evidence: dict
    source_url: str | None
    confidence: str
    recommendation: str | None
    verification_status: str
    observed_at: datetime


class WebsiteAuditOut(BaseModel):
    job_id: int | None
    task_status: str | None
    attempts: int = 0
    error: str | None = None
    summary: dict | None = None
    findings: list[FindingOut] = []


class SocialFinderOut(BaseModel):
    job_id: int | None
    task_status: str | None
    attempts: int = 0
    error: str | None = None
    summary: dict | None = None
    profiles: list[SocialOut] = []


class AgentResultOut(WebsiteAuditOut):
    """Same shape for every agent: latest task state + latest finished output + its findings."""


class ReportOut(BaseModel):
    id: int
    business_id: int
    report_type: str
    version: int
    language: str
    status: str
    created_at: datetime
    has_pdf: bool
