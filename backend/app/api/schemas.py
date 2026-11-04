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
    # WP-M6: многоракурсная карточка не может быть стартовым кадром (живёт в metadata).
    multi_view: bool | None = None



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
    # WP-M6: длительность голосового образца и пометка многоракурсной карточки.
    duration_s: float | None
    multi_view: bool
    approved_at: datetime | None
    created_at: datetime
    content_url: str

    @classmethod
    def from_asset(cls, asset: ReferenceAsset) -> "ReferenceOut":
        metadata = asset.metadata_json or {}
        raw_alpha = metadata.get("has_alpha")
        raw_duration = metadata.get("duration_s")
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
            duration_s=(
                float(raw_duration)
                if isinstance(raw_duration, (int, float)) and not isinstance(raw_duration, bool)
                else None
            ),
            multi_view=metadata.get("multi_view") is True,
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


class LibraryEntitySummary(BaseModel):
    """Карточка локации или предмета; обе сущности имеют одинаковый набор полей."""

    id: uuid.UUID
    project_id: uuid.UUID
    slug: str
    name: str
    description: str | None
    status: str
    reference_count: int


class LibraryEntityDetail(LibraryEntitySummary):
    references: list[ReferenceOut]


class LibraryEntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class LibraryEntityUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
