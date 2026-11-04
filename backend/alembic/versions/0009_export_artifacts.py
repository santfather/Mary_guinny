"""export artifacts (WP-M2)

Revision ID: 0009_export_artifacts
Revises: 0008_series_run_title
Create Date: 2026-11-04

Собранный MP4 хранится как обычный artifact с `source='export'` (решение
2026-11-04, DECISIONS §4.8). Ссылки `attempt_id`/`shot_composition_id` не
заполняются — провенанс лежит в `artifacts.metadata` (проект, клипы, таймкоды,
аудио). Это расширение инварианта S12: «export» — четвёртый источник наряду с
upload/import.

Downgrade удаляет export-артефакты: старые CHECK-константы не допускают
source='export'. Blob-файлы в storage остаются (сборка мусора не входит в WP).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_export_artifacts"
down_revision: str | None = "0008_series_run_title"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

ARTIFACT_SOURCES_WITH_EXPORT = (
    "attempt",
    "composition",
    "upload",
    "import",
    "export",
)
ARTIFACT_SOURCES_WITHOUT_EXPORT = ("attempt", "composition", "upload", "import")


def _source_check(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({joined})"


def upgrade() -> None:
    op.add_column(
        "artifacts",
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.drop_constraint("ck_artifacts_source", "artifacts", type_="check")
    op.drop_constraint("ck_artifacts_single_source", "artifacts", type_="check")
    op.drop_constraint("ck_artifacts_source_matches_link", "artifacts", type_="check")

    linked = ", ".join(f"'{value}'" for value in ("upload", "import", "export"))
    op.create_check_constraint(
        "ck_artifacts_source",
        "artifacts",
        _source_check("source", ARTIFACT_SOURCES_WITH_EXPORT),
    )
    op.create_check_constraint(
        "ck_artifacts_single_source",
        "artifacts",
        "(attempt_id IS NOT NULL)::int"
        " + (shot_composition_id IS NOT NULL)::int"
        f" + (source IN ({linked}))::int = 1",
    )
    op.create_check_constraint(
        "ck_artifacts_source_matches_link",
        "artifacts",
        "(source = 'attempt' AND attempt_id IS NOT NULL)"
        " OR (source = 'composition' AND shot_composition_id IS NOT NULL)"
        f" OR (source IN ({linked})"
        "     AND attempt_id IS NULL AND shot_composition_id IS NULL)",
    )


def downgrade() -> None:
    op.execute("DELETE FROM artifacts WHERE source = 'export'")

    op.drop_constraint("ck_artifacts_source", "artifacts", type_="check")
    op.drop_constraint("ck_artifacts_single_source", "artifacts", type_="check")
    op.drop_constraint("ck_artifacts_source_matches_link", "artifacts", type_="check")

    linked = ", ".join(f"'{value}'" for value in ("upload", "import"))
    op.create_check_constraint(
        "ck_artifacts_source",
        "artifacts",
        _source_check("source", ARTIFACT_SOURCES_WITHOUT_EXPORT),
    )
    op.create_check_constraint(
        "ck_artifacts_single_source",
        "artifacts",
        "(attempt_id IS NOT NULL)::int"
        " + (shot_composition_id IS NOT NULL)::int"
        f" + (source IN ({linked}))::int = 1",
    )
    op.create_check_constraint(
        "ck_artifacts_source_matches_link",
        "artifacts",
        "(source = 'attempt' AND attempt_id IS NOT NULL)"
        " OR (source = 'composition' AND shot_composition_id IS NOT NULL)"
        f" OR (source IN ({linked})"
        "     AND attempt_id IS NULL AND shot_composition_id IS NULL)",
    )

    op.drop_column("artifacts", "metadata")
