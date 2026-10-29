from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.set_shot_prompts import PROMPTS, set_shot_prompts


def _seed(conn, sequences: tuple[int, ...] = (21, 22)) -> tuple[uuid.UUID, str]:
    """Изолирует тест от реального проекта: title уникален в пределах транзакции."""

    project_id = uuid.uuid4()
    title = f"NLB {project_id.hex}"
    scene_id = uuid.uuid4()
    conn.execute(
        text("INSERT INTO projects (id, title) VALUES (:id, :title)"),
        {"id": project_id, "title": title},
    )
    conn.execute(
        text(
            "INSERT INTO scenes (id, project_id, sequence_no, title)"
            " VALUES (:id, :project_id, 1, 'Ночной тыгыдык')"
        ),
        {"id": scene_id, "project_id": project_id},
    )
    for sequence_no in sequences:
        shot_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO shots (id, scene_id, sequence_no)"
                " VALUES (:id, :scene_id, :sequence_no)"
            ),
            {"id": shot_id, "scene_id": scene_id, "sequence_no": sequence_no},
        )
        conn.execute(
            text(
                "INSERT INTO prompt_revisions"
                " (id, shot_id, prompt_type, version, prompt, parameters_json)"
                " VALUES (:id, :shot_id, 'motion', 1, 'old prompt',"
                " CAST(:parameters AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "shot_id": shot_id,
                "parameters": f'{{"shot_key": "NLB-{sequence_no:02d}"}}',
            },
        )
    return project_id, title


def _revisions(conn, title: str) -> dict[int, list[tuple[int, str, dict]]]:
    rows = conn.execute(
        text(
            "SELECT s.sequence_no, pr.version, pr.prompt, pr.parameters_json"
            " FROM prompt_revisions pr"
            " JOIN shots s ON s.id = pr.shot_id"
            " JOIN scenes sc ON sc.id = s.scene_id"
            " JOIN projects p ON p.id = sc.project_id"
            " WHERE p.title = :title AND pr.prompt_type = 'motion'"
            " ORDER BY s.sequence_no, pr.version"
        ),
        {"title": title},
    )
    grouped: dict[int, list[tuple[int, str, dict]]] = {}
    for sequence_no, version, prompt, parameters in rows.all():
        grouped.setdefault(sequence_no, []).append((version, prompt, parameters))
    return grouped


def test_dry_run_reports_changes_without_writing(conn) -> None:
    _project_id, title = _seed(conn)

    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        changes, skipped = set_shot_prompts(
            session, title, "Ночной тыгыдык", {21: PROMPTS[21]}, apply=False
        )

    assert [(change.sequence_no, change.before_version, change.after_version) for change in changes] == [
        (21, 1, 2)
    ]
    assert skipped == []
    assert [row[0] for row in _revisions(conn, title)[21]] == [1]


def test_apply_adds_new_revision_and_is_idempotent(conn) -> None:
    _project_id, title = _seed(conn)

    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        changes, _ = set_shot_prompts(
            session, title, "Ночной тыгыдык", {21: PROMPTS[21], 22: PROMPTS[22]}, apply=True
        )
    assert len(changes) == 2

    revisions = _revisions(conn, title)
    assert [row[0] for row in revisions[21]] == [1, 2]
    assert revisions[21][-1][1] == PROMPTS[21]
    assert revisions[21][-1][2]["shot_key"] == "NLB-21"
    assert revisions[21][-1][2]["source"] == "human_prompt_override"
    assert revisions[21][-1][2]["previous_version"] == 1
    assert revisions[21][0][1] == "old prompt"

    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        changes, skipped = set_shot_prompts(
            session, title, "Ночной тыгыдык", {21: PROMPTS[21]}, apply=True
        )
    assert changes == []
    assert skipped == ["NLB-21: already motion v2"]


def test_missing_shot_is_reported(conn) -> None:
    _project_id, title = _seed(conn)

    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        changes, skipped = set_shot_prompts(
            session, title, "Ночной тыгыдык", {99: PROMPTS[21]}, apply=False
        )

    assert changes == []
    assert skipped == ["NLB-99: shot not found"]


def test_unknown_project_and_scene_raise(conn) -> None:
    _project_id, title = _seed(conn)
    with Session(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
        with pytest.raises(LookupError, match="project not found"):
            set_shot_prompts(session, "Unknown", "Ночной тыгыдык", {}, apply=False)
        with pytest.raises(LookupError, match="scene not found"):
            set_shot_prompts(session, title, "Unknown", {}, apply=False)
