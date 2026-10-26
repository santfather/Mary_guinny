"""initial core schema

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-10-26

Базовые таблицы §4.1 v1.3 с учётом S10 (`prompt_revisions.prompt_type/version`),
S11 (`episodes`, nullable `scenes.episode_id`) и S12 (nullable-связи артефактов).

Циклические FK (`scenes -> artifacts`, `shots -> prompt_revisions`,
`shots -> render_attempts`) добавляются отдельными `create_foreign_key`
после создания всех таблиц.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_core"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade() -> None:
    op.create_table(
        "projects",
        _uuid_pk(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("bible_version", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')", name="ck_projects_status"
        ),
    )

    op.create_table(
        "episodes",
        _uuid_pk(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("project_id", "sequence_no", name="uq_episodes_project_sequence"),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'archived')", name="ck_episodes_status"
        ),
    )

    op.create_table(
        "scenes",
        _uuid_pk(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id"),
            nullable=True,
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        # FK на artifacts добавляется после создания artifacts.
        sa.Column("audio_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        _created_at(),
    )

    op.create_table(
        "shots",
        _uuid_pk(),
        sa.Column(
            "scene_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("scenes.id"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("target_duration_frames", sa.Integer(), nullable=True),
        sa.Column("timeline_fps", sa.Numeric(8, 3), nullable=True),
        # FK на prompt_revisions добавляется после создания prompt_revisions.
        sa.Column("current_prompt_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "continuity_from_shot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shots.id"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        # FK на render_attempts добавляется после создания render_attempts.
        sa.Column("approved_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("scene_id", "sequence_no", name="uq_shots_scene_sequence"),
        sa.CheckConstraint(
            "status IN ('draft', 'prompt_ready', 'keyframe_ready', 'queued',"
            " 'generating', 'review', 'approved', 'changes_requested')",
            name="ck_shots_status",
        ),
    )

    op.create_table(
        "prompt_revisions",
        _uuid_pk(),
        sa.Column(
            "shot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shots.id"),
            nullable=False,
        ),
        sa.Column("prompt_type", sa.Text(), nullable=False, server_default="motion"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("parameters_json", postgresql.JSONB(), nullable=True),
        _created_at(),
        sa.UniqueConstraint(
            "shot_id", "prompt_type", "version", name="uq_prompt_revisions_shot_type_version"
        ),
        sa.CheckConstraint(
            "prompt_type IN ('keyframe', 'motion', 'composition', 'script', 'other')",
            name="ck_prompt_revisions_type",
        ),
        sa.CheckConstraint("version >= 1", name="ck_prompt_revisions_version_positive"),
    )

    op.create_table(
        "jobs",
        _uuid_pk(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "scene_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("scenes.id"), nullable=True
        ),
        sa.Column(
            "shot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("shots.id"), nullable=True
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.CheckConstraint(
            "status IN ('pending', 'leased', 'running', 'completed', 'failed',"
            " 'cancel_requested', 'cancelled', 'retry_wait', 'lease_expired')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint(
            "(scene_id IS NOT NULL)::int + (shot_id IS NOT NULL)::int = 1",
            name="ck_jobs_single_target",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_jobs_attempts_non_negative"),
        sa.CheckConstraint("max_attempts > 0", name="ck_jobs_max_attempts_positive"),
    )
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_index(
        "one_active_render_per_shot",
        "jobs",
        ["shot_id"],
        unique=True,
        postgresql_where=sa.text(
            "kind = 'render_video' AND status IN"
            " ('pending','leased','running','retry_wait','cancel_requested','lease_expired')"
        ),
    )
    op.create_index(
        "uq_jobs_idempotency_key",
        "jobs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "job_dependencies",
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "depends_on_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.CheckConstraint("job_id <> depends_on_job_id", name="ck_job_dependencies_no_self"),
    )

    op.create_table(
        "workers",
        _uuid_pk(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(), nullable=True),
        sa.Column("comfy_version", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="unknown"),
    )

    op.create_table(
        "render_attempts",
        _uuid_pk(),
        sa.Column(
            "shot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shots.id"),
            nullable=False,
        ),
        sa.Column(
            "job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id"), nullable=True
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "prompt_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_revisions.id"),
            nullable=True,
        ),
        sa.Column("input_artifact_ids", postgresql.JSONB(), nullable=True),
        sa.Column("workflow_version", sa.Text(), nullable=True),
        sa.Column("model_hash", sa.Text(), nullable=True),
        sa.Column("seed", sa.BigInteger(), nullable=True),
        sa.Column("native_fps", sa.Numeric(8, 3), nullable=True),
        sa.Column("parameters", postgresql.JSONB(), nullable=True),
        sa.Column(
            "worker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workers.id"),
            nullable=True,
        ),
        sa.Column("duration_s", sa.Numeric(10, 3), nullable=True),
        sa.Column("peak_mem_mb", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        _created_at(),
        sa.CheckConstraint("kind IN ('keyframe', 'video', 'postprocess')", name="ck_render_attempts_kind"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_render_attempts_status",
        ),
        sa.CheckConstraint(
            "job_id IS NOT NULL OR kind = 'keyframe'",
            name="ck_render_attempts_job_required",
        ),
    )

    op.create_table(
        "artifacts",
        _uuid_pk(),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("render_attempts.id"),
            nullable=True,
        ),
        # FK на shot_compositions появится в WP-02 вместе с самой таблицей.
        sa.Column("shot_composition_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "source IN ('attempt', 'composition', 'upload', 'import')", name="ck_artifacts_source"
        ),
        sa.CheckConstraint(
            "(attempt_id IS NOT NULL)::int"
            " + (shot_composition_id IS NOT NULL)::int"
            " + (source IN ('upload', 'import'))::int = 1",
            name="ck_artifacts_single_source",
        ),
        sa.CheckConstraint(
            "(source = 'attempt' AND attempt_id IS NOT NULL)"
            " OR (source = 'composition' AND shot_composition_id IS NOT NULL)"
            " OR (source IN ('upload', 'import')"
            "     AND attempt_id IS NULL AND shot_composition_id IS NULL)",
            name="ck_artifacts_source_matches_link",
        ),
        sa.CheckConstraint("bytes >= 0", name="ck_artifacts_bytes_non_negative"),
    )
    op.create_index("ix_artifacts_sha256", "artifacts", ["sha256"])

    op.create_table(
        "reference_assets",
        _uuid_pk(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "kind IN ('character_reference', 'location_reference', 'prop_reference', 'uploaded')",
            name="ck_reference_assets_kind",
        ),
    )

    # Циклические FK: добавляются после создания всех таблиц.
    op.create_foreign_key(
        "fk_scenes_audio_artifact", "scenes", "artifacts", ["audio_artifact_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_shots_current_prompt_revision",
        "shots",
        "prompt_revisions",
        ["current_prompt_revision_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_shots_approved_attempt", "shots", "render_attempts", ["approved_attempt_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_shots_approved_attempt", "shots", type_="foreignkey")
    op.drop_constraint("fk_shots_current_prompt_revision", "shots", type_="foreignkey")
    op.drop_constraint("fk_scenes_audio_artifact", "scenes", type_="foreignkey")

    op.drop_table("reference_assets")
    op.drop_index("ix_artifacts_sha256", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_table("render_attempts")
    op.drop_table("workers")
    op.drop_table("job_dependencies")
    op.drop_index("uq_jobs_idempotency_key", table_name="jobs")
    op.drop_index("one_active_render_per_shot", table_name="jobs")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("prompt_revisions")
    op.drop_table("shots")
    op.drop_table("scenes")
    op.drop_table("episodes")
    op.drop_table("projects")
