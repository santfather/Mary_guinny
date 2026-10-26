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
    # FK на shot_compositions появится в WP-02 вместе с самой таблицей.
    shot_composition_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
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
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # metadata — зарезервированное имя в SQLAlchemy Declarative, колонка остаётся "metadata".
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
