"""events journal (WP-06)

Revision ID: 0006_events
Revises: 0005_visual_scene_plans
Create Date: 2026-10-26

Журнал событий job/attempt: claim, progress, artifact, completed, failed,
lease_expired, resumed. Источник истины о статусе остаётся в `jobs`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_events"
down_revision: str | None = "0005_visual_scene_plans"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

EVENT_NAMES = (
    "claimed",
    "progress",
    "artifact_uploaded",
    "completed",
    "failed",
    "lease_expired",
    "resumed",
)


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id"),
            nullable=True,
        ),
        sa.Column(
            "attempt_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("render_attempts.id"),
            nullable=True,
        ),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("progress", sa.Numeric(5, 4), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "event IN ("
            + ", ".join(f"'{name}'" for name in EVENT_NAMES)
            + ")",
            name="ck_events_event",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_events_sequence_positive"),
        sa.CheckConstraint(
            "job_id IS NOT NULL OR attempt_id IS NOT NULL", name="ck_events_target"
        ),
        sa.CheckConstraint(
            "progress IS NULL OR (progress >= 0 AND progress <= 1)",
            name="ck_events_progress_range",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_events_job_sequence"
        " ON events (job_id, sequence) WHERE job_id IS NOT NULL"
    )
    op.create_index("ix_events_attempt_id", "events", ["attempt_id"])


def downgrade() -> None:
    op.drop_index("ix_events_attempt_id", table_name="events")
    op.execute("DROP INDEX IF EXISTS uq_events_job_sequence")
    op.drop_table("events")
