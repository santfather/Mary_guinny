"""Библиотека персонажей WP-02: структура таблиц и базовые сценарии."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import Connection, text

LIBRARY_COLUMNS: dict[str, set[str]] = {
    "characters": {
        "id",
        "project_id",
        "slug",
        "name",
        "kind",
        "description",
        "status",
        "created_at",
        "updated_at",
    },
    "character_bible_versions": {
        "id",
        "project_id",
        "character_id",
        "version",
        "body",
        "sha256",
        "status",
        "source",
        "created_at",
        "approved_at",
    },
    "locations": {
        "id",
        "project_id",
        "slug",
        "name",
        "description",
        "status",
        "created_at",
        "updated_at",
    },
    "props": {
        "id",
        "project_id",
        "slug",
        "name",
        "description",
        "status",
        "created_at",
        "updated_at",
    },
    "reference_assets": {
        "id",
        "project_id",
        "kind",
        "character_id",
        "location_id",
        "prop_id",
        "status",
        "role",
        "view",
        "pose",
        "expression",
        "storage_key",
        "sha256",
        "width",
        "height",
        "mime_type",
        "metadata",
        "created_at",
        "approved_at",
    },
    "shot_references": {
        "id",
        "project_id",
        "shot_id",
        "reference_asset_id",
        "purpose",
        "created_at",
    },
    "shot_compositions": {
        "id",
        "project_id",
        "shot_id",
        "revision",
        "width",
        "height",
        "status",
        "preview_artifact_id",
        "created_at",
        "approved_at",
    },
    "shot_composition_layers": {
        "id",
        "project_id",
        "composition_id",
        "reference_asset_id",
        "z_index",
        "x",
        "y",
        "scale",
        "rotation",
        "opacity",
    },
}


def _sha() -> str:
    return uuid.uuid4().hex * 2


def _columns(conn: Connection) -> dict[str, set[str]]:
    rows = conn.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns"
            " WHERE table_schema = 'public'"
        )
    ).all()
    result: dict[str, set[str]] = {}
    for table, column in rows:
        result.setdefault(table, set()).add(column)
    return result


def test_library_tables_have_expected_columns(conn: Connection) -> None:
    actual = _columns(conn)

    for table, expected in LIBRARY_COLUMNS.items():
        assert table in actual, f"missing table {table}"
        assert expected <= actual[table], f"missing columns in {table}: {expected - actual[table]}"


def test_shots_store_start_keyframe_pointers(conn: Connection) -> None:
    assert {"start_keyframe_artifact_id", "start_keyframe_attempt_id"} <= _columns(conn)["shots"]


def test_character_defaults_kind_and_status(conn: Connection, project_id: uuid.UUID) -> None:
    character = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO characters (id, project_id, slug, name)"
            " VALUES (:id, :project_id, 'new-cat', 'New cat')"
        ),
        {"id": character, "project_id": project_id},
    )

    row = conn.execute(
        text("SELECT kind, status FROM characters WHERE id = :id"), {"id": character}
    ).one()

    assert row.kind == "other"
    assert row.status == "draft"


def test_character_slug_is_unique_per_project(
    conn: Connection,
    project_id: uuid.UUID,
    second_project_id: uuid.UUID,
    expect_violation: Callable[..., None],
) -> None:
    params = {"id": uuid.uuid4(), "project_id": project_id}
    conn.execute(
        text(
            "INSERT INTO characters (id, project_id, slug, name)"
            " VALUES (:id, :project_id, 'guinness', 'Guinness')"
        ),
        params,
    )

    expect_violation(
        "INSERT INTO characters (id, project_id, slug, name)"
        " VALUES (:id, :project_id, 'guinness', 'Guinness clone')",
        {"id": uuid.uuid4(), "project_id": project_id},
        "uq_characters_project_slug",
    )

    conn.execute(
        text(
            "INSERT INTO characters (id, project_id, slug, name)"
            " VALUES (:id, :project_id, 'guinness', 'Guinness')"
        ),
        {"id": uuid.uuid4(), "project_id": second_project_id},
    )


def test_bible_versions_are_separate_rows(
    conn: Connection,
    project_id: uuid.UUID,
    character_id: uuid.UUID,
    expect_violation: Callable[..., None],
) -> None:
    insert = (
        "INSERT INTO character_bible_versions"
        " (id, project_id, character_id, version, body, sha256)"
        " VALUES (:id, :project_id, :character_id, :version, :body, :sha256)"
    )

    for version in (1, 2):
        conn.execute(
            text(insert),
            {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "character_id": character_id,
                "version": version,
                "body": f"bible v{version}",
                "sha256": _sha(),
            },
        )

    total = conn.execute(
        text("SELECT count(*) FROM character_bible_versions WHERE character_id = :id"),
        {"id": character_id},
    ).scalar_one()
    assert total == 2

    expect_violation(
        insert,
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "character_id": character_id,
            "version": 1,
            "body": "duplicate",
            "sha256": _sha(),
        },
        "uq_bible_character_version",
    )


def test_bible_cannot_belong_to_foreign_project(
    conn: Connection,
    second_project_id: uuid.UUID,
    character_id: uuid.UUID,
    expect_violation: Callable[..., None],
) -> None:
    expect_violation(
        "INSERT INTO character_bible_versions"
        " (id, project_id, character_id, version, body, sha256)"
        " VALUES (:id, :project_id, :character_id, 1, 'foreign', :sha256)",
        {
            "id": uuid.uuid4(),
            "project_id": second_project_id,
            "character_id": character_id,
            "sha256": _sha(),
        },
        "fk_bible_character_project",
    )


def test_composition_revisions_are_separate_rows(
    conn: Connection,
    project_id: uuid.UUID,
    shot_id: uuid.UUID,
    make_composition: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    make_composition(project_id=project_id, shot_id=shot_id, revision=1)
    make_composition(project_id=project_id, shot_id=shot_id, revision=2)

    total = conn.execute(
        text("SELECT count(*) FROM shot_compositions WHERE shot_id = :id"), {"id": shot_id}
    ).scalar_one()
    assert total == 2

    expect_violation(
        "INSERT INTO shot_compositions (id, project_id, shot_id, revision, width, height)"
        " VALUES (:id, :project_id, :shot_id, 1, 512, 512)",
        {"id": uuid.uuid4(), "project_id": project_id, "shot_id": shot_id},
        "uq_shot_compositions_shot_revision",
    )


def test_shot_reference_points_to_concrete_asset(
    conn: Connection,
    project_id: uuid.UUID,
    shot_id: uuid.UUID,
    character_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
) -> None:
    asset = make_asset(
        project_id=project_id, kind="character_reference", character_id=character_id
    )

    conn.execute(
        text(
            "INSERT INTO shot_references"
            " (id, project_id, shot_id, reference_asset_id, purpose)"
            " VALUES (:id, :project_id, :shot_id, :asset, 'character')"
        ),
        {"id": uuid.uuid4(), "project_id": project_id, "shot_id": shot_id, "asset": asset},
    )

    stored = conn.execute(
        text("SELECT reference_asset_id FROM shot_references WHERE shot_id = :id"),
        {"id": shot_id},
    ).scalar_one()
    assert stored == asset
