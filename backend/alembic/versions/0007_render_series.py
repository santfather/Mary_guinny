"""render series (WP-N4)

Revision ID: 0007_render_series
Revises: 0006_events
Create Date: 2026-10-28

Прогон серии: намерение человека (start/pause/resume/stop-after-current/cancel)
и прогресс по шотам. Тяжёлые job по-прежнему живут в `jobs`; таблицы серии не
дублируют статусы job, а лишь ссылаются на них.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_render_series"
down_revision: str | None = "0006_events"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

RUN_STATUSES = ("draft", "running", "paused", "stopping", "completed", "cancelled", "failed")
ITEM_STATUSES = ("pending", "running", "completed", "failed", "skipped")


def upgrade() -> None:
    op.create_table(
        "series_runs",
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
        sa.Column("manifest_sha256", sa.String(64), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "stop_on_error", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{name}'" for name in RUN_STATUSES) + ")",
            name="ck_series_runs_status",
        ),
        sa.CheckConstraint(
            "total_items >= 0", name="ck_series_runs_total_items_non_negative"
        ),
    )
    op.create_index("ix_series_runs_project_status", "series_runs", ["project_id", "status"])

    op.create_table(
        "series_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("series_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shots.id"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id"),
            nullable=True,
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('"order" >= 1', name="ck_series_items_order_positive"),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{name}'" for name in ITEM_STATUSES) + ")",
            name="ck_series_items_status",
        ),
        sa.UniqueConstraint("run_id", "order", name="uq_series_items_run_order"),
        sa.UniqueConstraint("run_id", "shot_id", name="uq_series_items_run_shot"),
    )
    op.create_index("ix_series_items_run_status", "series_items", ["run_id", "status"])
    op.create_index("ix_series_items_job_id", "series_items", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_series_items_job_id", table_name="series_items")
    op.drop_index("ix_series_items_run_status", table_name="series_items")
    op.drop_table("series_items")
    op.drop_index("ix_series_runs_project_status", table_name="series_runs")
    op.drop_table("series_runs")
