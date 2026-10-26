from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_store
from app.api.schemas import ReferenceMetaUpdate, ReferenceOut
from app.models import ReferenceAsset
from app.storage import BlobStore, StorageError

router = APIRouter(prefix="/api/reference-assets", tags=["reference-assets"])

_REVIEW_TRANSITIONS = {
    "approve": {"draft", "rejected"},
    "reject": {"draft", "approved"},
}


def _require_asset(session: Session, asset_id: uuid.UUID) -> ReferenceAsset:
    asset = session.get(ReferenceAsset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="reference asset not found")
    return asset


@router.get("/{asset_id}", response_model=ReferenceOut)
def get_reference_asset(
    asset_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> ReferenceOut:
    return ReferenceOut.from_asset(_require_asset(session, asset_id))


@router.get("/{asset_id}/content")
def download_reference_asset(
    asset_id: uuid.UUID,
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
) -> FileResponse:
    asset = _require_asset(session, asset_id)
    storage_key = asset.storage_key
    mime_type = asset.mime_type

    try:
        path = store.resolve(storage_key)
    except StorageError as error:
        raise HTTPException(status_code=500, detail=f"invalid storage_key: {error}") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="reference content is missing")
    return FileResponse(path, media_type=mime_type)


def _review(
    session: Session, asset_id: uuid.UUID, action: str, target_status: str
) -> ReferenceOut:
    asset = _require_asset(session, asset_id)
    if asset.status == target_status:
        return ReferenceOut.from_asset(asset)
    if asset.status not in _REVIEW_TRANSITIONS[action]:
        raise HTTPException(
            status_code=409,
            detail=f"cannot {action} reference in status '{asset.status}'",
        )

    asset.status = target_status
    if target_status == "approved":
        asset.approved_at = datetime.now(timezone.utc)
    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="database rejected the reference transition"
        ) from error
    session.refresh(asset)
    return ReferenceOut.from_asset(asset)


@router.patch("/{asset_id}", response_model=ReferenceOut)
def update_reference_asset(
    asset_id: uuid.UUID,
    payload: ReferenceMetaUpdate,
    session: Session = Depends(get_session),
) -> ReferenceOut:
    """Разметка до утверждения; approved-референс неизменяем (S15)."""

    asset = _require_asset(session, asset_id)
    if asset.status not in {"draft", "rejected"}:
        raise HTTPException(
            status_code=409,
            detail=f"cannot relabel reference in status '{asset.status}'",
        )
    for field in payload.model_fields_set:
        setattr(asset, field, getattr(payload, field))
    session.commit()
    session.refresh(asset)
    return ReferenceOut.from_asset(asset)


@router.post("/{asset_id}/approve", response_model=ReferenceOut)
def approve_reference_asset(
    asset_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> ReferenceOut:
    return _review(session, asset_id, "approve", "approved")


@router.post("/{asset_id}/reject", response_model=ReferenceOut)
def reject_reference_asset(
    asset_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> ReferenceOut:
    return _review(session, asset_id, "reject", "rejected")
