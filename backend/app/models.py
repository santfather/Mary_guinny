from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

PROJECT_STATUSES = ("draft", "active", "archived")
EPISODE_STATUSES = ("draft", "active", "archived")
SHOT_STATUSES = (
    "draft",
    "prompt_ready",
    "keyframe_ready",
    "queued",
    "generating",
    "review",
    "approved",
    "changes_requested",
)
PROMPT_TYPES = ("keyframe", "motion", "composition", "script", "other")
JOB_STATUSES = (
    "pending",
    "leased",
    "running",
    "completed",
    "failed",
    "cancel_requested",
    "cancelled",
    "retry_wait",
    "lease_expired",
)
ATTEMPT_KINDS = ("keyframe", "video", "postprocess")
ATTEMPT_STATUSES = ("pending", "running", "completed", "failed", "cancelled")
ARTIFACT_SOURCES = ("attempt", "composition", "upload", "import")
REFERENCE_ASSET_KINDS = (
    "character_reference",
    "location_reference",
    "prop_reference",
    "uploaded",
)
CHARACTER_KINDS = ("cat", "human", "other")
LIBRARY_STATUSES = ("draft", "active", "archived")
BIBLE_STATUSES = ("draft", "approved", "superseded")
BIBLE_SOURCES = ("manual", "import")
REFERENCE_ASSET_STATUSES = ("draft", "approved", "rejected", "superseded")
REFERENCE_VIEWS = ("front", "side", "three_quarter", "back", "other")
REFERENCE_POSES = ("stand", "sit", "walk", "lie", "sleep", "custom")
SHOT_REFERENCE_PURPOSES = ("character", "location", "prop", "style", "other")
COMPOSITION_STATUSES = ("draft", "approved", "superseded")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(_in_list("status", PROJECT_STATUSES), name="ck_projects_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    bible_version: Mapped[str | None] = mapped_column(Text)


class Episode(TimestampMixin, Base):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("project_id", "sequence_no", name="uq_episodes_project_sequence"),
        CheckConstraint(_in_list("status", EPISODE_STATUSES), name="ck_episodes_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    # S11: nullable на переходный период, обязательным станет после backfill в WP-03.
    episode_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("episodes.id")
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    audio_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("artifacts.id", name="fk_scenes_audio_artifact")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Shot(TimestampMixin, Base):
    __tablename__ = "shots"
    __table_args__ = (
        UniqueConstraint("scene_id", "sequence_no", name="uq_shots_scene_sequence"),
        CheckConstraint(_in_list("status", SHOT_STATUSES), name="ck_shots_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenes.id"), nullable=False
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    target_duration_frames: Mapped[int | None] = mapped_column(Integer)
    timeline_fps: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    current_prompt_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompt_revisions.id", name="fk_shots_current_prompt_revision"),
    )
    continuity_from_shot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shots.id")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    approved_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("render_attempts.id", name="fk_shots_approved_attempt"),
    )
    # S9: единственный источник истины стартового кадра (пишет promote-keyframe).
    start_keyframe_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", name="fk_shots_start_keyframe_artifact"),
    )
    start_keyframe_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("render_attempts.id", name="fk_shots_start_keyframe_attempt"),
    )


class PromptRevision(Base):
    __tablename__ = "prompt_revisions"
    __table_args__ = (
        UniqueConstraint(
            "shot_id", "prompt_type", "version", name="uq_prompt_revisions_shot_type_version"
        ),
        CheckConstraint(_in_list("prompt_type", PROMPT_TYPES), name="ck_prompt_revisions_type"),
        CheckConstraint("version >= 1", name="ck_prompt_revisions_version_positive"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    shot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shots.id"), nullable=False
    )
    prompt_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="motion")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(Text)
    parameters_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in_list("status", JOB_STATUSES), name="ck_jobs_status"),
        CheckConstraint(
            "(scene_id IS NOT NULL)::int + (shot_id IS NOT NULL)::int = 1",
            name="ck_jobs_single_target",
        ),
        CheckConstraint("attempts >= 0", name="ck_jobs_attempts_non_negative"),
        CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts_positive"),
        Index(
            "one_active_render_per_shot",
            "shot_id",
            unique=True,
            postgresql_where=text(
                "kind = 'render_video' AND status IN "
                "('pending','leased','running','retry_wait','cancel_requested','lease_expired')"
            ),
        ),
        Index(
            "uq_jobs_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_jobs_status", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    scene_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenes.id")
    )
    shot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shots.id")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)


class JobDependency(Base):
    __tablename__ = "job_dependencies"
    __table_args__ = (
        CheckConstraint("job_id <> depends_on_job_id", name="ck_job_dependencies_no_self"),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )
    depends_on_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        primary_key=True,
    )


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    comfy_version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")


class RenderAttempt(Base):
    __tablename__ = "render_attempts"
    __table_args__ = (
        CheckConstraint(_in_list("kind", ATTEMPT_KINDS), name="ck_render_attempts_kind"),
        CheckConstraint(_in_list("status", ATTEMPT_STATUSES), name="ck_render_attempts_status"),
        # S12: job_id nullable только для синхронной keyframe-попытки.
        CheckConstraint(
            "job_id IS NOT NULL OR kind = 'keyframe'",
            name="ck_render_attempts_job_required",
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    shot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shots.id"), nullable=False
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id")
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("prompt_revisions.id")
    )
    input_artifact_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    workflow_version: Mapped[str | None] = mapped_column(Text)
    model_hash: Mapped[str | None] = mapped_column(Text)
    seed: Mapped[int | None] = mapped_column(BigInteger)
    native_fps: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    parameters: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workers.id")
    )
    duration_s: Mapped[Decimal | None] = mapped_column(Numeric(10, 3))
    peak_mem_mb: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(_in_list("source", ARTIFACT_SOURCES), name="ck_artifacts_source"),
        # S12, инвариант 1: ровно один источник.
        CheckConstraint(
            "(attempt_id IS NOT NULL)::int"
            " + (shot_composition_id IS NOT NULL)::int"
            " + (source IN ('upload', 'import'))::int = 1",
            name="ck_artifacts_single_source",
        ),
        # S12, инвариант 2: source соответствует заполненной связи.
        CheckConstraint(
            "(source = 'attempt' AND attempt_id IS NOT NULL)"
            " OR (source = 'composition' AND shot_composition_id IS NOT NULL)"
            " OR (source IN ('upload', 'import')"
            "     AND attempt_id IS NULL AND shot_composition_id IS NULL)",
            name="ck_artifacts_source_matches_link",
        ),
        CheckConstraint("bytes >= 0", name="ck_artifacts_bytes_non_negative"),
        Index("ix_artifacts_sha256", "sha256"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("render_attempts.id")
    )
    # S12: ссылка на ревизию композиции; FK добавлен в WP-02 (0004).
    shot_composition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shot_compositions.id", name="fk_artifacts_shot_composition"),
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReferenceAsset(Base):
    __tablename__ = "reference_assets"
    __table_args__ = (
        CheckConstraint(
            _in_list("kind", REFERENCE_ASSET_KINDS), name="ck_reference_assets_kind"
        ),
        CheckConstraint(
            _in_list("status", REFERENCE_ASSET_STATUSES), name="ck_reference_assets_status"
        ),
        # S1: владелец строго соответствует kind; у uploaded владельца-сущности нет.
        CheckConstraint(
            "(kind = 'character_reference' AND character_id IS NOT NULL"
            " AND location_id IS NULL AND prop_id IS NULL)"
            " OR (kind = 'location_reference' AND location_id IS NOT NULL"
            " AND character_id IS NULL AND prop_id IS NULL)"
            " OR (kind = 'prop_reference' AND prop_id IS NOT NULL"
            " AND character_id IS NULL AND location_id IS NULL)"
            " OR (kind = 'uploaded' AND character_id IS NULL"
            " AND location_id IS NULL AND prop_id IS NULL)",
            name="ck_reference_assets_owner_matches_kind",
        ),
        CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL",
            name="ck_reference_assets_approved_at",
        ),
        CheckConstraint(
            "view IS NULL OR view IN ('front', 'side', 'three_quarter', 'back', 'other')",
            name="ck_reference_assets_view",
        ),
        CheckConstraint(
            "pose IS NULL OR pose IN ('stand', 'sit', 'walk', 'lie', 'sleep', 'custom')",
            name="ck_reference_assets_pose",
        ),
        CheckConstraint("width IS NULL OR width > 0", name="ck_reference_assets_width_positive"),
        CheckConstraint(
            "height IS NULL OR height > 0", name="ck_reference_assets_height_positive"
        ),
        UniqueConstraint("project_id", "id", name="uq_reference_assets_project_id"),
        UniqueConstraint("project_id", "sha256", name="uq_reference_assets_project_sha256"),
        # S1/§3.2: владелец обязан принадлежать тому же проекту.
        ForeignKeyConstraint(
            ["project_id", "character_id"],
            ["characters.project_id", "characters.id"],
            name="fk_reference_assets_character_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "location_id"],
            ["locations.project_id", "locations.id"],
            name="fk_reference_assets_location_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "prop_id"],
            ["props.project_id", "props.id"],
            name="fk_reference_assets_prop_project",
        ),
        Index("ix_reference_assets_character_id", "character_id"),
        Index("ix_reference_assets_location_id", "location_id"),
        Index("ix_reference_assets_prop_id", "prop_id"),
        Index("ix_reference_assets_project_status", "project_id", "status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    character_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    prop_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    role: Mapped[str | None] = mapped_column(Text)
    view: Mapped[str | None] = mapped_column(Text)
    pose: Mapped[str | None] = mapped_column(Text)
    expression: Mapped[str | None] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    mime_type: Mapped[str | None] = mapped_column(Text)
    # metadata — зарезервированное имя в SQLAlchemy Declarative, колонка остаётся "metadata".
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Character(TimestampMixin, Base):
    __tablename__ = "characters"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_characters_project_slug"),
        UniqueConstraint("project_id", "id", name="uq_characters_project_id"),
        CheckConstraint(_in_list("kind", CHARACTER_KINDS), name="ck_characters_kind"),
        CheckConstraint(_in_list("status", LIBRARY_STATUSES), name="ck_characters_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="other")
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")


class CharacterBibleVersion(Base):
    __tablename__ = "character_bible_versions"
    __table_args__ = (
        UniqueConstraint("character_id", "version", name="uq_bible_character_version"),
        ForeignKeyConstraint(
            ["project_id", "character_id"],
            ["characters.project_id", "characters.id"],
            name="fk_bible_character_project",
        ),
        CheckConstraint("version >= 1", name="ck_bible_version_positive"),
        CheckConstraint(_in_list("status", BIBLE_STATUSES), name="ck_bible_status"),
        CheckConstraint(_in_list("source", BIBLE_SOURCES), name="ck_bible_source"),
        CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL", name="ck_bible_approved_at"
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    character_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Location(TimestampMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_locations_project_slug"),
        UniqueConstraint("project_id", "id", name="uq_locations_project_id"),
        CheckConstraint(_in_list("status", LIBRARY_STATUSES), name="ck_locations_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")


class Prop(TimestampMixin, Base):
    __tablename__ = "props"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_props_project_slug"),
        UniqueConstraint("project_id", "id", name="uq_props_project_id"),
        CheckConstraint(_in_list("status", LIBRARY_STATUSES), name="ck_props_status"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")


class ShotReference(Base):
    __tablename__ = "shot_references"
    __table_args__ = (
        UniqueConstraint(
            "shot_id", "reference_asset_id", "purpose", name="uq_shot_references_shot_asset_purpose"
        ),
        ForeignKeyConstraint(
            ["project_id", "reference_asset_id"],
            ["reference_assets.project_id", "reference_assets.id"],
            name="fk_shot_references_asset_project",
        ),
        CheckConstraint(_in_list("purpose", SHOT_REFERENCE_PURPOSES), name="ck_shot_references_purpose"),
        Index("ix_shot_references_reference_asset_id", "reference_asset_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    shot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shots.id"), nullable=False
    )
    reference_asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ShotComposition(Base):
    __tablename__ = "shot_compositions"
    __table_args__ = (
        UniqueConstraint("shot_id", "revision", name="uq_shot_compositions_shot_revision"),
        CheckConstraint("revision >= 1", name="ck_shot_compositions_revision_positive"),
        CheckConstraint(_in_list("status", COMPOSITION_STATUSES), name="ck_shot_compositions_status"),
        CheckConstraint("width > 0", name="ck_shot_compositions_width_positive"),
        CheckConstraint("height > 0", name="ck_shot_compositions_height_positive"),
        CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL",
            name="ck_shot_compositions_approved_at",
        ),
        Index("ix_shot_compositions_preview_artifact_id", "preview_artifact_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    shot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shots.id"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    preview_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", name="fk_shot_compositions_preview_artifact"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShotCompositionLayer(Base):
    __tablename__ = "shot_composition_layers"
    __table_args__ = (
        UniqueConstraint("composition_id", "z_index", name="uq_composition_layers_z_index"),
        ForeignKeyConstraint(
            ["project_id", "reference_asset_id"],
            ["reference_assets.project_id", "reference_assets.id"],
            name="fk_composition_layers_asset_project",
        ),
        CheckConstraint("z_index >= 0", name="ck_composition_layers_z_index_non_negative"),
        CheckConstraint("scale > 0", name="ck_composition_layers_scale_positive"),
        CheckConstraint(
            "opacity >= 0 AND opacity <= 1", name="ck_composition_layers_opacity_range"
        ),
        Index("ix_composition_layers_reference_asset_id", "reference_asset_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    composition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shot_compositions.id"), nullable=False
    )
    reference_asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    z_index: Mapped[int] = mapped_column(Integer, nullable=False)
    x: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default="0")
    y: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default="0")
    scale: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default="1")
    rotation: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, server_default="0")
    opacity: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, server_default="1")
