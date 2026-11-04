"""WP-M5: попытки проекта одной страницей — выбор дубля без новой модели данных."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_project
from app.api.shot_schemas import AttemptListItemOut, AttemptPage
from app.models import Artifact, RenderAttempt, Scene, Shot

router = APIRouter(prefix="/api", tags=["attempts"])

AttemptKind = Literal["keyframe", "video", "postprocess"]
AttemptStatus = Literal["pending", "running", "completed", "failed", "cancelled"]


def _artifact_ids(session: Session, attempt_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """Первый артефакт попытки — тот же выбор, что в карточке шота."""

    if not attempt_ids:
        return {}
    found: dict[uuid.UUID, uuid.UUID] = {}
    for artifact in session.scalars(
        select(Artifact)
        .where(Artifact.attempt_id.in_(attempt_ids))
        .order_by(Artifact.created_at)
    ):
        if artifact.attempt_id is not None:
            found.setdefault(artifact.attempt_id, artifact.id)
    return found


def _require_filter_owner(
    session: Session,
    project_id: uuid.UUID,
    scene_id: uuid.UUID | None,
    shot_id: uuid.UUID | None,
) -> None:
    """Фильтры по чужой сцене/шуту — 404, а не пустая страница."""

    if scene_id is not None:
        owner = session.scalar(select(Scene.project_id).where(Scene.id == scene_id))
        if owner != project_id:
            raise HTTPException(status_code=404, detail="scene not found")
    if shot_id is not None:
        owner = session.scalar(
            select(Scene.project_id)
            .join(Shot, Shot.scene_id == Scene.id)
            .where(Shot.id == shot_id)
        )
        if owner != project_id:
            raise HTTPException(status_code=404, detail="shot not found")


@router.get("/projects/{project_id}/attempts", response_model=AttemptPage)
def list_project_attempts(
    project_id: uuid.UUID,
    scene_id: uuid.UUID | None = Query(default=None),
    shot_id: uuid.UUID | None = Query(default=None),
    kind: AttemptKind | None = Query(default=None),
    status_filter: AttemptStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> AttemptPage:
    require_project(session, project_id)
    _require_filter_owner(session, project_id, scene_id, shot_id)

    conditions = [Scene.project_id == project_id]
    if scene_id is not None:
        conditions.append(Shot.scene_id == scene_id)
    if shot_id is not None:
        conditions.append(Shot.id == shot_id)
    if kind is not None:
        conditions.append(RenderAttempt.kind == kind)
    if status_filter is not None:
        conditions.append(RenderAttempt.status == status_filter)

    total = session.scalar(
        select(func.count(RenderAttempt.id))
        .join(Shot, Shot.id == RenderAttempt.shot_id)
        .join(Scene, Scene.id == Shot.scene_id)
        .where(*conditions)
    )

    rows = session.execute(
        select(RenderAttempt, Shot, Scene)
        .join(Shot, Shot.id == RenderAttempt.shot_id)
        .join(Scene, Scene.id == Shot.scene_id)
        .where(*conditions)
        .order_by(RenderAttempt.created_at.desc(), RenderAttempt.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    artifacts = _artifact_ids(session, [attempt.id for attempt, _, _ in rows])
    items = [
        AttemptListItemOut.from_attempt_on_shot(
            attempt, artifacts.get(attempt.id), shot, scene
        )
        for attempt, shot, scene in rows
    ]
    return AttemptPage(items=items, total=total or 0, limit=limit, offset=offset)
