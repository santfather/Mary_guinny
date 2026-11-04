"""WP-M5: список попыток проекта (фильтры, пагинация, флаг approved)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Connection, text


def _attempt(
    conn: Connection,
    shot_id: uuid.UUID,
    *,
    kind: str = "video",
    status: str = "completed",
    seed: int = 1,
    created_at: datetime | None = None,
    with_artifact: bool = True,
    parameters: dict[str, object] | None = None,
) -> tuple[uuid.UUID, uuid.UUID | None]:
    """Создаёт attempt (+job для video, +artifact) прямыми INSERT."""

    job_id: uuid.UUID | None = None
    if kind == "video":
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
            "  parameters, created_at)"
            " VALUES (:id, :shot, :job, :kind, :status, 'ltx23-mlx-q4-i2v/test', :seed,"
            "  8.04, CAST(:parameters AS jsonb), :created_at)"
        ),
        {
            "id": attempt_id,
            "shot": shot_id,
            "job": job_id,
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
            "created_at": created_at or datetime.now(timezone.utc),
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
    return attempt_id, artifact_id


def test_project_attempts_empty_page(api_client, project_id) -> None:
    response = api_client.get(f"/api/projects/{project_id}/attempts")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}

    missing = api_client.get(f"/api/projects/{uuid.uuid4()}/attempts")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "project not found"


def test_project_attempts_returns_shot_context_and_parameters(
    api_client, conn: Connection, project_id, scene_id, shot_id
) -> None:
    _, artifact_id = _attempt(conn, shot_id, seed=7)

    payload = api_client.get(f"/api/projects/{project_id}/attempts").json()
    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["shot_id"] == str(shot_id)
    assert item["shot_sequence_no"] == 1
    assert item["scene_id"] == str(scene_id)
    assert item["scene_title"] is None
    assert item["shot_status"] == "draft"
    assert item["approved"] is False
    assert item["artifact_id"] == str(artifact_id)
    assert item["artifact_content_url"] == f"/api/artifacts/{artifact_id}/content"
    assert item["seed"] == 7
    assert item["duration_s"] == 8.04
    # `workflow_snapshot` не выходит наружу — как в карточке шота.
    assert item["render_parameters"] == {
        "width": 576,
        "height": 1024,
        "num_frames": 193,
        "frame_rate": 24,
    }


def test_project_attempts_pagination_is_newest_first(
    api_client, conn: Connection, project_id, shot_id
) -> None:
    for hour, seed in ((1, 11), (2, 22), (3, 33)):
        _attempt(
            conn,
            shot_id,
            seed=seed,
            created_at=datetime(2026, 1, 1, hour, tzinfo=timezone.utc),
        )

    first = api_client.get(f"/api/projects/{project_id}/attempts?limit=2").json()
    assert first["total"] == 3
    assert first["limit"] == 2
    assert first["offset"] == 0
    assert [item["seed"] for item in first["items"]] == [33, 22]

    second = api_client.get(
        f"/api/projects/{project_id}/attempts?limit=2&offset=2"
    ).json()
    assert second["total"] == 3
    assert [item["seed"] for item in second["items"]] == [11]


def test_project_attempts_filters(
    api_client, conn: Connection, project_id, make_scene, make_shot
) -> None:
    scene_one = make_scene(project_id=project_id, sequence_no=1, title="Первая")
    scene_two = make_scene(project_id=project_id, sequence_no=2)
    shot_one = make_shot(scene_id=scene_one, sequence_no=1)
    shot_two = make_shot(scene_id=scene_one, sequence_no=2)
    shot_three = make_shot(scene_id=scene_two, sequence_no=1)

    video_id, _ = _attempt(conn, shot_one, kind="video", seed=1)
    failed_id, _ = _attempt(conn, shot_two, kind="video", status="failed", seed=2)
    keyframe_id, _ = _attempt(conn, shot_three, kind="keyframe", seed=3)

    by_scene = api_client.get(
        f"/api/projects/{project_id}/attempts?scene_id={scene_one}"
    ).json()
    assert {item["id"] for item in by_scene["items"]} == {str(video_id), str(failed_id)}

    by_shot = api_client.get(
        f"/api/projects/{project_id}/attempts?shot_id={shot_two}"
    ).json()
    assert [item["id"] for item in by_shot["items"]] == [str(failed_id)]

    by_kind = api_client.get(f"/api/projects/{project_id}/attempts?kind=keyframe").json()
    assert [item["id"] for item in by_kind["items"]] == [str(keyframe_id)]

    by_status = api_client.get(f"/api/projects/{project_id}/attempts?status=failed").json()
    assert [item["id"] for item in by_status["items"]] == [str(failed_id)]
    assert by_status["items"][0]["shot_sequence_no"] == 2
    assert by_status["items"][0]["scene_title"] == "Первая"


def test_project_attempts_isolated_by_project(
    api_client,
    conn: Connection,
    project_id,
    second_project_id,
    make_scene,
    make_shot,
) -> None:
    foreign_scene = make_scene(project_id=second_project_id, sequence_no=1)
    foreign_shot = make_shot(scene_id=foreign_scene, sequence_no=1)
    _attempt(conn, foreign_shot)

    own = api_client.get(f"/api/projects/{project_id}/attempts").json()
    assert own["total"] == 0

    assert (
        api_client.get(
            f"/api/projects/{project_id}/attempts?scene_id={foreign_scene}"
        ).status_code
        == 404
    )
    assert (
        api_client.get(
            f"/api/projects/{project_id}/attempts?shot_id={foreign_shot}"
        ).status_code
        == 404
    )


def test_project_attempts_validates_filters(api_client, project_id) -> None:
    assert api_client.get(f"/api/projects/{project_id}/attempts?limit=0").status_code == 422
    assert api_client.get(f"/api/projects/{project_id}/attempts?limit=101").status_code == 422
    assert api_client.get(f"/api/projects/{project_id}/attempts?offset=-1").status_code == 422
    assert api_client.get(f"/api/projects/{project_id}/attempts?kind=audio").status_code == 422
    assert (
        api_client.get(f"/api/projects/{project_id}/attempts?status=unknown").status_code
        == 422
    )


def test_project_attempts_marks_approved_attempt(
    api_client, conn: Connection, project_id, shot_id
) -> None:
    first_id, _ = _attempt(conn, shot_id, seed=1)
    second_id, _ = _attempt(conn, shot_id, seed=2)

    approved = api_client.post(f"/api/shots/{shot_id}/attempts/{second_id}/approve")
    assert approved.status_code == 200

    payload = api_client.get(f"/api/projects/{project_id}/attempts").json()
    flags = {item["id"]: item["approved"] for item in payload["items"]}
    assert flags == {str(first_id): False, str(second_id): True}
    assert all(item["shot_status"] == "approved" for item in payload["items"])
