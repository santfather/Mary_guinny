"""Публичное чтение job (WP-06): источник истины для статуса и UI.

WP-M1: к детали job добавлено последнее событие, появился журнал событий —
UI показывает этап и прогресс без SSE.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.worker_schemas import JobDetailOut, JobEventOut, JobOut
from app.models import Event, Job

router = APIRouter(prefix="/api", tags=["jobs"])


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[JobOut]:
    statement = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status_filter is not None:
        statement = statement.where(Job.status == status_filter)
    return [JobOut.model_validate(job) for job in session.scalars(statement)]


@router.get("/jobs/{job_id}", response_model=JobDetailOut)
def get_job(job_id: uuid.UUID, session: Session = Depends(get_session)) -> JobDetailOut:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    last = session.scalar(
        select(Event)
        .where(Event.job_id == job.id)
        .order_by(Event.sequence.desc())
        .limit(1)
    )
    return JobDetailOut(
        **JobOut.model_validate(job).model_dump(),
        last_event=JobEventOut.model_validate(last) if last is not None else None,
    )


@router.get("/jobs/{job_id}/events", response_model=list[JobEventOut])
def list_job_events(
    job_id: uuid.UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> list[JobEventOut]:
    """Последние `limit` событий в хронологическом порядке."""

    if session.get(Job, job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    events = list(
        session.scalars(
            select(Event)
            .where(Event.job_id == job_id)
            .order_by(Event.sequence.desc())
            .limit(limit)
        )
    )
    events.reverse()
    return [JobEventOut.model_validate(event) for event in events]
