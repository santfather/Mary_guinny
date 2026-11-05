"""API viseme-набора: импорт пяти кадров морды и проверка совместимости.

WP-VOICE-06. Набор хранится в существующих `reference_assets` с ролью
`viseme_<state>` — без миграций. Генерация блокируется, пока набор неполный,
не утверждён или не проходит проверку совместимости.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.artifacts import read_body_with_limit
from app.api.deps import get_session, get_settings, get_store
from app.api.mouth_animation import resolve_calibration
from app.api.mouth_sources import region_from_calibration, resolve_source_image
from app.api.shots import require_shot, shot_project_id
from app.config import Settings
from app.image_probe import ImageProbeError, probe_image_bytes
from app.models import ReferenceAsset, ShotReference
from app.rhubarb import RhubarbError, binary_path, verify_binary
from app.storage import BlobStore
from app.viseme_assets import (
    VISEME_STATES,
    VisemeError,
    comparison_sheet,
    role_for,
    state_from_role,
)
from app.viseme_service import load_entries, read_entry, set_report

router = APIRouter(prefix="/api", tags=["viseme-set"])

_MIME_SUFFIX = {"image/png": ".png", "image/jpeg": ".jpg"}


class VisemeVariantOut(BaseModel):
    state: str
    reference_asset_id: uuid.UUID | None
    status: str
    approved: bool
    implicit: bool
    width: int | None
    height: int | None
    sha256: str
    content_url: str


class VisemeSetOut(BaseModel):
    shot_id: uuid.UUID
    source_reference_asset_id: uuid.UUID | None
    source_artifact_id: uuid.UUID | None
    calibration_id: uuid.UUID
    variants: list[VisemeVariantOut]
    missing: list[str]
    ready: bool
    blockers: list[dict[str, str]]
    metrics: dict[str, Any]
    preview_url: str


class RhubarbStatusOut(BaseModel):
    installed: bool
    verified: bool
    path: str
    version: str
    license: str
    release_page: str
    arch: str | None
    sha256: str | None
    rosetta: bool | None = None
    reasons: list[dict[str, str]]
    notes: list[dict[str, str]] = []
    expected_arch: str
    download_performed: bool


def _default_source_reference(session: Session, shot) -> uuid.UUID | None:  # noqa: ANN001
    """Approved-изображение шота — источник, если стартового кадра нет."""

    rows = list(
        session.scalars(
            select(ReferenceAsset)
            .join(ShotReference, ShotReference.reference_asset_id == ReferenceAsset.id)
            .where(
                ShotReference.shot_id == shot.id,
                ReferenceAsset.status == "approved",
            )
            .order_by(ReferenceAsset.created_at, ReferenceAsset.sha256)
        )
    )
    images = [
        asset
        for asset in rows
        if (asset.mime_type or "").startswith("image/")
        and state_from_role(asset.role) is None
        and (asset.metadata_json or {}).get("multi_view") is not True
    ]
    if not images:
        return None
    start = [asset for asset in images if (asset.role or "").endswith("_start")]
    return (start or images)[0].id


def _resolve_set_context(
    session: Session,
    store: BlobStore,
    shot_id: uuid.UUID,
    reference_asset_id: uuid.UUID | None,
    calibration_id: uuid.UUID | None,
):
    shot = require_shot(session, shot_id)
    shot_project_id(session, shot)
    if reference_asset_id is None and shot.start_keyframe_artifact_id is None:
        reference_asset_id = _default_source_reference(session, shot)
    source = resolve_source_image(session, shot, reference_asset_id, store=store)
    calibration = resolve_calibration(session, shot.id, source, calibration_id)
    region = region_from_calibration(calibration)
    try:
        region.validate()
    except Exception as error:  # noqa: BLE001 - MouthAnimationError с кодом
        code = getattr(error, "code", "mouth_region_out_of_bounds")
        message = getattr(error, "message", str(error))
        raise HTTPException(
            status_code=409, detail={"error": code, "message": message}
        ) from error
    entries = load_entries(session, shot, source)
    return shot, source, calibration, entries, region


def _variant_out(state: str, entry) -> VisemeVariantOut:  # noqa: ANN001
    return VisemeVariantOut(
        state=state,
        reference_asset_id=entry.asset_id,
        status=entry.status,
        approved=entry.status == "approved",
        implicit=entry.implicit,
        width=entry.width,
        height=entry.height,
        sha256=entry.sha256,
        content_url=entry.content_url,
    )


@router.get("/shots/{shot_id}/viseme-set", response_model=VisemeSetOut)
def get_viseme_set(
    shot_id: uuid.UUID,
    reference_asset_id: uuid.UUID | None = Query(default=None),
    calibration_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> VisemeSetOut:
    """Состав набора и отчёт совместимости: источник — approved-кадр шота."""

    shot, source, calibration, entries, region = _resolve_set_context(
        session, store, shot_id, reference_asset_id, calibration_id
    )
    report = set_report(
        store,
        source.read(store),
        entries,
        region,
        outside_max_ratio=settings.viseme_outside_max_ratio,
        max_shift_px=settings.viseme_max_shift_px,
    )
    query = []
    if reference_asset_id is not None:
        query.append(f"reference_asset_id={reference_asset_id}")
    query.append(f"calibration_id={calibration.id}")
    return VisemeSetOut(
        shot_id=shot.id,
        source_reference_asset_id=source.reference_asset_id,
        source_artifact_id=source.artifact_id,
        calibration_id=calibration.id,
        variants=[
            _variant_out(state, entries[state])
            for state in VISEME_STATES
            if state in entries
        ],
        missing=report.missing,
        ready=report.ready,
        blockers=report.blockers,
        metrics=report.metrics,
        preview_url=f"/api/shots/{shot.id}/viseme-set/preview?{'&'.join(query)}",
    )


@router.get("/shots/{shot_id}/viseme-set/preview")
def get_viseme_set_preview(
    shot_id: uuid.UUID,
    reference_asset_id: uuid.UUID | None = Query(default=None),
    calibration_id: uuid.UUID | None = Query(default=None),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> Response:
    """PNG-лист сравнения: источник и пять вариантов с рамкой области морды."""

    shot, source, _calibration, entries, region = _resolve_set_context(
        session, store, shot_id, reference_asset_id, calibration_id
    )
    payloads = {}
    for state, entry in entries.items():
        try:
            payloads[state] = read_entry(store, entry)
        except VisemeError:
            continue
    try:
        png = comparison_sheet(source.read(store), payloads, region)
    except VisemeError as error:
        raise HTTPException(
            status_code=422, detail={"error": error.code, "message": error.message}
        ) from error
    return Response(
        content=png, media_type="image/png", headers={"Cache-Control": "no-store"}
    )


@router.post(
    "/shots/{shot_id}/viseme-set/{state}",
    response_model=VisemeVariantOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_viseme_variant(
    shot_id: uuid.UUID,
    state: str,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> VisemeVariantOut:
    """Импорт одного кадра морды; оригинал сохраняется, статус — `draft`."""

    if state not in VISEME_STATES:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "viseme_state_invalid",
                "message": "state должен быть одним из: " + ", ".join(VISEME_STATES),
            },
        )

    shot = require_shot(session, shot_id)
    project_id = shot_project_id(session, shot)
    body = await read_body_with_limit(request, settings.viseme_upload_max_bytes)
    if not body:
        raise HTTPException(
            status_code=422,
            detail={"error": "viseme_image_invalid", "message": "пустой файл"},
        )
    try:
        info = probe_image_bytes(body)
    except ImageProbeError as error:
        raise HTTPException(
            status_code=422,
            detail={"error": "viseme_image_invalid", "message": str(error)},
        ) from error
    if info.width * info.height > settings.reference_max_pixels:
        raise HTTPException(
            status_code=413,
            detail={"error": "viseme_image_invalid", "message": "слишком большое изображение"},
        )

    digest = hashlib.sha256(body).hexdigest()
    existing = session.scalar(
        select(ReferenceAsset).where(
            ReferenceAsset.project_id == project_id,
            ReferenceAsset.sha256 == digest,
        )
    )
    role = role_for(state)

    if existing is not None:
        if existing.role == role:
            link = session.scalar(
                select(ShotReference.id).where(
                    ShotReference.shot_id == shot.id,
                    ShotReference.reference_asset_id == existing.id,
                )
            )
            if link is None:
                session.add(
                    ShotReference(
                        project_id=project_id,
                        shot_id=shot.id,
                        reference_asset_id=existing.id,
                        purpose="other",
                    )
                )
                session.commit()
            response.status_code = status.HTTP_200_OK
            return VisemeVariantOut(
                state=state,
                reference_asset_id=existing.id,
                status=existing.status,
                approved=existing.status == "approved",
                implicit=False,
                width=existing.width,
                height=existing.height,
                sha256=existing.sha256,
                content_url=f"/api/reference-assets/{existing.id}/content",
            )

        # `closed` может совпадать с approved-источником побайтно.
        source = None
        try:
            source = resolve_source_image(
                session, shot, _default_source_reference(session, shot), store=store
            )
        except HTTPException:
            source = None
        if state == "closed" and source is not None and source.sha256 == digest:
            response.status_code = status.HTTP_200_OK
            return VisemeVariantOut(
                state=state,
                reference_asset_id=source.reference_asset_id,
                status="approved",
                approved=True,
                implicit=True,
                width=None,
                height=None,
                sha256=digest,
                content_url=(
                    f"/api/reference-assets/{source.reference_asset_id}/content"
                    if source.reference_asset_id
                    else f"/api/artifacts/{source.artifact_id}/content"
                ),
            )
        raise HTTPException(
            status_code=409,
            detail={
                "error": "duplicate_reference",
                "reference_asset_id": str(existing.id),
                "message": "этот файл уже загружен в проект в другой роли",
            },
        )

    blob = store.put_bytes(body, suffix=_MIME_SUFFIX.get(info.mime_type, ""))
    asset = ReferenceAsset(
        project_id=project_id,
        kind="uploaded",
        status="draft",
        role=role,
        storage_key=blob.storage_key,
        sha256=blob.sha256,
        width=info.width,
        height=info.height,
        mime_type=info.mime_type,
        metadata_json={
            "has_alpha": info.has_alpha,
            "source": "upload",
            "viseme_set": True,
            "viseme_state": state,
        },
    )
    session.add(asset)
    try:
        session.flush()
        session.add(
            ShotReference(
                project_id=project_id,
                shot_id=shot.id,
                reference_asset_id=asset.id,
                purpose="other",
            )
        )
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={"error": "duplicate_reference", "message": str(error.orig)},
        ) from error
    session.refresh(asset)

    return VisemeVariantOut(
        state=state,
        reference_asset_id=asset.id,
        status=asset.status,
        approved=False,
        implicit=False,
        width=asset.width,
        height=asset.height,
        sha256=asset.sha256,
        content_url=f"/api/reference-assets/{asset.id}/content",
    )


@router.get("/rhubarb/status", response_model=RhubarbStatusOut)
def get_rhubarb_status(
    settings: Settings = Depends(get_settings),
) -> RhubarbStatusOut:
    """Read-only статус Rhubarb: установлен/проверен. Скачивания нет."""

    try:
        configured = binary_path(settings.rhubarb_binary)
    except RhubarbError as error:
        raise HTTPException(
            status_code=409, detail={"error": error.code, "message": error.message}
        ) from error
    result = verify_binary(
        configured=configured, expected_sha256=settings.rhubarb_sha256
    )
    return RhubarbStatusOut(**result.as_dict())
