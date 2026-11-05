"""mouth calibrations (WP-VOICE-02)

Revision ID: 0011_mouth_calibrations
Revises: 0010_audio_timeline_plans
Create Date: 2026-11-04

Калибровка области рта для режима `mouth_animation_mvp`: нормализованные
координаты области (0…1), поворот и параметры сглаживания. Approved-референсы
и стартовые кадры не меняются — таблица только читает их идентификаторы.
Основание: `docs/DECISIONS.md` §4.18, `docs/PROPOSALS/WP_VOICE_02_MOUTH_ANIMATION.md`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_mouth_calibrations"
down_revision: str | None = "0010_audio_timeline_plans"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mouth_calibrations",
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
        sa.Column(
            "reference_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reference_assets.id"),
            nullable=True,
        ),
        sa.Column(
            "keyframe_artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("artifacts.id"),
            nullable=True,
        ),
        sa.Column("x", sa.Double(), nullable=False),
        sa.Column("y", sa.Double(), nullable=False),
        sa.Column("width", sa.Double(), nullable=False),
        sa.Column("height", sa.Double(), nullable=False),
        sa.Column("rotation", sa.Double(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_open", sa.Double(), nullable=False, server_default=sa.text("0.8")),
        sa.Column("sensitivity", sa.Double(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("smoothing", sa.Double(), nullable=False, server_default=sa.text("0.5")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "(reference_asset_id IS NOT NULL)::int"
            " + (keyframe_artifact_id IS NOT NULL)::int = 1",
            name="ck_mouth_calibrations_single_source",
        ),
        sa.CheckConstraint(
            "x >= 0 AND y >= 0 AND width > 0 AND height > 0"
            " AND x + width <= 1 AND y + height <= 1",
            name="ck_mouth_calibrations_region",
        ),
        sa.CheckConstraint(
            "rotation >= -180 AND rotation <= 180",
            name="ck_mouth_calibrations_rotation",
        ),
        sa.CheckConstraint(
            "max_open > 0 AND max_open <= 1", name="ck_mouth_calibrations_max_open"
        ),
        sa.CheckConstraint(
            "sensitivity > 0 AND sensitivity <= 5",
            name="ck_mouth_calibrations_sensitivity",
        ),
        sa.CheckConstraint(
            "smoothing >= 0 AND smoothing < 1", name="ck_mouth_calibrations_smoothing"
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_mouth_calibrations_shot_reference"
        " ON mouth_calibrations (shot_id, reference_asset_id)"
        " WHERE reference_asset_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_mouth_calibrations_shot_keyframe"
        " ON mouth_calibrations (shot_id, keyframe_artifact_id)"
        " WHERE keyframe_artifact_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_mouth_calibrations_shot_keyframe")
    op.execute("DROP INDEX IF EXISTS uq_mouth_calibrations_shot_reference")
    op.drop_table("mouth_calibrations")
