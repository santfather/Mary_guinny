from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import ProjectOut, ReferenceOut
from app.models import Project, ReferenceAsset

router = APIRouter(prefix="/api/projects", tags=["projects"])

ReferenceStatus = Literal["draft", "approved", "rejected", "superseded"]
ReferenceKind = Literal[
    "character_reference", "location_reference", "prop_reference", "uploaded"
]


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.title)))


@router.get("/{project_id}/references", response_model=list[ReferenceOut])
def list_project_references(
    project_id: uuid.UUID,
    status: ReferenceStatus | None = None,
    kind: ReferenceKind | None = None,
    session: Session = Depends(get_session),
) -> list[ReferenceOut]:
    """Все референсы проекта для пикера слоёв композиции (WP-05)."""

    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")

    statement = select(ReferenceAsset).where(ReferenceAsset.project_id == project_id)
    if status is not None:
        statement = statement.where(ReferenceAsset.status == status)
    if kind is not None:
        statement = statement.where(ReferenceAsset.kind == kind)
    statement = statement.order_by(ReferenceAsset.created_at, ReferenceAsset.sha256)
    return [
        ReferenceOut.from_asset(asset) for asset in session.scalars(statement)
    ]
