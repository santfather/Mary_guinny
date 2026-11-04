"""audio timeline и production plans (WP-M3)

Revision ID: 0010_audio_timeline_plans
Revises: 0009_export_artifacts
Create Date: 2026-11-04

1. `projects.audio_artifact_id` — песня проекта (один трек на проект), из неё
   строится таймлайн.
2. `production_plans` — ревизии чернового плана: ответ LLM, таймлайн-снимок и
   предупреждения. Утверждение плана и применение к сценам в WP-M3 не входят,
   поэтому статусы только `draft`/`superseded`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_audio_timeline_plans"
down_revision: str | None = "0009_export_artifacts"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("audio_artifact_id", postgresql.UUID(as_uuid=True)))
    op.create_foreign_key(
        "fk_projects_audio_artifact",
        "projects",
        "artifacts",
        ["audio_artifact_id"],
        ["id"],
    )

    op.create_table(
        "production_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'llm'")),
        sa.Column("audio_artifact_id", postgresql.UUID(as_uuid=True)),
        sa.Column("timeline", postgresql.JSONB(), nullable=False),
        sa.Column("plan", postgresql.JSONB(), nullable=False),
        sa.Column(
            "warnings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(
            ["audio_artifact_id"],
            ["artifacts.id"],
            name="fk_production_plans_audio_artifact",
        ),
        sa.UniqueConstraint("project_id", "revision", name="uq_production_plans_project_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_production_plans_revision_positive"),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_production_plans_schema_version_positive"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'superseded')", name="ck_production_plans_status"
        ),
        sa.CheckConstraint(
            "source IN ('llm', 'manual', 'fallback')", name="ck_production_plans_source"
        ),
    )
    op.create_index(
        "ix_production_plans_project_created",
        "production_plans",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_production_plans_project_created", table_name="production_plans")
    op.drop_table("production_plans")
    op.drop_constraint("fk_projects_audio_artifact", "projects", type_="foreignkey")
    op.drop_column("projects", "audio_artifact_id")
