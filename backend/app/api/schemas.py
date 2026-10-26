from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models import CharacterBibleVersion, ReferenceAsset

ReferenceView = Literal["front", "side", "three_quarter", "back", "other"]
ReferencePose = Literal["stand", "sit", "walk", "lie", "sleep", "custom"]


class ReferenceMetaUpdate(BaseModel):
    """Ручная разметка неутверждённого референса (front-референс и т.п.)."""

    view: ReferenceView | None = None
    pose: ReferencePose | None = None
    expression: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=64)



class ProjectOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str


class BibleVersionSummary(BaseModel):
    version: int
    status: str
    source: str
    sha256: str
    created_at: datetime
    approved_at: datetime | None

    @classmethod
    def from_version(cls, version: CharacterBibleVersion) -> "BibleVersionSummary":
        return cls(
            version=version.version,
            status=version.status,
            source=version.source,
            sha256=version.sha256,
            created_at=version.created_at,
            approved_at=version.approved_at,
        )


class BibleVersionOut(BibleVersionSummary):
    body: str

    @classmethod
    def from_version(cls, version: CharacterBibleVersion) -> "BibleVersionOut":
        return cls(
            version=version.version,
            status=version.status,
            source=version.source,
            sha256=version.sha256,
            created_at=version.created_at,
            approved_at=version.approved_at,
            body=version.body,
        )


class ReferenceOut(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    role: str | None
    character_id: uuid.UUID | None
    location_id: uuid.UUID | None
    prop_id: uuid.UUID | None
    view: str | None
    pose: str | None
    expression: str | None
    width: int | None
    height: int | None
    mime_type: str | None
    sha256: str
    has_alpha: bool | None
    approved_at: datetime | None
    created_at: datetime
    content_url: str

    @classmethod
    def from_asset(cls, asset: ReferenceAsset) -> "ReferenceOut":
        raw_alpha = (asset.metadata_json or {}).get("has_alpha")
        return cls(
            id=asset.id,
            kind=asset.kind,
            status=asset.status,
            role=asset.role,
            character_id=asset.character_id,
            location_id=asset.location_id,
            prop_id=asset.prop_id,
            view=asset.view,
            pose=asset.pose,
            expression=asset.expression,
            width=asset.width,
            height=asset.height,
            mime_type=asset.mime_type,
            sha256=asset.sha256,
            has_alpha=raw_alpha if isinstance(raw_alpha, bool) else None,
            approved_at=asset.approved_at,
            created_at=asset.created_at,
            content_url=f"/api/reference-assets/{asset.id}/content",
        )


class CharacterSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: str
    status: str
    description: str | None
    reference_count: int
    approved_reference_count: int
    bible_version_count: int
    latest_bible_version: int | None
    latest_bible_status: str | None


class CharacterDetail(CharacterSummary):
    bible_versions: list[BibleVersionSummary]


class LocationSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    status: str
    reference_count: int


class LocationDetail(LocationSummary):
    references: list[ReferenceOut]


class PropSummary(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    status: str
    reference_count: int


class PropDetail(PropSummary):
    references: list[ReferenceOut]
