from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_settings, get_store
from app.api.schemas import ReferenceOut
from app.api.shot_schemas import (
    CompositionLayerOut,
    CompositionOut,
    CompositionRenderOut,
    CompositionSummary,
    CompositionWarningOut,
    CompositionWrite,
)
from app.api.shots import composition_summaries, require_shot, shot_project_id
from app.composer import CompositionError, CompositionLayer, compose
from app.config import Settings
from app.models import (
    Artifact,
    ReferenceAsset,
    ShotComposition,
    ShotCompositionLayer,
)
from app.storage import BlobStore

router = APIRouter(prefix="/api/shots/{shot_id}/compositions", tags=["compositions"])


def require_composition(
    session: Session, shot_id: uuid.UUID, revision: int
) -> ShotComposition:
    composition = session.scalar(
        select(ShotComposition).where(
            ShotComposition.shot_id == shot_id,
            ShotComposition.revision == revision,
        )
    )
    if composition is None:
        raise HTTPException(status_code=404, detail="composition revision not found")
    return composition


def _assets_by_id(
    session: Session, asset_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ReferenceAsset]:
    if not asset_ids:
        return {}
    return {
        asset.id: asset
        for asset in session.scalars(
            select(ReferenceAsset).where(ReferenceAsset.id.in_(asset_ids))
        )
    }


def _layer_specs(
    session: Session, composition: ShotComposition
) -> list[CompositionLayer]:
    rows = list(
        session.scalars(
            select(ShotCompositionLayer)
            .where(ShotCompositionLayer.composition_id == composition.id)
            .order_by(ShotCompositionLayer.z_index)
        )
    )
    assets = _assets_by_id(session, [row.reference_asset_id for row in rows])
    specs: list[CompositionLayer] = []
    for row in rows:
        asset = assets.get(row.reference_asset_id)
        if asset is None:
            raise HTTPException(
                status_code=409, detail="composition layer reference is missing"
            )
        specs.append(
            CompositionLayer(
                reference_asset_id=asset.id,
                kind=asset.kind,
                storage_key=asset.storage_key,
                z_index=row.z_index,
                x=float(row.x),
                y=float(row.y),
                scale=float(row.scale),
                rotation=float(row.rotation),
                opacity=float(row.opacity),
            )
        )
    return specs


def _composition_out(session: Session, composition: ShotComposition) -> CompositionOut:
    rows = list(
        session.scalars(
            select(ShotCompositionLayer)
            .where(ShotCompositionLayer.composition_id == composition.id)
            .order_by(ShotCompositionLayer.z_index)
        )
    )
    assets = _assets_by_id(session, [row.reference_asset_id for row in rows])
    layers: list[CompositionLayerOut] = []
    for row in rows:
        asset = assets.get(row.reference_asset_id)
        if asset is None:
            continue
        layers.append(CompositionLayerOut.from_layer(row, ReferenceOut.from_asset(asset)))
    summary = CompositionSummary.from_composition(composition, len(rows))
    return CompositionOut(**summary.model_dump(), layers=layers)


def _validate_payload(payload: CompositionWrite, settings: Settings) -> None:
    if len(payload.layers) > settings.composition_max_layers:
        raise HTTPException(
            status_code=413,
            detail=f"composition exceeds {settings.composition_max_layers} layers",
        )
    if payload.width * payload.height > settings.composition_max_pixels:
        raise HTTPException(
            status_code=413,
            detail=f"composition exceeds {settings.composition_max_pixels} pixels",
        )
    z_indexes = [layer.z_index for layer in payload.layers]
    if len(set(z_indexes)) != len(z_indexes):
        raise HTTPException(status_code=422, detail="layer z_index values must be unique")


def _check_layer_assets(
    session: Session, payload: CompositionWrite, project_id: uuid.UUID
) -> None:
    assets = _assets_by_id(session, [layer.reference_asset_id for layer in payload.layers])
    for layer in payload.layers:
        asset = assets.get(layer.reference_asset_id)
        if asset is None or asset.project_id != project_id:
            raise HTTPException(status_code=404, detail="reference asset not found")
        if asset.status != "approved" and asset.kind != "uploaded":
            raise HTTPException(
                status_code=409,
                detail=f"layer z={layer.z_index} needs an approved or uploaded reference",
            )


def _replace_layers(
    session: Session, composition: ShotComposition, payload: CompositionWrite
) -> None:
    session.execute(
        delete(ShotCompositionLayer).where(
            ShotCompositionLayer.composition_id == composition.id
        )
    )
    composition.width = payload.width
    composition.height = payload.height
    for layer in payload.layers:
        session.add(
            ShotCompositionLayer(
                project_id=composition.project_id,
                composition_id=composition.id,
                reference_asset_id=layer.reference_asset_id,
                z_index=layer.z_index,
                x=layer.x,
                y=layer.y,
                scale=layer.scale,
                rotation=layer.rotation,
                opacity=layer.opacity,
            )
        )


@router.get("", response_model=list[CompositionSummary])
def list_compositions(
    shot_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[CompositionSummary]:
    require_shot(session, shot_id)
    return composition_summaries(session, shot_id)


@router.post("", response_model=CompositionOut, status_code=status.HTTP_201_CREATED)
def create_composition(
    shot_id: uuid.UUID,
    payload: CompositionWrite,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CompositionOut:
    shot = require_shot(session, shot_id)
    project_id = shot_project_id(session, shot)
    _validate_payload(payload, settings)
    _check_layer_assets(session, payload, project_id)

    revision = (
        session.scalar(
            select(func.coalesce(func.max(ShotComposition.revision), 0)).where(
                ShotComposition.shot_id == shot.id
            )
        )
        + 1
    )
    composition = ShotComposition(
        project_id=project_id,
        shot_id=shot.id,
        revision=revision,
        width=payload.width,
        height=payload.height,
        status="draft",
    )
    session.add(composition)
    session.flush()
    _replace_layers(session, composition, payload)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="composition revision already exists"
        ) from error
    session.refresh(composition)
    return _composition_out(session, composition)


@router.get("/{revision}", response_model=CompositionOut)
def get_composition(
    shot_id: uuid.UUID,
    revision: int,
    session: Session = Depends(get_session),
) -> CompositionOut:
    require_shot(session, shot_id)
    return _composition_out(session, require_composition(session, shot_id, revision))


@router.put("/{revision}", response_model=CompositionOut)
def update_composition(
    shot_id: uuid.UUID,
    revision: int,
    payload: CompositionWrite,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> CompositionOut:
    shot = require_shot(session, shot_id)
    composition = require_composition(session, shot_id, revision)
    if composition.status != "draft":
        raise HTTPException(
            status_code=409, detail="only a draft composition can be edited"
        )
    project_id = shot_project_id(session, shot)
    _validate_payload(payload, settings)
    _check_layer_assets(session, payload, project_id)

    _replace_layers(session, composition, payload)
    # Правка draft делает старый предпросмотр недействительным.
    composition.preview_artifact_id = None
    composition.approved_at = None
    session.commit()
    session.refresh(composition)
    return _composition_out(session, composition)


@router.post("/{revision}/render", response_model=CompositionRenderOut)
def render_composition(
    shot_id: uuid.UUID,
    revision: int,
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
    settings: Settings = Depends(get_settings),
) -> CompositionRenderOut:
    require_shot(session, shot_id)
    composition = require_composition(session, shot_id, revision)
    specs = _layer_specs(session, composition)

    try:
        result = compose(
            specs,
            width=composition.width,
            height=composition.height,
            store=store,
            max_pixels=settings.composition_max_pixels,
            max_layers=settings.composition_max_layers,
        )
    except CompositionError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error

    blob = store.put_bytes(result.png, suffix=".png")
    artifact = Artifact(
        source="composition",
        kind="composition_preview",
        shot_composition_id=composition.id,
        storage_key=blob.storage_key,
        sha256=blob.sha256,
        bytes=blob.size,
        mime_type="image/png",
    )
    session.add(artifact)
    session.flush()
    # S8: повторный render не переписывает preview-указатель ревизии.
    if composition.preview_artifact_id is None:
        composition.preview_artifact_id = artifact.id
    session.commit()
    session.refresh(artifact)
    session.refresh(composition)

    return CompositionRenderOut(
        artifact_id=artifact.id,
        content_url=f"/api/artifacts/{artifact.id}/content",
        width=result.width,
        height=result.height,
        preview_artifact_id=composition.preview_artifact_id,
        warnings=[
            CompositionWarningOut(
                code=warning.code,
                message=warning.message,
                z_index=warning.z_index,
                reference_asset_id=warning.reference_asset_id,
            )
            for warning in result.warnings
        ],
    )


@router.post("/{revision}/approve", response_model=CompositionOut)
def approve_composition(
    shot_id: uuid.UUID,
    revision: int,
    session: Session = Depends(get_session),
) -> CompositionOut:
    require_shot(session, shot_id)
    composition = require_composition(session, shot_id, revision)
    if composition.status == "approved":
        return _composition_out(session, composition)
    if composition.status != "draft":
        raise HTTPException(
            status_code=409, detail="only a draft composition can be approved"
        )
    if composition.preview_artifact_id is None:
        raise HTTPException(
            status_code=409, detail="render the composition before approving"
        )

    other = session.scalar(
        select(ShotComposition).where(
            ShotComposition.shot_id == shot_id,
            ShotComposition.status == "approved",
            ShotComposition.id != composition.id,
        )
    )
    if other is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "another composition revision is approved; "
                "supersede it before approving a new one"
            ),
        )

    composition.status = "approved"
    composition.approved_at = datetime.now(timezone.utc)
    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="database rejected the composition transition"
        ) from error
    session.refresh(composition)
    return _composition_out(session, composition)


@router.post("/{revision}/supersede", response_model=CompositionOut)
def supersede_composition(
    shot_id: uuid.UUID,
    revision: int,
    session: Session = Depends(get_session),
) -> CompositionOut:
    require_shot(session, shot_id)
    composition = require_composition(session, shot_id, revision)
    if composition.status == "superseded":
        return _composition_out(session, composition)
    if composition.status != "approved":
        raise HTTPException(
            status_code=409, detail="only an approved composition can be superseded"
        )
    composition.status = "superseded"
    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="database rejected the composition transition"
        ) from error
    session.refresh(composition)
    return _composition_out(session, composition)
