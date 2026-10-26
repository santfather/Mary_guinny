"""character library: characters, bible versions, locations, props

Revision ID: 0002_character_library
Revises: 0001_initial_core
Create Date: 2026-10-26

Новые сущности библиотеки (S4–S6) и расширение `reference_assets` полями S2.
Составные FK и уникальные индексы — в следующей миграции `0003`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_character_library"
down_revision: str | None = "0001_initial_core"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

LIBRARY_STATUSES = "('draft', 'active', 'archived')"


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
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
    )


def _create_library_table(table: str, status_check: str) -> None:
    created_at, updated_at = _timestamps()
    op.create_table(
        table,
        _uuid_pk(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        created_at,
        updated_at,
        sa.UniqueConstraint("project_id", "slug", name=f"uq_{table}_project_slug"),
        sa.UniqueConstraint("project_id", "id", name=f"uq_{table}_project_id"),
        sa.CheckConstraint(f"status IN {LIBRARY_STATUSES}", name=status_check),
    )


def upgrade() -> None:
    op.create_table(
        "characters",
        _uuid_pk(),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id"),
            nullable=False,
        ),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="other"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        *_timestamps(),
        sa.UniqueConstraint("project_id", "slug", name="uq_characters_project_slug"),
        sa.UniqueConstraint("project_id", "id", name="uq_characters_project_id"),
        sa.CheckConstraint("kind IN ('cat', 'human', 'other')", name="ck_characters_kind"),
        sa.CheckConstraint(f"status IN {LIBRARY_STATUSES}", name="ck_characters_status"),
    )

    # S16: project_id денормализован, чтобы bible нельзя было привязать к чужому проекту.
    op.create_table(
        "character_bible_versions",
        _uuid_pk(),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("character_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id", "character_id"],
            ["characters.project_id", "characters.id"],
            name="fk_bible_character_project",
        ),
        sa.UniqueConstraint("character_id", "version", name="uq_bible_character_version"),
        sa.CheckConstraint("version >= 1", name="ck_bible_version_positive"),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'superseded')", name="ck_bible_status"
        ),
        sa.CheckConstraint("source IN ('manual', 'import')", name="ck_bible_source"),
        sa.CheckConstraint(
            "status <> 'approved' OR approved_at IS NOT NULL", name="ck_bible_approved_at"
        ),
    )

    _create_library_table("locations", "ck_locations_status")
    _create_library_table("props", "ck_props_status")

    # S2: расширение reference_assets (составные FK — в 0003).
    op.add_column("reference_assets", sa.Column("character_id", postgresql.UUID(as_uuid=True)))
    op.add_column("reference_assets", sa.Column("location_id", postgresql.UUID(as_uuid=True)))
    op.add_column("reference_assets", sa.Column("prop_id", postgresql.UUID(as_uuid=True)))
    op.add_column(
        "reference_assets",
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
    )
    op.add_column("reference_assets", sa.Column("role", sa.Text()))
    op.add_column("reference_assets", sa.Column("view", sa.Text()))
    op.add_column("reference_assets", sa.Column("pose", sa.Text()))
    op.add_column("reference_assets", sa.Column("expression", sa.Text()))
    op.add_column("reference_assets", sa.Column("width", sa.Integer()))
    op.add_column("reference_assets", sa.Column("height", sa.Integer()))
    op.add_column("reference_assets", sa.Column("mime_type", sa.Text()))
    op.add_column("reference_assets", sa.Column("approved_at", sa.DateTime(timezone=True)))

    op.create_check_constraint(
        "ck_reference_assets_status",
        "reference_assets",
        "status IN ('draft', 'approved', 'rejected', 'superseded')",
    )
    op.create_check_constraint(
        "ck_reference_assets_view",
        "reference_assets",
        "view IS NULL OR view IN ('front', 'side', 'three_quarter', 'back', 'other')",
    )
    op.create_check_constraint(
        "ck_reference_assets_pose",
        "reference_assets",
        "pose IS NULL OR pose IN ('stand', 'sit', 'walk', 'lie', 'sleep', 'custom')",
    )
    op.create_check_constraint(
        "ck_reference_assets_width_positive", "reference_assets", "width IS NULL OR width > 0"
    )
    op.create_check_constraint(
        "ck_reference_assets_height_positive", "reference_assets", "height IS NULL OR height > 0"
    )
    op.create_check_constraint(
        "ck_reference_assets_approved_at",
        "reference_assets",
        "status <> 'approved' OR approved_at IS NOT NULL",
    )


def downgrade() -> None:
    for name in (
        "ck_reference_assets_approved_at",
        "ck_reference_assets_height_positive",
        "ck_reference_assets_width_positive",
        "ck_reference_assets_pose",
        "ck_reference_assets_view",
        "ck_reference_assets_status",
    ):
        op.drop_constraint(name, "reference_assets", type_="check")

    for column in (
        "approved_at",
        "mime_type",
        "height",
        "width",
        "expression",
        "pose",
        "view",
        "role",
        "status",
        "prop_id",
        "location_id",
        "character_id",
    ):
        op.drop_column("reference_assets", column)

    op.drop_table("props")
    op.drop_table("locations")
    op.drop_table("character_bible_versions")
    op.drop_table("characters")
