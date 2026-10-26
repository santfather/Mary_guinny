from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import PropDetail, PropSummary, ReferenceOut
from app.models import Project, Prop, ReferenceAsset

router = APIRouter(prefix="/api", tags=["props"])


def _require_project(session: Session, project_id: uuid.UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _references_by_prop(
    session: Session, project_id: uuid.UUID
) -> dict[uuid.UUID, list[ReferenceAsset]]:
    grouped: dict[uuid.UUID, list[ReferenceAsset]] = {}
    for asset in session.scalars(
        select(ReferenceAsset)
        .where(
            ReferenceAsset.project_id == project_id,
            ReferenceAsset.prop_id.is_not(None),
        )
        .order_by(ReferenceAsset.created_at, ReferenceAsset.sha256)
    ):
        grouped.setdefault(asset.prop_id, []).append(asset)  # type: ignore[arg-type]
    return grouped


@router.get("/projects/{project_id}/props", response_model=list[PropSummary])
def list_props(
    project_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> list[PropSummary]:
    _require_project(session, project_id)
    props = session.scalars(
        select(Prop).where(Prop.project_id == project_id).order_by(Prop.name)
    )
    grouped = _references_by_prop(session, project_id)
    return [
        PropSummary(
            id=prop.id,
            slug=prop.slug,
            name=prop.name,
            description=prop.description,
            status=prop.status,
            reference_count=len(grouped.get(prop.id, [])),
        )
        for prop in props
    ]


@router.get("/props/{prop_id}", response_model=PropDetail)
def get_prop(
    prop_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> PropDetail:
    prop = session.get(Prop, prop_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="prop not found")
    references = _references_by_prop(session, prop.project_id).get(prop.id, [])
    return PropDetail(
        id=prop.id,
        slug=prop.slug,
        name=prop.name,
        description=prop.description,
        status=prop.status,
        reference_count=len(references),
        references=[ReferenceOut.from_asset(asset) for asset in references],
    )
