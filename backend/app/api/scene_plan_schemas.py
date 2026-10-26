"""Pydantic-схемы Visual Scene Plan (WP-05A)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ReferenceRole = Literal["character", "location", "prop", "style", "storyboard"]
CameraFraming = Literal["wide", "medium", "close_up", "other"]
CameraMovement = Literal["static", "pan", "tilt", "dolly", "zoom", "handheld", "other"]
LayoutExportMode = Literal["crop", "pad"]

_ALIAS_PATTERN = r"^[a-z][a-z0-9_]{1,31}$"


class PlanReferenceIn(BaseModel):
    asset_id: uuid.UUID
    role: ReferenceRole
    entity_id: uuid.UUID | None = None
    alias: str = Field(pattern=_ALIAS_PATTERN)


class PlanCanvas(BaseModel):
    width: int = Field(default=768, gt=0, le=16384)
    height: int = Field(default=512, gt=0, le=16384)


class PlanCamera(BaseModel):
    framing: CameraFraming = "wide"
    movement: CameraMovement = "static"


class PlanInitialState(BaseModel):
    subject: str
    position: str = ""
    action: str = ""


class PlanActionBeat(BaseModel):
    order: int = Field(ge=1)
    subject: str
    action: str = ""
    target: str | None = None


class PlanConstraints(BaseModel):
    preserve_character_identity: bool = True
    preserve_location_layout: bool = True
    no_unreferenced_characters: bool = True


class ScenePlanWrite(BaseModel):
    """Полный план ревизии; schema_version проставляет сервер."""

    canvas: PlanCanvas = Field(default_factory=PlanCanvas)
    references: list[PlanReferenceIn] = Field(min_length=1)
    camera: PlanCamera = Field(default_factory=PlanCamera)
    initial_state: list[PlanInitialState] = Field(default_factory=list)
    action_beats: list[PlanActionBeat] = Field(default_factory=list)
    constraints: PlanConstraints = Field(default_factory=PlanConstraints)
    motion_prompt: str = Field(min_length=1, max_length=4000)
    needs_review: bool = False

    def to_plan(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        return {"schema_version": 1, **payload}


class ScenePlanWarningOut(BaseModel):
    code: str
    message: str


class ScenePlanOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    shot_id: uuid.UUID
    revision: int
    schema_version: int
    status: str
    source: str
    plan: ScenePlanWrite
    warnings: list[ScenePlanWarningOut]
    created_at: datetime
    approved_at: datetime | None


class ScenePlanCreate(BaseModel):
    plan: ScenePlanWrite
    source: Literal["manual", "llm", "fallback"] = "manual"
    warnings: list[ScenePlanWarningOut] = Field(default_factory=list)


class ScenePlanGenerateRequest(BaseModel):
    action: str = Field(default="", max_length=2000)
    references: list[PlanReferenceIn] = Field(min_length=1)
    camera: PlanCamera = Field(default_factory=PlanCamera)
    canvas: PlanCanvas = Field(default_factory=PlanCanvas)
    use_vision: bool = True


class ScenePlanCandidate(BaseModel):
    plan: ScenePlanWrite
    warnings: list[ScenePlanWarningOut]
    source: str


class LayoutExportRequest(BaseModel):
    size: int = Field(default=512, ge=64, le=4096)
    mode: LayoutExportMode = "crop"


class LayoutExportOut(BaseModel):
    artifact_id: uuid.UUID
    content_url: str
    size: int
    mode: str
    source_composition_revision: int
    source_artifact_id: uuid.UUID
    is_layout_mockup: bool
