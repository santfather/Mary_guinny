"""WP-M1: ревью видео-попытки и журнал событий job."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import Connection, text


def _video_attempt(
    conn: Connection,
    shot_id: uuid.UUID,
    *,
    kind: str = "video",
    status: str = "completed",
    with_artifact: bool = True,
    seed: int | None = 1234,
    parameters: dict[str, object] | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID | None]:
    """Создаёт job + attempt (+artifact) прямыми INSERT: проверяем API ревью."""

    job_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO jobs (id, kind, shot_id, status)"
            " VALUES (:id, 'render_video', :shot, 'completed')"
        ),
        {"id": job_id, "shot": shot_id},
    )
    attempt_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO render_attempts"
            " (id, shot_id, job_id, kind, status, workflow_version, seed, duration_s,"
            "  parameters)"
            " VALUES (:id, :shot, :job, :kind, :status, 'ltx23-mlx-q4-i2v/test', :seed,"
            "  8.04, CAST(:parameters AS jsonb))"
        ),
        {
            "id": attempt_id,
            "shot": shot_id,
            "job": job_id if kind == "video" else None,
            "kind": kind,
            "status": status,
            "seed": seed,
            "parameters": json.dumps(
                parameters
                if parameters is not None
                else {
                    "width": 576,
                    "height": 1024,
                    "num_frames": 193,
                    "frame_rate": 24,
                    "workflow_snapshot": {"1": {"class_type": "LTX2MLXGenerate"}},
                }
            ),
        },
    )
    artifact_id: uuid.UUID | None = None
    if with_artifact:
        artifact_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO artifacts"
                " (id, attempt_id, source, kind, storage_key, sha256, bytes, mime_type)"
                " VALUES (:id, :attempt, 'attempt', 'video', :key, :sha, 1024,"
                "  'video/mp4')"
            ),
            {
                "id": artifact_id,
                "attempt": attempt_id,
                "key": f"blobs/{artifact_id.hex[:2]}/{artifact_id.hex}.mp4",
                "sha": uuid.uuid4().hex + uuid.uuid4().hex,
            },
        )
    return job_id, attempt_id, artifact_id


def _events(conn: Connection, job_id: uuid.UUID) -> None:
    for sequence, progress in ((1, 0.05), (2, 0.4), (3, 0.9)):
        conn.execute(
            text(
                "INSERT INTO events"
                " (id, job_id, event, stage, progress, sequence, payload)"
                " VALUES (:id, :job, 'progress', 'sampling', :progress, :sequence,"
                "  CAST(:payload AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "job": job_id,
                "progress": progress,
                "sequence": sequence,
                "payload": json.dumps({"poll": sequence}),
            },
        )


def test_approve_video_attempt_sets_pointer_once(
    api_client, conn: Connection, shot_id
) -> None:
    job_id, attempt_id, artifact_id = _video_attempt(conn, shot_id)

    detail = api_client.get(f"/api/shots/{shot_id}").json()
    assert detail["approved_attempt_id"] is None
    assert detail["start_keyframe_artifact_id"] is None

    approved = api_client.post(f"/api/shots/{shot_id}/attempts/{attempt_id}/approve")
    assert approved.status_code == 200
    payload = approved.json()
    assert payload["status"] == "approved"
    assert payload["approved_attempt_id"] == str(attempt_id)
    # S9: ревью не назначает стартовый кадр.
    assert payload["start_keyframe_artifact_id"] is None

    repeated = api_client.post(f"/api/shots/{shot_id}/attempts/{attempt_id}/approve")
    assert repeated.status_code == 200
    assert repeated.json()["approved_attempt_id"] == str(attempt_id)

    detail = api_client.get(f"/api/shots/{shot_id}").json()
    assert detail["approved_attempt_id"] == str(attempt_id)
    assert detail["status"] == "approved"
    attempt = next(item for item in detail["attempts"] if item["id"] == str(attempt_id))
    assert attempt["job_id"] == str(job_id)
    assert attempt["artifact_id"] == str(artifact_id)
    assert attempt["seed"] == 1234
    assert attempt["duration_s"] == 8.04
    assert attempt["workflow_version"] == "ltx23-mlx-q4-i2v/test"
    assert attempt["render_parameters"] == {
        "width": 576,
        "height": 1024,
        "num_frames": 193,
        "frame_rate": 24,
    }


def test_approve_guards_reject_invalid_attempts(api_client, conn: Connection, shot_id) -> None:
    _, keyframe_id, _ = _video_attempt(conn, shot_id, kind="keyframe")
    _, running_id, _ = _video_attempt(conn, shot_id, status="running")
    _, no_artifact_id, _ = _video_attempt(conn, shot_id, with_artifact=False)

    assert (
        api_client.post(f"/api/shots/{shot_id}/attempts/{keyframe_id}/approve").status_code
        == 409
    )
    running = api_client.post(f"/api/shots/{shot_id}/attempts/{running_id}/approve")
    assert running.status_code == 409
    assert "completed" in running.json()["detail"]
    missing = api_client.post(f"/api/shots/{shot_id}/attempts/{no_artifact_id}/approve")
    assert missing.status_code == 409
    assert "artifact" in missing.json()["detail"]

    assert (
        api_client.post(f"/api/shots/{shot_id}/attempts/{uuid.uuid4()}/approve").status_code
        == 404
    )
    assert api_client.get(f"/api/shots/{uuid.uuid4()}").status_code == 404


def test_approve_rejects_attempt_of_another_shot(
    api_client, conn: Connection, scene_id, make_shot
) -> None:
    first = make_shot(scene_id=scene_id, sequence_no=1)
    second = make_shot(scene_id=scene_id, sequence_no=2)
    _, foreign_attempt, _ = _video_attempt(conn, second)

    response = api_client.post(f"/api/shots/{first}/attempts/{foreign_attempt}/approve")
    assert response.status_code == 404
    assert response.json()["detail"] == "render attempt not found"


def test_reject_attempt_keeps_history_and_clears_approval(
    api_client, conn: Connection, shot_id
) -> None:
    _, first_id, _ = _video_attempt(conn, shot_id)
    _, second_id, second_artifact = _video_attempt(conn, shot_id, seed=99)

    # Отклонение неутверждённой попытки не трогает указатель другой попытки.
    assert (
        api_client.post(f"/api/shots/{shot_id}/attempts/{first_id}/approve").status_code
        == 200
    )
    rejected_other = api_client.post(f"/api/shots/{shot_id}/attempts/{second_id}/reject")
    assert rejected_other.status_code == 200
    assert rejected_other.json()["approved_attempt_id"] == str(first_id)
    assert rejected_other.json()["status"] == "changes_requested"

    rejected = api_client.post(f"/api/shots/{shot_id}/attempts/{first_id}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["approved_attempt_id"] is None
    assert rejected.json()["status"] == "changes_requested"

    repeated = api_client.post(f"/api/shots/{shot_id}/attempts/{first_id}/reject")
    assert repeated.status_code == 200
    assert repeated.json()["approved_attempt_id"] is None

    detail = api_client.get(f"/api/shots/{shot_id}").json()
    assert {item["id"] for item in detail["attempts"]} == {str(first_id), str(second_id)}
    assert (
        conn.execute(
            text("SELECT count(*) FROM artifacts WHERE attempt_id IN (:a, :b)"),
            {"a": first_id, "b": second_id},
        ).scalar_one()
        == 2
    )
    assert second_artifact is not None


def test_job_detail_and_events_journal(api_client, conn: Connection, shot_id) -> None:
    job_id, _, _ = _video_attempt(conn, shot_id)
    _events(conn, job_id)

    events = api_client.get(f"/api/jobs/{job_id}/events")
    assert events.status_code == 200
    payload = events.json()
    assert [item["sequence"] for item in payload] == [1, 2, 3]
    assert [item["progress"] for item in payload] == [0.05, 0.4, 0.9]
    assert payload[0]["stage"] == "sampling"
    assert payload[0]["payload"] == {"poll": 1}

    last = api_client.get(f"/api/jobs/{job_id}/events?limit=1")
    assert last.status_code == 200
    assert [item["sequence"] for item in last.json()] == [3]

    detail = api_client.get(f"/api/jobs/{job_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "completed"
    assert body["last_event"]["sequence"] == 3
    assert body["last_event"]["progress"] == 0.9

    empty = api_client.post(f"/api/shots/{shot_id}/render")
    assert empty.status_code == 409  # нет стартового кадра — job не создан
    assert api_client.get(f"/api/jobs/{uuid.uuid4()}/events").status_code == 404
    assert api_client.get(f"/api/jobs/{uuid.uuid4()}").status_code == 404
