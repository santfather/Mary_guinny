"""series run title (WP-08)

Revision ID: 0008_series_run_title
Revises: 0007_render_series
Create Date: 2026-10-28

Человеческое имя прогона серии (например, «NLB-single»). Поле необязательное:
прогоны без имени продолжают существовать и опознаются по `id`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_series_run_title"
down_revision: str | None = "0007_render_series"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("series_runs", sa.Column("title", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("series_runs", "title")
