"""Аудио проекта, таймлайн и черновые планы производства (WP-M3).

Аудио проекта — один трек (`projects.audio_artifact_id`). Таймлайн строится
из него на лету, снимок таймлайна сохраняется вместе с планом. Генерация плана
никогда не меняет сцены и утверждённые записи: создаётся только новая ревизия
`production_plans` со статусом `draft`, предыдущие черновики становятся
`superseded`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_settings, get_store, require_project
from app.audio_timeline import AudioTimelineError, analyze_audio, probe_audio
from app.config import Settings
from app.models import Artifact, Character, Location, ProductionPlan, Project, Prop
from app.production_plan import (
    PLAN_SCHEMA_VERSION,
    ProductionPlanPayload,
    generate_plan,
)
from app.storage import BlobStore, StorageError

router = APIRouter(tags=["production-plans"])

MAX_LIBRARY_NAMES = 50


class WarningOut(BaseModel):
    code: str
    message: str


class TimelineSectionOut(BaseModel):
    start_s: float
    end_s: float
    rms: float
    energy_tier: str


class TimelineOut(BaseModel):
    duration_s: float
    bpm: float | None
    bpm_confidence: float
    meter: str
    beats: list[float]
    downbeats: list[float]
    sections: list[TimelineSectionOut]
    method: str
    analysis_rate_hz: int
    warnings: list[WarningOut]


class AudioOut(BaseModel):
    artifact_id: uuid.UUID
    content_url: str
    mime_type: str
    bytes: int
    duration_s: float


class AudioAttach(BaseModel):
    artifact_id: uuid.UUID


class PlanGenerate(BaseModel):
    brief: str | None = Field(default=None, max_length=2000)
    use_llm: bool = True


class ProductionPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    revision: int
    schema_version: int
    status: str
    source: str
    audio_artifact_id: uuid.UUID | None
    timeline: TimelineOut
    plan: ProductionPlanPayload
    warnings: list[WarningOut]
    created_at: datetime


def _content_url(artifact_id: uuid.UUID) -> str:
    return f"/api/artifacts/{artifact_id}/content"


def _artifact_path(store: BlobStore, artifact: Artifact) -> Path:
    try:
        path = store.resolve(artifact.storage_key)
    except StorageError as error:
        raise HTTPException(status_code=500, detail=f"invalid storage_key: {error}") from error
    if not path.is_file():
        raise HTTPException(status_code=409, detail="artifact content is missing")
    return path


def _timeline_error(error: AudioTimelineError, code: int = 422) -> HTTPException:
    return HTTPException(
        status_code=code, detail={"error": error.code, "message": str(error)}
    )


def _project_audio(session: Session, project: Project) -> Artifact:
    if project.audio_artifact_id is None:
        raise HTTPException(status_code=409, detail="project audio is not set")
    artifact = session.get(Artifact, project.audio_artifact_id)
    if artifact is None:
        raise HTTPException(status_code=409, detail="project audio artifact is missing")
    return artifact


def _audio_out(store: BlobStore, artifact: Artifact) -> AudioOut:
    path = _artifact_path(store, artifact)
    try:
        duration, has_audio = probe_audio(path)
    except AudioTimelineError as error:
        raise _timeline_error(error) from error
    if not has_audio:
        raise _timeline_error(
            AudioTimelineError("missing_audio_stream", "в файле нет аудиодорожки")
        )
    return AudioOut(
        artifact_id=artifact.id,
        content_url=_content_url(artifact.id),
        mime_type=artifact.mime_type,
        bytes=artifact.bytes,
        duration_s=round(duration, 3),
    )


def _timeline_out(timeline: dict[str, Any]) -> TimelineOut:
    return TimelineOut(
        duration_s=float(timeline.get("duration_s") or 0.0),
        bpm=timeline.get("bpm"),
        bpm_confidence=float(timeline.get("bpm_confidence") or 0.0),
        meter=str(timeline.get("meter") or "4/4"),
        beats=[float(value) for value in timeline.get("beats") or []],
        downbeats=[float(value) for value in timeline.get("downbeats") or []],
        sections=[TimelineSectionOut(**section) for section in timeline.get("sections") or []],
        method=str(timeline.get("method") or "unknown"),
        analysis_rate_hz=int(timeline.get("analysis_rate_hz") or 0),
        warnings=[WarningOut(**warning) for warning in timeline.get("warnings") or []],
    )


def _plan_out(plan: ProductionPlan) -> ProductionPlanOut:
    return ProductionPlanOut(
        id=plan.id,
        project_id=plan.project_id,
        revision=plan.revision,
        schema_version=plan.schema_version,
        status=plan.status,
        source=plan.source,
        audio_artifact_id=plan.audio_artifact_id,
        timeline=_timeline_out(plan.timeline),
        plan=ProductionPlanPayload.model_validate(plan.plan),
        warnings=[WarningOut(**warning) for warning in plan.warnings],
        created_at=plan.created_at,
    )


def _library_names(session: Session, model: Any, project_id: uuid.UUID) -> list[str]:
    names = session.scalars(
        select(model.name)
        .where(model.project_id == project_id)
        .order_by(model.name)
        .limit(MAX_LIBRARY_NAMES)
    )
    return list(names)


@router.post(
    "/api/projects/{project_id}/audio",
    response_model=AudioOut,
    status_code=status.HTTP_201_CREATED,
)
def attach_project_audio(
    project_id: uuid.UUID,
    payload: AudioAttach,
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
) -> AudioOut:
    """Привязывает загруженный аудиоартефакт к проекту (один трек на проект)."""

    project = require_project(session, project_id)
    artifact = session.get(Artifact, payload.artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="audio artifact not found")
    if not artifact.mime_type.startswith("audio/"):
        raise HTTPException(status_code=409, detail="artifact is not audio")
    result = _audio_out(store, artifact)
    project.audio_artifact_id = artifact.id
    session.commit()
    return result


@router.get("/api/projects/{project_id}/audio", response_model=AudioOut)
def get_project_audio(
    project_id: uuid.UUID,
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
) -> AudioOut:
    project = require_project(session, project_id)
    artifact = _project_audio(session, project)
    return _audio_out(store, artifact)


@router.get("/api/projects/{project_id}/timeline", response_model=TimelineOut)
def get_project_timeline(
    project_id: uuid.UUID,
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
) -> TimelineOut:
    """Таймлайн песни: BPM, биты, доли и энергетические секции (эвристика)."""

    project = require_project(session, project_id)
    artifact = _project_audio(session, project)
    path = _artifact_path(store, artifact)
    try:
        timeline = analyze_audio(path)
    except AudioTimelineError as error:
        raise _timeline_error(error) from error
    return _timeline_out(timeline)


@router.post(
    "/api/projects/{project_id}/production-plans/generate",
    response_model=ProductionPlanOut,
    status_code=status.HTTP_201_CREATED,
)
def generate_production_plan(
    project_id: uuid.UUID,
    payload: PlanGenerate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> ProductionPlanOut:
    """Новая ревизия чернового плана; сцены и утверждённые записи не меняются."""

    project = require_project(session, project_id)
    artifact = _project_audio(session, project)
    path = _artifact_path(store, artifact)
    try:
        timeline = analyze_audio(path)
    except AudioTimelineError as error:
        raise _timeline_error(error) from error

    plan, warnings, source = generate_plan(
        title=project.title,
        brief=(payload.brief or "").strip(),
        timeline=timeline,
        characters=_library_names(session, Character, project_id),
        locations=_library_names(session, Location, project_id),
        props=_library_names(session, Prop, project_id),
        settings=settings,
        use_llm=payload.use_llm,
        max_repair=settings.planner_max_repair,
    )

    revision = (
        session.scalar(
            select(func.coalesce(func.max(ProductionPlan.revision), 0)).where(
                ProductionPlan.project_id == project_id
            )
        )
        + 1
    )
    session.execute(
        update(ProductionPlan)
        .where(ProductionPlan.project_id == project_id, ProductionPlan.status == "draft")
        .values(status="superseded")
    )
    record = ProductionPlan(
        project_id=project_id,
        revision=revision,
        schema_version=PLAN_SCHEMA_VERSION,
        status="draft",
        source=source,
        audio_artifact_id=artifact.id,
        timeline=timeline,
        plan=plan,
        warnings=warnings,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return _plan_out(record)


@router.get(
    "/api/projects/{project_id}/production-plans",
    response_model=list[ProductionPlanOut],
)
def list_production_plans(
    project_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[ProductionPlanOut]:
    require_project(session, project_id)
    plans = session.scalars(
        select(ProductionPlan)
        .where(ProductionPlan.project_id == project_id)
        .order_by(ProductionPlan.revision.desc())
        .limit(limit)
    )
    return [_plan_out(plan) for plan in plans]


@router.get("/api/production-plans/{plan_id}", response_model=ProductionPlanOut)
def get_production_plan(
    plan_id: uuid.UUID, session: Session = Depends(get_session)
) -> ProductionPlanOut:
    plan = session.get(ProductionPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="production plan not found")
    return _plan_out(plan)
