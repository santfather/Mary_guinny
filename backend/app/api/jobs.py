"""Публичное чтение job (WP-06): источник истины для статуса и UI."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.worker_schemas import JobOut
from app.models import Job

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


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, session: Session = Depends(get_session)) -> JobOut:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobOut.model_validate(job)
