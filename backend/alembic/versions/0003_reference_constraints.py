"""reference_assets: project isolation and owner constraints

Revision ID: 0003_reference_constraints
Revises: 0002_character_library
Create Date: 2026-10-26

S1: владелец соответствует `kind`; §3.2: составные FK на владельцев,
`UNIQUE(project_id, id)` как цель составных FK для `shot_references`
и `shot_composition_layers`, дедупликация `UNIQUE(project_id, sha256)`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_reference_constraints"
down_revision: str | None = "0002_character_library"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

OWNER_MATCHES_KIND = (
    "(kind = 'character_reference' AND character_id IS NOT NULL"
    " AND location_id IS NULL AND prop_id IS NULL)"
    " OR (kind = 'location_reference' AND location_id IS NOT NULL"
    " AND character_id IS NULL AND prop_id IS NULL)"
    " OR (kind = 'prop_reference' AND prop_id IS NOT NULL"
    " AND character_id IS NULL AND location_id IS NULL)"
    " OR (kind = 'uploaded' AND character_id IS NULL"
    " AND location_id IS NULL AND prop_id IS NULL)"
)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_reference_assets_project_id", "reference_assets", ["project_id", "id"]
    )
    op.create_unique_constraint(
        "uq_reference_assets_project_sha256", "reference_assets", ["project_id", "sha256"]
    )

    op.create_check_constraint(
        "ck_reference_assets_owner_matches_kind", "reference_assets", OWNER_MATCHES_KIND
    )

    op.create_foreign_key(
        "fk_reference_assets_character_project",
        "reference_assets",
        "characters",
        ["project_id", "character_id"],
        ["project_id", "id"],
    )
    op.create_foreign_key(
        "fk_reference_assets_location_project",
        "reference_assets",
        "locations",
        ["project_id", "location_id"],
        ["project_id", "id"],
    )
    op.create_foreign_key(
        "fk_reference_assets_prop_project",
        "reference_assets",
        "props",
        ["project_id", "prop_id"],
        ["project_id", "id"],
    )

    op.create_index("ix_reference_assets_character_id", "reference_assets", ["character_id"])
    op.create_index("ix_reference_assets_location_id", "reference_assets", ["location_id"])
    op.create_index("ix_reference_assets_prop_id", "reference_assets", ["prop_id"])
    op.create_index(
        "ix_reference_assets_project_status", "reference_assets", ["project_id", "status"]
    )

    # §5.2: metadata — NOT NULL с пустым объектом по умолчанию.
    op.alter_column(
        "reference_assets",
        "metadata",
        existing_type=postgresql.JSONB(),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )


def downgrade() -> None:
    op.alter_column(
        "reference_assets",
        "metadata",
        existing_type=postgresql.JSONB(),
        nullable=True,
        server_default=None,
    )

    op.drop_index("ix_reference_assets_project_status", table_name="reference_assets")
    op.drop_index("ix_reference_assets_prop_id", table_name="reference_assets")
    op.drop_index("ix_reference_assets_location_id", table_name="reference_assets")
    op.drop_index("ix_reference_assets_character_id", table_name="reference_assets")

    op.drop_constraint(
        "fk_reference_assets_prop_project", "reference_assets", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_reference_assets_location_project", "reference_assets", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_reference_assets_character_project", "reference_assets", type_="foreignkey"
    )

    op.drop_constraint(
        "ck_reference_assets_owner_matches_kind", "reference_assets", type_="check"
    )
    op.drop_constraint(
        "uq_reference_assets_project_sha256", "reference_assets", type_="unique"
    )
    op.drop_constraint("uq_reference_assets_project_id", "reference_assets", type_="unique")
