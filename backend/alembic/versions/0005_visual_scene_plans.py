"""visual scene plans (WP-05A)

Revision ID: 0005_visual_scene_plans
Revises: 0004_composition_revisions
Create Date: 2026-10-26

S19: версионируемый план сцены, привязанный к шоту. Approved-ревизия неизменяема
(триггер `mary_forbid_approved_change()` из 0004). `shot_compositions.source_plan_id`
фиксирует происхождение композиции: plan → composition → attempt → artifact.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_visual_scene_plans"
down_revision: str | None = "0004_composition_revisions"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

PLAN_STATUSES = ("draft", "approved", "superseded")
PLAN_SOURCES = ("manual", "llm", "fallback")


def upgrade() -> None:
    op.create_table(
        "visual_scene_plans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column(
            "shot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shots.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "schema_version", sa.Integer(), nullable=False, server_default="1"
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
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
            server_default=sa.text("now()"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "shot_id", "revision", name="uq_visual_scene_plans_shot_revision"
        ),
        sa.UniqueConstraint("project_id", "id", name="uq_visual_scene_plans_project_id"),
        sa.CheckConstraint("revision >= 1", name="ck_visual_scene_plans_revision_positive"),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_visual_scene_plans_schema_version_positive"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'superseded')",
            name="ck_visual_scene_plans_status",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'llm', 'fallback')",
            name="ck_visual_scene_plans_source",
        ),
        sa.CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL",
            name="ck_visual_scene_plans_approved_at",
        ),
    )
    op.create_index(
        "ix_visual_scene_plans_shot_status",
        "visual_scene_plans",
        ["shot_id", "status"],
    )
    # Одна утверждённая ревизия плана на шот; смена — только через supersede.
    op.execute(
        "CREATE UNIQUE INDEX uq_visual_scene_plans_one_approved"
        " ON visual_scene_plans (shot_id) WHERE status = 'approved'"
    )
    op.execute(
        "CREATE TRIGGER trg_visual_scene_plans_approved_immutable"
        " BEFORE UPDATE OR DELETE ON visual_scene_plans"
        " FOR EACH ROW EXECUTE FUNCTION mary_forbid_approved_change()"
    )

    op.add_column(
        "shot_compositions",
        sa.Column("source_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_shot_compositions_source_plan",
        "shot_compositions",
        "visual_scene_plans",
        ["source_plan_id"],
        ["id"],
    )
    op.create_index(
        "ix_shot_compositions_source_plan_id",
        "shot_compositions",
        ["source_plan_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shot_compositions_source_plan_id", table_name="shot_compositions"
    )
    op.drop_constraint(
        "fk_shot_compositions_source_plan", "shot_compositions", type_="foreignkey"
    )
    op.drop_column("shot_compositions", "source_plan_id")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_visual_scene_plans_approved_immutable"
        " ON visual_scene_plans"
    )
    op.execute("DROP INDEX IF EXISTS uq_visual_scene_plans_one_approved")
    op.drop_index(
        "ix_visual_scene_plans_shot_status", table_name="visual_scene_plans"
    )
    op.drop_table("visual_scene_plans")
