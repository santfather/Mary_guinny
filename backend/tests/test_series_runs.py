"""WP-N4: управляемый последовательный прогон серии.

Проверяется только новый слой `app/api/series_runs.py`: таблицы 0007, конечный
автомат прогона и воркерский `POST /api/worker/series/next`. Тяжёлых рендеров нет:
job создаётся в `pending`, дальше тесты двигают её статус напрямую в БД.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import Connection, text


@pytest.fixture(autouse=True)
def _no_banners(monkeypatch: pytest.MonkeyPatch) -> None:
    """Баннеры macOS в тестах не нужны и не должны ничего запускать."""

    monkeypatch.setenv("MARY_DISABLE_NOTIFY", "1")


def _token(client) -> dict[str, str]:
    return {"X-Worker-Token": client.app.state.settings.worker_token}


def _make_shot(
    conn: Connection,
    make_shot,
    scene_id: uuid.UUID,
    *,
    sequence_no: int,
    prompt: str | None = "the cat blinks slowly",
    start_frame: bool = True,
    reference_filename: str | None = None,
) -> uuid.UUID:
    """Шот в нужной степени готовности: стартовый кадр и motion-ревизия."""

    shot_id = make_shot(scene_id=scene_id, sequence_no=sequence_no)
    if start_frame:
        artifact_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO artifacts"
                " (id, source, kind, storage_key, sha256, bytes, mime_type)"
                " VALUES (:id, 'upload', 'keyframe', :key, :sha, 1, 'image/png')"
            ),
            {
                "id": artifact_id,
                "key": f"blobs/{artifact_id.hex}.png",
                "sha": uuid.uuid4().hex + uuid.uuid4().hex,
            },
        )
        conn.execute(
            text("UPDATE shots SET start_keyframe_artifact_id = :artifact WHERE id = :id"),
            {"artifact": artifact_id, "id": shot_id},
        )
    if prompt is not None:
        parameters: dict[str, object] = {"shot_key": f"NLB-{sequence_no:02d}"}
        if reference_filename is not None:
            parameters["reference_filename"] = reference_filename
        conn.execute(
            text(
                "INSERT INTO prompt_revisions (id, shot_id, prompt_type, version, prompt,"
                " parameters_json) VALUES (:id, :shot_id, 'motion', 1, :prompt,"
                " CAST(:parameters AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "shot_id": shot_id,
                "prompt": prompt,
                "parameters": json.dumps(parameters),
            },
        )
    return shot_id


def _create_run(api_client, project_id, body: dict | None = None) -> dict:
    response = api_client.post(
        f"/api/projects/{project_id}/series/runs", json=body or {}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _next(api_client, run_id, worker_name: str = "worker-a") -> dict:
    response = api_client.post(
        "/api/worker/series/next",
        json={"worker_name": worker_name, "run_id": str(run_id)},
        headers=_token(api_client),
    )
    assert response.status_code == 200, response.text
    return response.json()


def _job_status(conn: Connection, job_id: str) -> str:
    return conn.execute(
        text("SELECT status FROM jobs WHERE id = :id"), {"id": job_id}
    ).scalar_one()


def _set_job_status(conn: Connection, job_id: str, status: str) -> None:
    conn.execute(
        text("UPDATE jobs SET status = :status WHERE id = :id"),
        {"status": status, "id": job_id},
    )


def _jobs_for_run(conn: Connection, run_id: str) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            text(
                "SELECT id::text FROM jobs WHERE payload->>'series_run_id' = :run"
                " ORDER BY created_at"
            ),
            {"run": str(run_id)},
        )
    ]


def test_create_run_splits_ready_and_skipped(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    """Готовые шоты — `pending`, неготовые — `skipped` с причиной из данных."""

    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    _make_shot(conn, make_shot, scene_id, sequence_no=2, start_frame=False)
    _make_shot(conn, make_shot, scene_id, sequence_no=3, prompt=None)
    _make_shot(
        conn,
        make_shot,
        scene_id,
        sequence_no=4,
        reference_filename="missing.png",
    )

    run = _create_run(api_client, project_id)

    assert run["status"] == "draft"
    assert run["total_items"] == 4
    assert run["counts"]["pending"] == 1
    assert run["counts"]["skipped"] == 3
    reasons = {item["shot_sequence_no"]: item["error_code"] for item in run["items"]}
    assert reasons == {
        1: None,
        2: "missing_start_frame",
        3: "missing_prompt",
        4: "missing_reference",
    }


def test_create_run_limits_selection_for_gate(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    """Ворота «один калибровочный / два тестовых шота» — через `shot_orders`."""

    for sequence_no in (1, 2, 3):
        _make_shot(conn, make_shot, scene_id, sequence_no=sequence_no)

    run = _create_run(api_client, project_id, {"shot_orders": [2, 3]})

    assert run["total_items"] == 2
    assert [item["shot_sequence_no"] for item in run["items"]] == [2, 3]

    unknown = api_client.post(
        f"/api/projects/{project_id}/series/runs", json={"shot_orders": [99]}
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["unknown_shot_orders"] == [99]


def test_run_title_is_stored_and_returned(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    """WP-08: имя прогона сохраняется и отдаётся в детали и в списке."""

    _make_shot(conn, make_shot, scene_id, sequence_no=1)

    run = _create_run(api_client, project_id, {"title": "NLB-single"})
    assert run["title"] == "NLB-single"

    listing = api_client.get(f"/api/projects/{project_id}/series/runs").json()
    assert [item["title"] for item in listing] == ["NLB-single"]

    unnamed = _create_run(api_client, project_id, {"shot_orders": [1]})
    assert unnamed["title"] is None


def test_runs_are_isolated_by_project(
    api_client,
    conn: Connection,
    project_id,
    second_project_id,
    scene_id,
    make_shot,
) -> None:
    """Прогон проекта A не виден в проекте B, и пустой проект не создаёт прогон."""

    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    run = _create_run(api_client, project_id)

    other = api_client.get(f"/api/projects/{second_project_id}/series/runs")
    assert other.status_code == 200
    assert other.json() == []
    assert api_client.get(f"/api/series/{run['run_id']}").status_code == 200

    empty = api_client.post(f"/api/projects/{second_project_id}/series/runs", json={})
    assert empty.status_code == 409
    assert empty.json()["detail"] == "project has no shots"


def test_start_requires_pending_items(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    _make_shot(conn, make_shot, scene_id, sequence_no=1, start_frame=False)
    run = _create_run(api_client, project_id)

    response = api_client.post(f"/api/series/{run['run_id']}/start")
    assert response.status_code == 409
    assert response.json()["detail"] == "no ready items in this run"


def test_next_creates_one_job_and_is_idempotent_per_item(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    """Один item — одна job: повторный запрос не создаёт вторую тяжёлую job."""

    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    _make_shot(conn, make_shot, scene_id, sequence_no=2)
    run = _create_run(api_client, project_id)
    assert api_client.post(f"/api/series/{run['run_id']}/start").status_code == 200

    first = _next(api_client, run["run_id"])
    assert first["status"] == "queued"
    assert first["order"] == 1
    assert _job_status(conn, first["job_id"]) == "pending"

    again = _next(api_client, run["run_id"])
    assert again["status"] == "running"
    assert again["job_id"] == first["job_id"]

    assert _jobs_for_run(conn, run["run_id"]) == [first["job_id"]]


def test_next_moves_to_following_item_after_completion(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    _make_shot(conn, make_shot, scene_id, sequence_no=2)
    run = _create_run(api_client, project_id)
    api_client.post(f"/api/series/{run['run_id']}/start")

    first = _next(api_client, run["run_id"])
    _set_job_status(conn, first["job_id"], "completed")

    second = _next(api_client, run["run_id"])
    assert second["status"] == "queued"
    assert second["order"] == 2

    detail = api_client.get(f"/api/series/{run['run_id']}").json()
    assert detail["counts"]["completed"] == 1
    assert detail["counts"]["running"] == 1
    assert detail["items"][0]["job_status"] == "completed"


def test_stop_after_current_pauses_without_new_job(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    _make_shot(conn, make_shot, scene_id, sequence_no=2)
    run = _create_run(api_client, project_id)
    api_client.post(f"/api/series/{run['run_id']}/start")
    first = _next(api_client, run["run_id"])

    stopped = api_client.post(f"/api/series/{run['run_id']}/stop-after-current")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopping"

    still_running = _next(api_client, run["run_id"])
    assert still_running["status"] == "running"
    assert still_running["job_id"] == first["job_id"]

    _set_job_status(conn, first["job_id"], "completed")
    paused = _next(api_client, run["run_id"])
    assert paused["status"] == "paused"
    assert paused["reason"] == "stop_after_current"

    detail = api_client.get(f"/api/series/{run['run_id']}").json()
    assert detail["status"] == "paused"
    assert detail["counts"]["completed"] == 1
    assert detail["counts"]["pending"] == 1
    assert len(_jobs_for_run(conn, run["run_id"])) == 1


def test_failed_item_pauses_run_on_stop_on_error(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    _make_shot(conn, make_shot, scene_id, sequence_no=2)
    run = _create_run(api_client, project_id)
    api_client.post(f"/api/series/{run['run_id']}/start")

    first = _next(api_client, run["run_id"])
    _set_job_status(conn, first["job_id"], "failed")

    result = _next(api_client, run["run_id"])
    assert result["status"] == "paused"
    assert result["reason"] == "job_failed"

    detail = api_client.get(f"/api/series/{run['run_id']}").json()
    assert detail["counts"]["failed"] == 1
    assert detail["items"][0]["error_code"] == "job_failed"
    assert detail["finished_at"] is None

    # Продолжение — штатный resume, а не новый job в обход паузы.
    assert api_client.post(f"/api/series/{run['run_id']}/resume").status_code == 200
    second = _next(api_client, run["run_id"])
    assert second["status"] == "queued"
    assert second["order"] == 2


def test_run_completes_when_no_pending_left(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    _make_shot(conn, make_shot, scene_id, sequence_no=2, start_frame=False)
    run = _create_run(api_client, project_id)
    api_client.post(f"/api/series/{run['run_id']}/start")

    first = _next(api_client, run["run_id"])
    _set_job_status(conn, first["job_id"], "completed")

    result = _next(api_client, run["run_id"])
    assert result["status"] == "completed"
    assert result["counts"] == {
        "pending": 0,
        "running": 0,
        "completed": 1,
        "failed": 0,
        "skipped": 1,
    }

    detail = api_client.get(f"/api/series/{run['run_id']}").json()
    assert detail["status"] == "completed"
    assert detail["finished_at"] is not None

    # Завершённый прогон новых job не создаёт.
    assert _next(api_client, run["run_id"])["status"] == "completed"


def test_cancel_skips_pending_and_stops_worker(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    _make_shot(conn, make_shot, scene_id, sequence_no=2)
    run = _create_run(api_client, project_id)
    api_client.post(f"/api/series/{run['run_id']}/start")

    cancelled = api_client.post(f"/api/series/{run['run_id']}/cancel")
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert body["counts"]["skipped"] == 2
    assert {item["error_code"] for item in body["items"]} == {"cancelled"}

    assert _next(api_client, run["run_id"]) == {"status": "cancelled", "job_id": None}
    assert _jobs_for_run(conn, run["run_id"]) == []


def test_pause_resume_and_invalid_transitions(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    run = _create_run(api_client, project_id)
    api_client.post(f"/api/series/{run['run_id']}/start")

    assert api_client.post(f"/api/series/{run['run_id']}/pause").status_code == 200
    duplicate = api_client.post(f"/api/series/{run['run_id']}/pause")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error"] == "invalid_state"

    assert api_client.post(f"/api/series/{run['run_id']}/resume").status_code == 200
    assert api_client.post(f"/api/series/{run['run_id']}/resume").status_code == 409

    # Пауза останавливает выдачу новых job.
    assert api_client.post(f"/api/series/{run['run_id']}/pause").status_code == 200
    assert _next(api_client, run["run_id"]) == {"status": "paused", "job_id": None}
    assert _jobs_for_run(conn, run["run_id"]) == []


def test_series_next_requires_worker_token(
    api_client, project_id
) -> None:
    response = api_client.post("/api/worker/series/next", json={"worker_name": "w"})
    assert response.status_code == 401


def test_series_next_without_run_id_picks_running_run(
    api_client, conn: Connection, project_id, scene_id, make_shot
) -> None:
    """Флаг `--series-run` опционален: воркер может взять единственный running."""

    _make_shot(conn, make_shot, scene_id, sequence_no=1)
    run = _create_run(api_client, project_id)
    api_client.post(f"/api/series/{run['run_id']}/start")

    response = api_client.post(
        "/api/worker/series/next",
        json={"worker_name": "worker-a"},
        headers=_token(api_client),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["job_id"] is not None


def test_series_next_idle_when_no_runs(api_client) -> None:
    response = api_client.post(
        "/api/worker/series/next",
        json={"worker_name": "worker-a"},
        headers=_token(api_client),
    )
    assert response.status_code == 200
    assert response.json() == {"status": "idle", "job_id": None}
