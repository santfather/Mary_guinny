"""API Visual Scene Plan (WP-05A): ревизии, approve/supersede, план → композиция."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.api.compositions import composition_out
from app.api.deps import get_session, get_settings, get_store
from app.api.scene_plan_schemas import (
    PlanReferenceIn,
    ScenePlanCandidate,
    ScenePlanCreate,
    ScenePlanGenerateRequest,
    ScenePlanOut,
    ScenePlanWarningOut,
    ScenePlanWrite,
)
from app.api.shot_schemas import CompositionOut
from app.api.shots import require_shot, shot_project_id
from app.config import Settings
from app.image_probe import ImageProbeError, probe_image_bytes
from app.models import (
    ReferenceAsset,
    ShotComposition,
    ShotCompositionLayer,
    VisualScenePlan,
)
from app.planner import (
    PlanError,
    PlanReference,
    default_canvas,
    generate_candidate,
    validate_plan,
)
from app.storage import BlobStore, StorageError

router = APIRouter(prefix="/api/shots/{shot_id}/scene-plans", tags=["scene-plans"])

_OWNER_FIELD_BY_ROLE = {
    "character": "character_id",
    "location": "location_id",
    "prop": "prop_id",
}


def require_plan(
    session: Session, shot_id: uuid.UUID, revision: int
) -> VisualScenePlan:
    plan = session.scalar(
        select(VisualScenePlan).where(
            VisualScenePlan.shot_id == shot_id,
            VisualScenePlan.revision == revision,
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="scene plan revision not found")
    return plan


def plan_out(plan: VisualScenePlan) -> ScenePlanOut:
    return ScenePlanOut(
        id=plan.id,
        project_id=plan.project_id,
        shot_id=plan.shot_id,
        revision=plan.revision,
        schema_version=plan.schema_version,
        status=plan.status,
        source=plan.source,
        plan=ScenePlanWrite.model_validate(plan.plan),
        warnings=[ScenePlanWarningOut(**warning) for warning in plan.warnings],
        created_at=plan.created_at,
        approved_at=plan.approved_at,
    )


def _resolve_references(
    session: Session,
    project_id: uuid.UUID,
    items: list[PlanReferenceIn],
) -> list[tuple[PlanReference, ReferenceAsset]]:
    """Сервер сам связывает asset_id с владельцем и проверяет допустимость."""

    resolved: list[tuple[PlanReference, ReferenceAsset]] = []
    for item in items:
        asset = session.get(ReferenceAsset, item.asset_id)
        if asset is None or asset.project_id != project_id:
            raise HTTPException(status_code=404, detail="reference asset not found")
        if asset.status != "approved" and asset.kind != "uploaded":
            raise HTTPException(
                status_code=409,
                detail=f"reference '{item.alias}' needs an approved or uploaded asset",
            )

        owner_field = _OWNER_FIELD_BY_ROLE.get(item.role)
        if owner_field is not None:
            owner_id = getattr(asset, owner_field)
            if owner_id is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"reference '{item.alias}' has no {item.role} owner",
                )
            if item.entity_id is not None and item.entity_id != owner_id:
                raise HTTPException(
                    status_code=422,
                    detail=f"reference '{item.alias}' entity_id does not match its asset",
                )
            entity_id = owner_id
        else:
            if item.entity_id is not None:
                raise HTTPException(
                    status_code=422,
                    detail=f"reference '{item.alias}' role '{item.role}' cannot have entity_id",
                )
            entity_id = None

        resolved.append(
            (
                PlanReference(
                    asset_id=asset.id,
                    role=item.role,
                    entity_id=entity_id,
                    alias=item.alias,
                ),
                asset,
            )
        )
    return resolved


def _validate_plan_payload(plan: ScenePlanWrite) -> dict[str, Any]:
    payload = plan.to_plan()
    try:
        validate_plan(payload)
    except PlanError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return payload


def _apply_resolved_entities(
    payload: dict[str, Any], resolved: list[tuple[PlanReference, ReferenceAsset]]
) -> None:
    """Сервер фиксирует владельца референса, даже если клиент его не прислал."""

    by_asset = {
        str(reference.asset_id): reference.entity_id for reference, _asset in resolved
    }
    for item in payload["references"]:
        entity_id = by_asset.get(str(item["asset_id"]))
        if entity_id is not None:
            item["entity_id"] = str(entity_id)


@router.get("", response_model=list[ScenePlanOut])
def list_scene_plans(
    shot_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[ScenePlanOut]:
    require_shot(session, shot_id)
    plans = session.scalars(
        select(VisualScenePlan)
        .where(VisualScenePlan.shot_id == shot_id)
        .order_by(VisualScenePlan.revision.desc())
    )
    return [plan_out(plan) for plan in plans]


@router.get("/{revision}", response_model=ScenePlanOut)
def get_scene_plan(
    shot_id: uuid.UUID, revision: int, session: Session = Depends(get_session)
) -> ScenePlanOut:
    require_shot(session, shot_id)
    return plan_out(require_plan(session, shot_id, revision))


@router.post("", response_model=ScenePlanOut, status_code=status.HTTP_201_CREATED)
def create_scene_plan(
    shot_id: uuid.UUID,
    payload: ScenePlanCreate,
    response: Response,
    session: Session = Depends(get_session),
) -> ScenePlanOut:
    shot = require_shot(session, shot_id)
    project_id = shot_project_id(session, shot)
    resolved = _resolve_references(session, project_id, payload.plan.references)
    plan_payload = _validate_plan_payload(payload.plan)
    _apply_resolved_entities(plan_payload, resolved)

    latest = session.scalar(
        select(VisualScenePlan)
        .where(VisualScenePlan.shot_id == shot.id)
        .order_by(VisualScenePlan.revision.desc())
        .limit(1)
    )
    if latest is not None and latest.status == "draft" and latest.plan == plan_payload:
        response.status_code = status.HTTP_200_OK
        return plan_out(latest)

    revision = (
        session.scalar(
            select(func.coalesce(func.max(VisualScenePlan.revision), 0)).where(
                VisualScenePlan.shot_id == shot.id
            )
        )
        + 1
    )
    plan = VisualScenePlan(
        project_id=project_id,
        shot_id=shot.id,
        revision=revision,
        schema_version=1,
        status="draft",
        source=payload.source,
        plan=plan_payload,
        warnings=[warning.model_dump() for warning in payload.warnings],
    )
    session.add(plan)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="scene plan revision already exists"
        ) from error
    session.refresh(plan)
    return plan_out(plan)


@router.put("/{revision}", response_model=ScenePlanOut)
def update_scene_plan(
    shot_id: uuid.UUID,
    revision: int,
    payload: ScenePlanWrite,
    session: Session = Depends(get_session),
) -> ScenePlanOut:
    shot = require_shot(session, shot_id)
    plan = require_plan(session, shot_id, revision)
    if plan.status != "draft":
        raise HTTPException(status_code=409, detail="only a draft scene plan can be edited")
    project_id = shot_project_id(session, shot)
    resolved = _resolve_references(session, project_id, payload.references)
    plan_payload = _validate_plan_payload(payload)
    _apply_resolved_entities(plan_payload, resolved)
    plan.plan = plan_payload
    session.commit()
    session.refresh(plan)
    return plan_out(plan)


@router.post("/generate", response_model=ScenePlanCandidate)
def generate_scene_plan(
    shot_id: uuid.UUID,
    payload: ScenePlanGenerateRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> ScenePlanCandidate:
    """Возвращает черновик плана, ничего не записывая в БД."""

    shot = require_shot(session, shot_id)
    project_id = shot_project_id(session, shot)
    resolved = _resolve_references(session, project_id, payload.references)

    images: list[tuple[str, bytes]] = []
    if payload.use_vision:
        for reference, asset in resolved:
            if len(images) >= settings.planner_max_images:
                break
            try:
                images.append((reference.alias, store.read_bytes(asset.storage_key)))
            except (StorageError, FileNotFoundError, OSError):
                continue

    plan, warnings, source = generate_candidate(
        [reference for reference, _asset in resolved],
        action=payload.action,
        camera=payload.camera.model_dump(),
        canvas=default_canvas(payload.canvas.width, payload.canvas.height),
        images=images,
        use_vision=payload.use_vision,
        settings=settings,
    )
    return ScenePlanCandidate(
        plan=ScenePlanWrite.model_validate(plan),
        warnings=[ScenePlanWarningOut(**warning) for warning in warnings],
        source=source,
    )


@router.post("/{revision}/approve", response_model=ScenePlanOut)
def approve_scene_plan(
    shot_id: uuid.UUID, revision: int, session: Session = Depends(get_session)
) -> ScenePlanOut:
    require_shot(session, shot_id)
    plan = require_plan(session, shot_id, revision)
    if plan.status == "approved":
        return plan_out(plan)
    if plan.status != "draft":
        raise HTTPException(
            status_code=409, detail="only a draft scene plan can be approved"
        )
    other = session.scalar(
        select(VisualScenePlan).where(
            VisualScenePlan.shot_id == shot_id,
            VisualScenePlan.status == "approved",
            VisualScenePlan.id != plan.id,
        )
    )
    if other is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "another scene plan revision is approved; "
                "supersede it before approving a new one"
            ),
        )
    plan.status = "approved"
    plan.approved_at = datetime.now(timezone.utc)
    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="database rejected the scene plan transition"
        ) from error
    session.refresh(plan)
    return plan_out(plan)


@router.post("/{revision}/supersede", response_model=ScenePlanOut)
def supersede_scene_plan(
    shot_id: uuid.UUID, revision: int, session: Session = Depends(get_session)
) -> ScenePlanOut:
    require_shot(session, shot_id)
    plan = require_plan(session, shot_id, revision)
    if plan.status == "superseded":
        return plan_out(plan)
    if plan.status != "approved":
        raise HTTPException(
            status_code=409, detail="only an approved scene plan can be superseded"
        )
    plan.status = "superseded"
    try:
        session.commit()
    except DBAPIError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="database rejected the scene plan transition"
        ) from error
    session.refresh(plan)
    return plan_out(plan)


def _asset_size(asset: ReferenceAsset, store: BlobStore) -> tuple[int, int]:
    if asset.width and asset.height:
        return asset.width, asset.height
    try:
        info = probe_image_bytes(store.read_bytes(asset.storage_key))
    except (StorageError, FileNotFoundError, OSError, ImageProbeError) as error:
        raise HTTPException(
            status_code=409, detail="reference content is unavailable"
        ) from error
    return info.width, info.height


def _layout_layers(
    session: Session,
    plan: VisualScenePlan,
    store: BlobStore,
    settings: Settings,
) -> list[ShotCompositionLayer]:
    """Детерминированная раскладка: локация → персонажи → предметы."""

    payload = plan.plan
    width = int(payload["canvas"]["width"])
    height = int(payload["canvas"]["height"])
    if width * height > settings.composition_max_pixels:
        raise HTTPException(
            status_code=413,
            detail=f"composition exceeds {settings.composition_max_pixels} pixels",
        )

    assets: dict[uuid.UUID, ReferenceAsset] = {}
    for item in payload["references"]:
        asset = session.get(ReferenceAsset, uuid.UUID(str(item["asset_id"])))
        if asset is None:
            raise HTTPException(status_code=409, detail="plan reference is missing")
        assets[asset.id] = asset

    by_role: dict[str, list[dict[str, Any]]] = {
        "location": [],
        "character": [],
        "prop": [],
    }
    for item in payload["references"]:
        by_role.get(item["role"], []).append(item)

    layers: list[ShotCompositionLayer] = []
    z_index = 0

    for item in by_role["location"]:
        asset = assets[uuid.UUID(str(item["asset_id"]))]
        asset_width, asset_height = _asset_size(asset, store)
        scale = max(width / asset_width, height / asset_height)
        layers.append(
            _layer(
                plan,
                asset,
                z_index,
                x=(width - asset_width * scale) / 2,
                y=(height - asset_height * scale) / 2,
                scale=scale,
            )
        )
        z_index += 1

    character_x = (0.10, 0.55, 0.30)
    for index, item in enumerate(by_role["character"]):
        asset = assets[uuid.UUID(str(item["asset_id"]))]
        asset_width, asset_height = _asset_size(asset, store)
        scale = 0.55 * height / asset_height
        layers.append(
            _layer(
                plan,
                asset,
                z_index,
                x=width * character_x[min(index, len(character_x) - 1)],
                y=height - asset_height * scale,
                scale=scale,
            )
        )
        z_index += 1

    for item in by_role["prop"]:
        asset = assets[uuid.UUID(str(item["asset_id"]))]
        asset_width, asset_height = _asset_size(asset, store)
        scale = 0.25 * width / asset_width
        layers.append(
            _layer(
                plan,
                asset,
                z_index,
                x=width - asset_width * scale - 0.05 * width,
                y=height - asset_height * scale - 0.05 * height,
                scale=scale,
            )
        )
        z_index += 1

    if len(layers) > settings.composition_max_layers:
        raise HTTPException(
            status_code=413,
            detail=f"composition exceeds {settings.composition_max_layers} layers",
        )
    return layers


def _layer(
    plan: VisualScenePlan,
    asset: ReferenceAsset,
    z_index: int,
    *,
    x: float,
    y: float,
    scale: float,
) -> ShotCompositionLayer:
    return ShotCompositionLayer(
        project_id=plan.project_id,
        reference_asset_id=asset.id,
        z_index=z_index,
        x=round(x, 4),
        y=round(y, 4),
        scale=round(scale, 4),
        rotation=0,
        opacity=1,
    )


@router.post(
    "/{revision}/composition",
    response_model=CompositionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_composition_from_plan(
    shot_id: uuid.UUID,
    revision: int,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> CompositionOut:
    shot = require_shot(session, shot_id)
    plan = require_plan(session, shot_id, revision)
    if plan.status != "approved":
        raise HTTPException(
            status_code=409, detail="approve the scene plan before creating a composition"
        )
    project_id = shot_project_id(session, shot)
    layers = _layout_layers(session, plan, store, settings)
    if not layers:
        raise HTTPException(
            status_code=409, detail="scene plan has no layers to compose"
        )

    composition_revision = (
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
        revision=composition_revision,
        width=int(plan.plan["canvas"]["width"]),
        height=int(plan.plan["canvas"]["height"]),
        status="draft",
        source_plan_id=plan.id,
    )
    session.add(composition)
    session.flush()
    for layer in layers:
        layer.composition_id = composition.id
        session.add(layer)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="composition revision already exists"
        ) from error
    session.refresh(composition)
    return composition_out(session, composition)
