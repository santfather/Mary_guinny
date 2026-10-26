"""S15: approved-записи библиотеки неизменяемы и не удаляются."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import Connection, text

BIBLE_INSERT = (
    "INSERT INTO character_bible_versions"
    " (id, project_id, character_id, version, body, sha256)"
    " VALUES (:id, :project_id, :character_id, :version, :body, :sha256)"
)


def _sha() -> str:
    return uuid.uuid4().hex * 2


def _approve(conn: Connection, table: str, row_id: uuid.UUID) -> None:
    conn.execute(
        text(f"UPDATE {table} SET status = 'approved', approved_at = now() WHERE id = :id"),
        {"id": row_id},
    )


def _insert_bible(
    conn: Connection, project_id: uuid.UUID, character_id: uuid.UUID
) -> uuid.UUID:
    bible = uuid.uuid4()
    conn.execute(
        text(BIBLE_INSERT),
        {
            "id": bible,
            "project_id": project_id,
            "character_id": character_id,
            "version": 1,
            "body": "Guinness is a black cat.",
            "sha256": _sha(),
        },
    )
    return bible


def test_approved_asset_content_is_immutable(
    conn: Connection,
    project_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    asset = make_asset(project_id=project_id)
    _approve(conn, "reference_assets", asset)

    expect_violation(
        "UPDATE reference_assets SET storage_key = 'other.png' WHERE id = :id",
        {"id": asset},
        "is immutable",
    )
    expect_violation(
        "UPDATE reference_assets SET view = 'front' WHERE id = :id",
        {"id": asset},
        "is immutable",
    )


def test_approved_asset_cannot_be_deleted(
    conn: Connection,
    project_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    asset = make_asset(project_id=project_id)
    _approve(conn, "reference_assets", asset)

    expect_violation(
        "DELETE FROM reference_assets WHERE id = :id", {"id": asset}, "cannot be deleted"
    )


def test_approved_asset_allows_only_revocation(
    conn: Connection,
    project_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    superseded = make_asset(project_id=project_id)
    _approve(conn, "reference_assets", superseded)
    conn.execute(
        text("UPDATE reference_assets SET status = 'superseded' WHERE id = :id"),
        {"id": superseded},
    )
    status = conn.execute(
        text("SELECT status FROM reference_assets WHERE id = :id"), {"id": superseded}
    ).scalar_one()
    assert status == "superseded"

    rejected = make_asset(project_id=project_id)
    _approve(conn, "reference_assets", rejected)
    conn.execute(
        text("UPDATE reference_assets SET status = 'rejected' WHERE id = :id"),
        {"id": rejected},
    )

    unchanged = make_asset(project_id=project_id)
    _approve(conn, "reference_assets", unchanged)
    expect_violation(
        "UPDATE reference_assets SET status = 'approved' WHERE id = :id",
        {"id": unchanged},
        "allows only status superseded/rejected",
    )


def test_draft_asset_stays_editable(
    conn: Connection,
    project_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
) -> None:
    asset = make_asset(project_id=project_id)

    conn.execute(
        text("UPDATE reference_assets SET storage_key = 'renamed.png' WHERE id = :id"),
        {"id": asset},
    )
    conn.execute(text("DELETE FROM reference_assets WHERE id = :id"), {"id": asset})


def test_approved_requires_approved_at(
    conn: Connection,
    project_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    asset = make_asset(project_id=project_id)

    expect_violation(
        "UPDATE reference_assets SET status = 'approved' WHERE id = :id",
        {"id": asset},
        "ck_reference_assets_approved_at",
    )


def test_approved_bible_is_immutable(
    conn: Connection,
    project_id: uuid.UUID,
    character_id: uuid.UUID,
    expect_violation: Callable[..., None],
) -> None:
    bible = _insert_bible(conn, project_id, character_id)
    _approve(conn, "character_bible_versions", bible)

    expect_violation(
        "UPDATE character_bible_versions SET body = 'rewritten' WHERE id = :id",
        {"id": bible},
        "is immutable",
    )
    expect_violation(
        "DELETE FROM character_bible_versions WHERE id = :id",
        {"id": bible},
        "cannot be deleted",
    )

    conn.execute(
        text("UPDATE character_bible_versions SET status = 'superseded' WHERE id = :id"),
        {"id": bible},
    )


def test_approved_composition_is_immutable(
    conn: Connection,
    project_id: uuid.UUID,
    shot_id: uuid.UUID,
    make_composition: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    composition = make_composition(project_id=project_id, shot_id=shot_id)
    _approve(conn, "shot_compositions", composition)

    expect_violation(
        "UPDATE shot_compositions SET width = 1024 WHERE id = :id",
        {"id": composition},
        "is immutable",
    )
    expect_violation(
        "DELETE FROM shot_compositions WHERE id = :id",
        {"id": composition},
        "cannot be deleted",
    )

    conn.execute(
        text("UPDATE shot_compositions SET status = 'superseded' WHERE id = :id"),
        {"id": composition},
    )
