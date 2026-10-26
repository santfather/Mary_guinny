from __future__ import annotations

import hashlib
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.artifacts import read_body_with_limit
from app.api.deps import get_session, get_settings, get_store
from app.api.schemas import ProjectOut, ReferenceOut, ReferencePose, ReferenceView
from app.config import Settings
from app.image_probe import ImageProbeError, probe_image_bytes
from app.models import Character, Location, Project, Prop, ReferenceAsset
from app.storage import BlobStore

router = APIRouter(prefix="/api/projects", tags=["projects"])

ReferenceStatus = Literal["draft", "approved", "rejected", "superseded"]
ReferenceKind = Literal[
    "character_reference", "location_reference", "prop_reference", "uploaded"
]

_MIME_SUFFIX = {"image/png": ".png", "image/jpeg": ".jpg"}


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


def _check_owner(
    session: Session,
    project_id: uuid.UUID,
    kind: str,
    character_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
    prop_id: uuid.UUID | None,
) -> None:
    owners = {
        "character_reference": (character_id, Character, "character"),
        "location_reference": (location_id, Location, "location"),
        "prop_reference": (prop_id, Prop, "prop"),
    }
    provided = {
        "character_id": character_id,
        "location_id": location_id,
        "prop_id": prop_id,
    }
    if kind == "uploaded":
        if any(value is not None for value in provided.values()):
            raise HTTPException(
                status_code=422, detail="uploaded reference must not have an owner"
            )
        return

    owner_id, model, label = owners[kind]
    if owner_id is None:
        raise HTTPException(
            status_code=422, detail=f"{kind} requires {label}_id"
        )
    for field, value in provided.items():
        if field != f"{label}_id" and value is not None:
            raise HTTPException(
                status_code=422, detail=f"{kind} cannot reference another owner"
            )
    owner = session.get(model, owner_id)
    if owner is None or owner.project_id != project_id:
        raise HTTPException(status_code=404, detail=f"{label} not found")


@router.post(
    "/{project_id}/references",
    response_model=ReferenceOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_reference(
    project_id: uuid.UUID,
    request: Request,
    response: Response,
    kind: ReferenceKind = Query(...),
    character_id: uuid.UUID | None = Query(default=None),
    location_id: uuid.UUID | None = Query(default=None),
    prop_id: uuid.UUID | None = Query(default=None),
    view: ReferenceView | None = Query(default=None),
    pose: ReferencePose | None = Query(default=None),
    expression: str | None = Query(default=None, max_length=200),
    role: str | None = Query(default=None, max_length=64),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> ReferenceOut:
    """Загрузка PNG/JPEG в существующий BlobStore; sha256 считает сервер."""

    if session.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    _check_owner(session, project_id, kind, character_id, location_id, prop_id)

    body = await read_body_with_limit(request, settings.reference_upload_max_bytes)
    if not body:
        raise HTTPException(status_code=422, detail="empty body")
    try:
        info = probe_image_bytes(body)
    except ImageProbeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if info.width * info.height > settings.reference_max_pixels:
        raise HTTPException(
            status_code=413,
            detail=f"reference exceeds {settings.reference_max_pixels} pixels",
        )

    digest = hashlib.sha256(body).hexdigest()
    existing = session.scalar(
        select(ReferenceAsset).where(
            ReferenceAsset.project_id == project_id, ReferenceAsset.sha256 == digest
        )
    )
    if existing is not None:
        same_owner = (
            existing.kind == kind
            and existing.character_id == character_id
            and existing.location_id == location_id
            and existing.prop_id == prop_id
        )
        if same_owner:
            response.status_code = status.HTTP_200_OK
            return ReferenceOut.from_asset(existing)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "duplicate_reference",
                "reference_asset_id": str(existing.id),
            },
        )

    blob = store.put_bytes(body, suffix=_MIME_SUFFIX.get(info.mime_type, ""))
    asset = ReferenceAsset(
        project_id=project_id,
        kind=kind,
        character_id=character_id,
        location_id=location_id,
        prop_id=prop_id,
        status="draft",
        role=role,
        view=view,
        pose=pose,
        expression=expression,
        storage_key=blob.storage_key,
        sha256=blob.sha256,
        width=info.width,
        height=info.height,
        mime_type=info.mime_type,
        metadata_json={"has_alpha": info.has_alpha, "source": "upload"},
    )
    session.add(asset)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "duplicate_reference"},
        ) from error
    session.refresh(asset)
    return ReferenceOut.from_asset(asset)
