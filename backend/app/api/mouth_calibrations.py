"""Калибровка области рта для `mouth_animation_mvp` (WP-VOICE-02, §4.18).

Калибровка хранится отдельно и не меняет approved-референс или артефакт
стартового кадра. Одна запись на пару (шот, источник), запись изменяемая.
Предпросмотр закрытого/открытого рта — PNG без записи в БД.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_store
from app.api.mouth_sources import (
    region_from_calibration,
    require_calibration_source,
    resolve_source_image,
)
from app.api.shots import require_shot, shot_project_id
from app.models import MouthCalibration, Shot
from app.mouth_animation import (
    MouthAnimationError,
    MouthRegion,
    decode_source_image,
    render_frame,
)
from app.storage import BlobStore

router = APIRouter(prefix="/api", tags=["mouth-calibrations"])


class MouthCalibrationIn(BaseModel):
    """Ровно один источник: approved-референс или стартовый кадр шота."""

    reference_asset_id: uuid.UUID | None = None
    keyframe_artifact_id: uuid.UUID | None = None
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)
    rotation: float = Field(default=0, ge=-180, le=180)
    max_open: float = Field(default=0.8, gt=0, le=1)
    sensitivity: float = Field(default=1.0, gt=0, le=5)
    smoothing: float = Field(default=0.5, ge=0, lt=1)

    @model_validator(mode="after")
    def _validate(self) -> "MouthCalibrationIn":
        if (self.reference_asset_id is None) == (self.keyframe_artifact_id is None):
            raise ValueError(
                "specify exactly one of reference_asset_id / keyframe_artifact_id"
            )
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("mouth region is out of bounds")
        return self

    def as_region(self) -> MouthRegion:
        return MouthRegion(
            x=self.x,
            y=self.y,
            width=self.width,
            height=self.height,
            rotation=self.rotation,
            max_open=self.max_open,
            sensitivity=self.sensitivity,
            smoothing=self.smoothing,
        )


class MouthCalibrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    shot_id: uuid.UUID
    reference_asset_id: uuid.UUID | None
    keyframe_artifact_id: uuid.UUID | None
    x: float
    y: float
    width: float
    height: float
    rotation: float
    max_open: float
    sensitivity: float
    smoothing: float
    created_at: datetime
    updated_at: datetime


def _existing(
    session: Session, shot_id: uuid.UUID, payload: MouthCalibrationIn
) -> MouthCalibration | None:
    statement = select(MouthCalibration).where(MouthCalibration.shot_id == shot_id)
    if payload.reference_asset_id is not None:
        statement = statement.where(
            MouthCalibration.reference_asset_id == payload.reference_asset_id
        )
    else:
        statement = statement.where(
            MouthCalibration.keyframe_artifact_id == payload.keyframe_artifact_id
        )
    return session.scalar(statement)


def _apply(row: MouthCalibration, payload: MouthCalibrationIn) -> None:
    row.x = payload.x
    row.y = payload.y
    row.width = payload.width
    row.height = payload.height
    row.rotation = payload.rotation
    row.max_open = payload.max_open
    row.sensitivity = payload.sensitivity
    row.smoothing = payload.smoothing


@router.post(
    "/shots/{shot_id}/mouth-calibrations",
    response_model=MouthCalibrationOut,
    status_code=status.HTTP_201_CREATED,
)
def save_mouth_calibration(
    shot_id: uuid.UUID,
    payload: MouthCalibrationIn,
    response: Response,
    session: Session = Depends(get_session),
) -> MouthCalibrationOut:
    """Upsert по источнику: повторное сохранение обновляет ту же калибровку."""

    shot = require_shot(session, shot_id)
    project_id = shot_project_id(session, shot)
    require_calibration_source(
        session, shot, payload.reference_asset_id, payload.keyframe_artifact_id
    )

    existing = _existing(session, shot.id, payload)
    if existing is not None:
        _apply(existing, payload)
        session.commit()
        session.refresh(existing)
        response.status_code = status.HTTP_200_OK
        return MouthCalibrationOut.model_validate(existing)

    row = MouthCalibration(
        project_id=project_id,
        shot_id=shot.id,
        reference_asset_id=payload.reference_asset_id,
        keyframe_artifact_id=payload.keyframe_artifact_id,
        x=payload.x,
        y=payload.y,
        width=payload.width,
        height=payload.height,
        rotation=payload.rotation,
        max_open=payload.max_open,
        sensitivity=payload.sensitivity,
        smoothing=payload.smoothing,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail={"error": "calibration_conflict"}
        ) from error
    session.refresh(row)
    return MouthCalibrationOut.model_validate(row)


@router.get(
    "/shots/{shot_id}/mouth-calibrations",
    response_model=list[MouthCalibrationOut],
)
def list_mouth_calibrations(
    shot_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[MouthCalibrationOut]:
    require_shot(session, shot_id)
    rows = session.scalars(
        select(MouthCalibration)
        .where(MouthCalibration.shot_id == shot_id)
        .order_by(MouthCalibration.updated_at.desc(), MouthCalibration.id)
    )
    return [MouthCalibrationOut.model_validate(row) for row in rows]


@router.post(
    "/shots/{shot_id}/mouth-calibrations/preview",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
def preview_mouth(
    shot_id: uuid.UUID,
    payload: MouthCalibrationIn,
    state: Literal["closed", "open"] = Query(default="closed"),
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
) -> Response:
    """PNG исходного кадра с закрытым или максимально открытым ртом."""

    shot: Shot = require_shot(session, shot_id)
    require_calibration_source(
        session, shot, payload.reference_asset_id, payload.keyframe_artifact_id
    )
    source = resolve_source_image(
        session,
        shot,
        payload.reference_asset_id,
        store=store,
        keyframe_artifact_id=payload.keyframe_artifact_id,
    )
    region = payload.as_region()
    try:
        region.validate()
    except MouthAnimationError as error:
        raise HTTPException(
            status_code=409,
            detail={"error": error.code, "message": error.message},
        ) from error

    base = decode_source_image(source.read(store))
    openness = 0.0 if state == "closed" else region.max_open
    frame = render_frame(base, region, openness)
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG")
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


def calibration_region(row: MouthCalibration) -> MouthRegion:
    return region_from_calibration(row)
