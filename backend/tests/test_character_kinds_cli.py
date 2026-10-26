from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.set_character_kinds import set_character_kinds


def _seed(conn) -> tuple[uuid.UUID, str]:
    """Изолирует тест от реального проекта: title уникален в пределах транзакции."""
    project_id = uuid.uuid4()
    title = f"Mary Studio {project_id.hex}"
    conn.execute(
        text("INSERT INTO projects (id, title) VALUES (:id, :title)"),
        {"id": project_id, "title": title},
    )
    for slug, name in (("guinness", "Guinness"), ("marija", "Marija")):
        conn.execute(
            text(
                "INSERT INTO characters (id, project_id, slug, name, kind)"
                " VALUES (:id, :project_id, :slug, :name, 'other')"
            ),
            {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "slug": slug,
                "name": name,
            },
        )
    return project_id, title


def _kinds(conn, project_id: uuid.UUID) -> dict[str, str]:
    rows = conn.execute(
        text("SELECT slug, kind FROM characters WHERE project_id = :project_id"),
        {"project_id": project_id},
    )
    return dict(rows.all())


def test_dry_run_reports_changes_without_writing(conn) -> None:
    project_id, title = _seed(conn)

    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        changes, skipped = set_character_kinds(
            session,
            title,
            {"guinness": "cat", "marija": "human"},
            apply=False,
        )

    assert [(change.slug, change.before, change.after) for change in changes] == [
        ("guinness", "other", "cat"),
        ("marija", "other", "human"),
    ]
    assert skipped == []
    assert _kinds(conn, project_id) == {"guinness": "other", "marija": "other"}


def test_apply_changes_only_kind_and_is_idempotent(conn) -> None:
    project_id, title = _seed(conn)

    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        changes, _ = set_character_kinds(
            session, title, {"guinness": "cat", "marija": "human"}, apply=True
        )
    assert len(changes) == 2
    assert _kinds(conn, project_id) == {"guinness": "cat", "marija": "human"}

    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        changes, skipped = set_character_kinds(
            session, title, {"guinness": "cat", "marija": "human"}, apply=True
        )
    assert changes == []
    assert skipped == ["guinness: already cat", "marija: already human"]


def test_non_other_kind_requires_manual_review(conn) -> None:
    project_id, title = _seed(conn)
    conn.execute(
        text(
            "UPDATE characters SET kind = 'human'"
            " WHERE slug = 'guinness' AND project_id = :project_id"
        ),
        {"project_id": project_id},
    )

    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        changes, skipped = set_character_kinds(
            session, title, {"guinness": "cat"}, apply=False
        )

    assert changes == []
    assert skipped == ["guinness: kind=human, manual review required"]
    assert _kinds(conn, project_id)["guinness"] == "human"


def test_unknown_project_and_kind_raise(conn) -> None:
    _project_id, title = _seed(conn)
    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(LookupError, match="project not found"):
            set_character_kinds(session, "Unknown", {"guinness": "cat"}, apply=False)
        with pytest.raises(LookupError, match="unsupported character kinds"):
            set_character_kinds(session, title, {"guinness": "dog"}, apply=False)
