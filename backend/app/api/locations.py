from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.schemas import LocationDetail, LocationSummary, ReferenceOut
from app.models import Location, Project, ReferenceAsset

router = APIRouter(prefix="/api", tags=["locations"])


def _require_project(session: Session, project_id: uuid.UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _references_by_location(
    session: Session, project_id: uuid.UUID
) -> dict[uuid.UUID, list[ReferenceAsset]]:
    grouped: dict[uuid.UUID, list[ReferenceAsset]] = {}
    for asset in session.scalars(
        select(ReferenceAsset)
        .where(
            ReferenceAsset.project_id == project_id,
            ReferenceAsset.location_id.is_not(None),
        )
        .order_by(ReferenceAsset.created_at, ReferenceAsset.sha256)
    ):
        grouped.setdefault(asset.location_id, []).append(asset)  # type: ignore[arg-type]
    return grouped


@router.get("/projects/{project_id}/locations", response_model=list[LocationSummary])
def list_locations(
    project_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> list[LocationSummary]:
    _require_project(session, project_id)
    locations = session.scalars(
        select(Location)
        .where(Location.project_id == project_id)
        .order_by(Location.name)
    )
    grouped = _references_by_location(session, project_id)
    return [
        LocationSummary(
            id=location.id,
            slug=location.slug,
            name=location.name,
            description=location.description,
            status=location.status,
            reference_count=len(grouped.get(location.id, [])),
        )
        for location in locations
    ]


@router.get("/locations/{location_id}", response_model=LocationDetail)
def get_location(
    location_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> LocationDetail:
    location = session.get(Location, location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="location not found")
    references = _references_by_location(session, location.project_id).get(location.id, [])
    return LocationDetail(
        id=location.id,
        slug=location.slug,
        name=location.name,
        description=location.description,
        status=location.status,
        reference_count=len(references),
        references=[ReferenceOut.from_asset(asset) for asset in references],
    )
