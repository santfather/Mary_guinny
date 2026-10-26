"""shot references, composition revisions and start keyframe pointers

Revision ID: 0004_composition_revisions
Revises: 0003_reference_constraints
Create Date: 2026-10-26

S7 (`shot_references`), S8 (`shot_compositions` + `shot_composition_layers`),
S9 (`shots.start_keyframe_*`), завершение S12 (`artifacts.shot_composition_id` FK)
и S15 — триггеры иммутабельности approved-записей.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_composition_revisions"
down_revision: str | None = "0003_reference_constraints"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION mary_forbid_approved_change() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    old_row jsonb := to_jsonb(OLD);
    new_row jsonb := to_jsonb(NEW);
BEGIN
    IF old_row ->> 'status' IS DISTINCT FROM 'approved' THEN
        RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'approved row in % cannot be deleted', TG_TABLE_NAME;
    END IF;
    IF (new_row - 'status' - 'approved_at' - 'updated_at')
       IS DISTINCT FROM (old_row - 'status' - 'approved_at' - 'updated_at') THEN
        RAISE EXCEPTION 'approved row in % is immutable; create a new revision', TG_TABLE_NAME;
    END IF;
    IF (new_row ->> 'status') NOT IN ('superseded', 'rejected') THEN
        RAISE EXCEPTION 'approved row in % allows only status superseded/rejected', TG_TABLE_NAME;
    END IF;
    RETURN NEW;
END;
$$;
"""

IMMUTABLE_TABLES = ("reference_assets", "character_bible_versions", "shot_compositions")


def upgrade() -> None:
    op.create_table(
        "shot_references",
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
        sa.Column("reference_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "reference_asset_id"],
            ["reference_assets.project_id", "reference_assets.id"],
            name="fk_shot_references_asset_project",
        ),
        sa.UniqueConstraint(
            "shot_id",
            "reference_asset_id",
            "purpose",
            name="uq_shot_references_shot_asset_purpose",
        ),
        sa.CheckConstraint(
            "purpose IN ('character', 'location', 'prop', 'style', 'other')",
            name="ck_shot_references_purpose",
        ),
    )
    op.create_index(
        "ix_shot_references_reference_asset_id", "shot_references", ["reference_asset_id"]
    )

    # preview_artifact_id FK добавляется после создания artifacts-ссылки (циклическая пара).
    op.create_table(
        "shot_compositions",
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
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("preview_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("shot_id", "revision", name="uq_shot_compositions_shot_revision"),
        sa.CheckConstraint("revision >= 1", name="ck_shot_compositions_revision_positive"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'superseded')", name="ck_shot_compositions_status"
        ),
        sa.CheckConstraint("width > 0", name="ck_shot_compositions_width_positive"),
        sa.CheckConstraint("height > 0", name="ck_shot_compositions_height_positive"),
        sa.CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL",
            name="ck_shot_compositions_approved_at",
        ),
    )
    op.create_index(
        "ix_shot_compositions_preview_artifact_id", "shot_compositions", ["preview_artifact_id"]
    )

    op.create_table(
        "shot_composition_layers",
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
            "composition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shot_compositions.id"),
            nullable=False,
        ),
        sa.Column("reference_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("z_index", sa.Integer(), nullable=False),
        sa.Column("x", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("y", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("scale", sa.Numeric(10, 4), nullable=False, server_default="1"),
        sa.Column("rotation", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("opacity", sa.Numeric(4, 3), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["project_id", "reference_asset_id"],
            ["reference_assets.project_id", "reference_assets.id"],
            name="fk_composition_layers_asset_project",
        ),
        sa.UniqueConstraint("composition_id", "z_index", name="uq_composition_layers_z_index"),
        sa.CheckConstraint("z_index >= 0", name="ck_composition_layers_z_index_non_negative"),
        sa.CheckConstraint("scale > 0", name="ck_composition_layers_scale_positive"),
        sa.CheckConstraint(
            "opacity >= 0 AND opacity <= 1", name="ck_composition_layers_opacity_range"
        ),
    )
    op.create_index(
        "ix_composition_layers_reference_asset_id",
        "shot_composition_layers",
        ["reference_asset_id"],
    )

    op.create_foreign_key(
        "fk_artifacts_shot_composition",
        "artifacts",
        "shot_compositions",
        ["shot_composition_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_shot_compositions_preview_artifact",
        "shot_compositions",
        "artifacts",
        ["preview_artifact_id"],
        ["id"],
    )

    op.add_column(
        "shots",
        sa.Column("start_keyframe_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "shots",
        sa.Column("start_keyframe_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_shots_start_keyframe_artifact",
        "shots",
        "artifacts",
        ["start_keyframe_artifact_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_shots_start_keyframe_attempt",
        "shots",
        "render_attempts",
        ["start_keyframe_attempt_id"],
        ["id"],
    )

    # S15: approved-записи неизменяемы; допустим только отзыв/ошибка приёмки.
    op.execute(IMMUTABILITY_FUNCTION)
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_approved_immutable"
            f" BEFORE UPDATE OR DELETE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION mary_forbid_approved_change()"
        )


def downgrade() -> None:
    for table in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_approved_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS mary_forbid_approved_change()")

    op.drop_constraint("fk_shots_start_keyframe_attempt", "shots", type_="foreignkey")
    op.drop_constraint("fk_shots_start_keyframe_artifact", "shots", type_="foreignkey")
    op.drop_column("shots", "start_keyframe_attempt_id")
    op.drop_column("shots", "start_keyframe_artifact_id")

    op.drop_constraint(
        "fk_shot_compositions_preview_artifact", "shot_compositions", type_="foreignkey"
    )
    op.drop_constraint("fk_artifacts_shot_composition", "artifacts", type_="foreignkey")

    op.drop_index(
        "ix_composition_layers_reference_asset_id", table_name="shot_composition_layers"
    )
    op.drop_table("shot_composition_layers")
    op.drop_index(
        "ix_shot_compositions_preview_artifact_id", table_name="shot_compositions"
    )
    op.drop_table("shot_compositions")
    op.drop_index("ix_shot_references_reference_asset_id", table_name="shot_references")
    op.drop_table("shot_references")
