import pytest
from sqlalchemy.exc import IntegrityError, StatementError

from app.models import (AgentName, AgentTask, AuditFinding, AuditJob, Business, Confidence, DataSource,
                        JobStatus, Report, Severity, SocialProfile, TaskStatus)


def _business(session, **kw):
    b = Business(name="Example Dental Clinic", country="AE", city="Dubai", source="apify_maps", **kw)
    session.add(b)
    session.commit()
    return b


def test_business_gets_public_id(session):
    b = _business(session)
    assert b.business_id == "BUS-0001"


def test_place_id_is_unique(session):
    _business(session, place_id="ChIJ1")
    session.add(Business(name="Copy", country="AE", source="apify_maps", place_id="ChIJ1"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_one_task_per_agent_per_job(session):
    job = AuditJob(business_id=_business(session).id, requested_by="rafay")
    session.add(job)
    session.commit()
    session.add_all([AgentTask(audit_job_id=job.id, agent_name=AgentName.WEBSITE_EXPERT),
                     AgentTask(audit_job_id=job.id, agent_name=AgentName.WEBSITE_EXPERT)])
    with pytest.raises(IntegrityError):
        session.commit()


def test_bad_status_value_is_rejected(session):
    b = _business(session)
    session.add(AuditJob(business_id=b.id, requested_by="rafay", status="done-ish"))
    with pytest.raises(StatementError):
        session.commit()


def test_full_chain_and_cascade_delete(session):
    b = _business(session)
    job = AuditJob(business_id=b.id, requested_by="rafay")
    session.add(job)
    session.flush()
    task = AgentTask(audit_job_id=job.id, agent_name=AgentName.WEBSITE_EXPERT, status=TaskStatus.COMPLETED)
    session.add(task)
    session.flush()
    session.add_all([
        AuditFinding(business_id=b.id, agent_task_id=task.id, category="seo", title="Homepage title missing",
                     severity=Severity.LOW, confidence=Confidence.HIGH, evidence={"url": "https://example.com"}),
        SocialProfile(business_id=b.id, platform="instagram", profile_url="https://instagram.com/example"),
        DataSource(business_id=b.id, field="phone", source_type="apify", collection_method="actor_run"),
        Report(business_id=b.id, audit_job_id=job.id, report_type="owner_summary"),
    ])
    session.commit()
    assert job.status == JobStatus.QUEUED
    assert len(b.social_profiles) == 1 and len(job.reports) == 1

    session.delete(b)
    session.commit()
    for model in (AuditJob, AgentTask, AuditFinding, SocialProfile, DataSource, Report):
        assert session.query(model).count() == 0, model.__name__


def test_timestamps_are_timezone_aware_columns():
    from app.models import AuditJob, Business
    assert Business.__table__.c.created_at.type.timezone is True
    assert AuditJob.__table__.c.started_at.type.timezone is True
