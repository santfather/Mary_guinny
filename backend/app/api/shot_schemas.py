from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.api.schemas import ReferenceOut
from app.models import (
    RenderAttempt,
    Scene,
    Shot,
    ShotComposition,
    ShotCompositionLayer,
    ShotReference,
)

ShotReferencePurpose = Literal["character", "location", "prop", "style", "other"]


def _fps(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


class ShotSummary(BaseModel):
    id: uuid.UUID
    scene_id: uuid.UUID
    project_id: uuid.UUID
    sequence_no: int
    status: str
    target_duration_frames: int | None
    timeline_fps: float | None
    start_keyframe_artifact_id: uuid.UUID | None
    start_keyframe_attempt_id: uuid.UUID | None
    start_keyframe_content_url: str | None

    @classmethod
    def from_shot(cls, shot: Shot, project_id: uuid.UUID) -> "ShotSummary":
        keyframe_id = shot.start_keyframe_artifact_id
        return cls(
            id=shot.id,
            scene_id=shot.scene_id,
            project_id=project_id,
            sequence_no=shot.sequence_no,
            status=shot.status,
            target_duration_frames=shot.target_duration_frames,
            timeline_fps=_fps(shot.timeline_fps),
            start_keyframe_artifact_id=keyframe_id,
            start_keyframe_attempt_id=shot.start_keyframe_attempt_id,
            start_keyframe_content_url=(
                f"/api/artifacts/{keyframe_id}/content" if keyframe_id is not None else None
            ),
        )


class SceneOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    episode_id: uuid.UUID | None
    sequence_no: int
    title: str | None
    shots: list[ShotSummary]

    @classmethod
    def from_scene(cls, scene: Scene, shots: list[ShotSummary]) -> "SceneOut":
        return cls(
            id=scene.id,
            project_id=scene.project_id,
            episode_id=scene.episode_id,
            sequence_no=scene.sequence_no,
            title=scene.title,
            shots=shots,
        )


class SceneCreate(BaseModel):
    sequence_no: int | None = Field(default=None, ge=1)
    title: str | None = None
    episode_id: uuid.UUID | None = None


class ShotCreate(BaseModel):
    sequence_no: int | None = Field(default=None, ge=1)
    target_duration_frames: int | None = Field(default=None, ge=1)
    timeline_fps: float | None = Field(default=None, gt=0)


class ShotReferenceCreate(BaseModel):
    reference_asset_id: uuid.UUID
    purpose: ShotReferencePurpose


class ShotReferenceOut(BaseModel):
    id: uuid.UUID
    purpose: str
    reference: ReferenceOut

    @classmethod
    def from_link(cls, link: ShotReference, reference: ReferenceOut) -> "ShotReferenceOut":
        return cls(id=link.id, purpose=link.purpose, reference=reference)


class CompositionLayerIn(BaseModel):
    reference_asset_id: uuid.UUID
    z_index: int = Field(ge=0)
    x: float = 0
    y: float = 0
    scale: float = Field(default=1, gt=0)
    rotation: float = 0
    opacity: float = Field(default=1, ge=0, le=1)


class CompositionWrite(BaseModel):
    width: int = Field(gt=0, le=16384)
    height: int = Field(gt=0, le=16384)
    layers: list[CompositionLayerIn] = Field(min_length=1)


class CompositionLayerOut(BaseModel):
    z_index: int
    x: float
    y: float
    scale: float
    rotation: float
    opacity: float
    reference: ReferenceOut

    @classmethod
    def from_layer(
        cls, layer: ShotCompositionLayer, reference: ReferenceOut
    ) -> "CompositionLayerOut":
        return cls(
            z_index=layer.z_index,
            x=float(layer.x),
            y=float(layer.y),
            scale=float(layer.scale),
            rotation=float(layer.rotation),
            opacity=float(layer.opacity),
            reference=reference,
        )


class CompositionSummary(BaseModel):
    revision: int
    width: int
    height: int
    status: str
    layer_count: int
    preview_artifact_id: uuid.UUID | None
    preview_content_url: str | None
    source_plan_id: uuid.UUID | None
    # True, если непрозрачный персонаж перекрывает фон: это layout mockup.
    layout_mockup: bool = False
    created_at: datetime
    approved_at: datetime | None

    @classmethod
    def from_composition(
        cls,
        composition: ShotComposition,
        layer_count: int,
        *,
        layout_mockup: bool = False,
    ) -> "CompositionSummary":
        preview_id = composition.preview_artifact_id
        return cls(
            revision=composition.revision,
            width=composition.width,
            height=composition.height,
            status=composition.status,
            layer_count=layer_count,
            preview_artifact_id=preview_id,
            preview_content_url=(
                f"/api/artifacts/{preview_id}/content" if preview_id is not None else None
            ),
            source_plan_id=composition.source_plan_id,
            layout_mockup=layout_mockup,
            created_at=composition.created_at,
            approved_at=composition.approved_at,
        )


class CompositionOut(CompositionSummary):
    layers: list[CompositionLayerOut]


class CompositionWarningOut(BaseModel):
    code: str
    message: str
    z_index: int
    reference_asset_id: uuid.UUID


class CompositionRenderOut(BaseModel):
    artifact_id: uuid.UUID
    content_url: str
    width: int
    height: int
    preview_artifact_id: uuid.UUID | None
    warnings: list[CompositionWarningOut]
    is_layout_mockup: bool = False


class KeyframeCreate(BaseModel):
    composition_revision: int | None = Field(default=None, ge=1)


class KeyframeOut(BaseModel):
    attempt_id: uuid.UUID
    artifact_id: uuid.UUID
    artifact_content_url: str
    composition_revision: int
    status: str


class AttemptOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    job_id: uuid.UUID | None
    created_at: datetime
    artifact_id: uuid.UUID | None
    artifact_content_url: str | None
    composition_revision: int | None
    visual_plan_revision: int | None

    @classmethod
    def from_attempt(
        cls, attempt: RenderAttempt, artifact_id: uuid.UUID | None
    ) -> "AttemptOut":
        revision: int | None = None
        plan_revision: int | None = None
        parameters = attempt.parameters
        if isinstance(parameters, dict):
            raw = parameters.get("composition_revision")
            if isinstance(raw, int):
                revision = raw
            raw_plan = parameters.get("visual_plan_revision")
            if isinstance(raw_plan, int):
                plan_revision = raw_plan
        return cls(
            id=attempt.id,
            kind=attempt.kind,
            status=attempt.status,
            job_id=attempt.job_id,
            created_at=attempt.created_at,
            artifact_id=artifact_id,
            artifact_content_url=(
                f"/api/artifacts/{artifact_id}/content" if artifact_id is not None else None
            ),
            composition_revision=revision,
            visual_plan_revision=plan_revision,
        )


class ShotDetail(ShotSummary):
    references: list[ShotReferenceOut]
    composition_revisions: list[CompositionSummary]
    attempts: list[AttemptOut]


class RenderQueuedOut(BaseModel):
    job_id: uuid.UUID
    status: str
    shot_id: uuid.UUID
    start_keyframe_artifact_id: uuid.UUID
