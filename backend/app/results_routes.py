"""Audit Results page: finished full audits, newest first, grouped into runs (needs a login)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .db import get_session
from .models import Business
from .services import pitch as pitch_service
from .services import results as results_service

router = APIRouter()


@router.get("/results")
def audit_results(run: str | None = Query(None, max_length=40), band: str | None = Query(None, max_length=40),
                  q: str | None = Query(None, max_length=100), sort: Literal["finished", "score"] = "finished",
                  limit: int = Query(100, ge=1, le=500),
                  sales: Literal["not_called", "called", "no_answer", "interested", "follow_up", "not_interested",
                                 "won"] | None = None,
                  session: Session = Depends(get_session)) -> dict:
    return results_service.results(session, run=run, band=band, q=q, sort=sort, limit=limit, sales=sales)


@router.get("/businesses/{business_pk}/pitch")
def sales_pitch(business_pk: int, session: Session = Depends(get_session)) -> dict:
    """What to say on the call, from the checked audit facts only (same source as the sales brief)."""
    b = session.get(Business, business_pk)
    if b is None:
        raise HTTPException(404, "No such business")
    return pitch_service.pitch(session, b)
