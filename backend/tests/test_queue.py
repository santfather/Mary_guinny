"""WP-06: очередь, worker API, lease/retry, MP4-проверка, идемпотентность."""

from __future__ import annotations

import hashlib
import struct
import uuid

import pytest
from sqlalchemy import Connection, text

from app.video_probe import VideoProbeError, probe_mp4


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload) + 8) + box_type + payload


def _mvhd(duration: int, timescale: int = 1000) -> bytes:
    payload = (
        b"\x00\x00\x00\x00"
        + b"\x00" * 8
        + struct.pack(">II", timescale, duration)
        + b"\x00" * 64
    )
    return _box(b"mvhd", payload)


def _hdlr(handler: bytes) -> bytes:
    return _box(b"hdlr", b"\x00" * 8 + handler + b"\x00" * 12)


def make_mp4(*, duration_ms: int = 1000, video: bool = True, audio: bool = False) -> bytes:
    """Минимальный ISO BMFF: ftyp + moov(mvhd + trak'и)."""

    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2mp41")
    tracks = b""
    if video:
        tracks += _box(b"trak", _box(b"mdia", _hdlr(b"vide")))
    if audio:
        tracks += _box(b"trak", _box(b"mdia", _hdlr(b"soun")))
    moov = _box(b"moov", _mvhd(duration_ms) + tracks)
    return ftyp + moov


def _token(client) -> dict[str, str]:
    return {"X-Worker-Token": client.app.state.settings.worker_token}


def _approve_keyframe(
    api_client, project_id, shot_id, character_id, location_id, make_png_reference
):
    """Готовит approved-композицию и promoted-keyframe для шота."""

    character_ref = make_png_reference(project_id=project_id, character_id=character_id)
    location_ref = make_png_reference(project_id=project_id, location_id=location_id)
    composition = api_client.post(
        f"/api/shots/{shot_id}/compositions",
        json={
            "width": 64,
            "height": 64,
            "layers": [
                {"reference_asset_id": str(location_ref), "z_index": 0},
                {
                    "reference_asset_id": str(character_ref),
                    "z_index": 1,
                    "x": 8,
                    "y": 8,
                    "scale": 0.5,
                },
            ],
        },
    )
    assert composition.status_code == 201
    assert (
        api_client.post(f"/api/shots/{shot_id}/compositions/1/render").status_code
        == 200
    )
    assert (
        api_client.post(f"/api/shots/{shot_id}/compositions/1/approve").status_code
        == 200
    )
    keyframe = api_client.post(f"/api/shots/{shot_id}/keyframe", json={})
    assert keyframe.status_code == 201
    payload = keyframe.json()
    promoted = api_client.post(
        f"/api/shots/{shot_id}/attempts/{payload['attempt_id']}/promote-keyframe"
    )
    assert promoted.status_code == 200
    return payload


def _queue(api_client, shot_id, headers: dict[str, str] | None = None) -> dict:
    queued = api_client.post(f"/api/shots/{shot_id}/render", headers=headers or {})
    assert queued.status_code == 202
    return queued.json()


def _events(conn: Connection, job_id) -> list[str]:
    return [
        row[0]
        for row in conn.execute(
            text("SELECT event FROM events WHERE job_id = :id ORDER BY sequence"),
            {"id": job_id},
        )
    ]


def _freeze_other_jobs(conn: Connection) -> None:
    """Снимает с очереди job'ы, оставшиеся от ручных прогонов (откатится с транзакцией)."""

    conn.execute(
        text(
            "UPDATE jobs SET status = 'cancel_requested'"
            " WHERE status IN ('pending','retry_wait','leased','running','lease_expired')"
        )
    )


def test_probe_mp4_accepts_valid_and_rejects_broken() -> None:
    info = probe_mp4(make_mp4(duration_ms=1500))
    assert info.has_video is True
    assert info.has_audio is False
    assert info.duration_s == pytest.approx(1.5)

    with_audio = probe_mp4(make_mp4(audio=True))
    assert with_audio.has_audio is True

    with pytest.raises(VideoProbeError, match="no video track"):
        probe_mp4(make_mp4(video=False))
    with pytest.raises(VideoProbeError, match="duration is zero"):
        probe_mp4(make_mp4(duration_ms=0))
    with pytest.raises(VideoProbeError):
        probe_mp4(b"not an mp4 at all")
    with pytest.raises(VideoProbeError, match="missing ftyp"):
        probe_mp4(_box(b"moov", _mvhd(1000)))
    with pytest.raises(VideoProbeError, match="empty file"):
        probe_mp4(b"")


def test_worker_token_is_required(api_client) -> None:
    body = {"worker_name": "worker-a"}
    assert api_client.post("/api/worker/claim", json=body).status_code == 401
    assert (
        api_client.post(
            "/api/worker/claim", json=body, headers={"X-Worker-Token": "wrong"}
        ).status_code
        == 401
    )

    settings = api_client.app.state.settings
    original = settings.worker_token
    settings.worker_token = ""
    try:
        disabled = api_client.post(
            "/api/worker/claim", json=body, headers={"X-Worker-Token": "anything"}
        )
        assert disabled.status_code == 503
    finally:
        settings.worker_token = original

    bearer = api_client.post(
        "/api/worker/claim",
        json=body,
        headers={"Authorization": f"Bearer {original}"},
    )
    assert bearer.status_code == 200


def test_claim_heartbeat_upload_and_complete(
    api_client,
    conn: Connection,
    project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
) -> None:
    keyframe = _approve_keyframe(
        api_client, project_id, shot_id, character_id, location_id, make_png_reference
    )
    _freeze_other_jobs(conn)
    job_id = _queue(api_client, shot_id)["job_id"]

    claim = api_client.post(
        "/api/worker/claim",
        json={"worker_name": "worker-a", "lease_seconds": 30},
        headers=_token(api_client),
    )
    assert claim.status_code == 200
    claimed = claim.json()
    assert claimed["job_id"] == job_id
    assert claimed["status"] == "leased"
    assert claimed["attempts"] == 1
    assert claimed["max_attempts"] == 3
    assert claimed["workflow_id"] == "fake_i2v_v1"
    assert claimed["inputs"]["frames"] == 73
    assert claimed["inputs"]["fps"] == 24.0
    assert claimed["inputs"]["start_image"]["artifact_id"] == keyframe["artifact_id"]
    assert claimed["inputs"]["start_image"]["sha256"]
    assert claimed["inputs"]["start_image"]["content_url"].endswith("/content")
    assert claimed["output_prefix"].endswith(f"/attempts/{claimed['attempt_id']}/")

    assert _queue_claim(api_client, "worker-b") is None

    heartbeat = api_client.post(
        f"/api/worker/jobs/{job_id}/heartbeat",
        json={"worker_name": "worker-a", "progress": 0.5, "stage": "sampling"},
        headers=_token(api_client),
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["status"] == "running"
    assert heartbeat.json()["sequence"] == 2

    foreign = api_client.post(
        f"/api/worker/jobs/{job_id}/heartbeat",
        json={"worker_name": "worker-b", "progress": 0.5},
        headers=_token(api_client),
    )
    assert foreign.status_code == 409
    assert foreign.json()["detail"]["error"] == "lease_not_owned"

    url = f"/api/worker/jobs/{job_id}/artifacts?worker_name=worker-a&kind=video"
    broken = b"not an mp4"
    invalid = api_client.post(
        url,
        content=broken,
        headers={
            **_token(api_client),
            "Content-Type": "video/mp4",
            "X-Content-SHA256": hashlib.sha256(broken).hexdigest(),
        },
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["error"] == "invalid_mp4"

    video = make_mp4(duration_ms=1000, audio=True)
    digest = hashlib.sha256(video).hexdigest()
    headers = {
        **_token(api_client),
        "Content-Type": "video/mp4",
        "X-Content-SHA256": digest,
    }
    mismatch = api_client.post(
        url,
        content=video,
        headers={**headers, "X-Content-SHA256": hashlib.sha256(b"other").hexdigest()},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["error"] == "sha256_mismatch"

    upload = api_client.post(url, content=video, headers=headers)
    assert upload.status_code == 201
    repeat = api_client.post(url, content=video, headers=headers)
    assert repeat.status_code == 201
    assert repeat.json()["id"] == upload.json()["id"]
    artifact_id = upload.json()["id"]

    complete = api_client.post(
        f"/api/worker/jobs/{job_id}/complete",
        json={
            "worker_name": "worker-a",
            "duration_s": 1.0,
            "native_fps": 24,
            "parameters": {"width": 576, "height": 1024, "cfg_scale": 3.0},
        },
        headers=_token(api_client),
    )
    assert complete.status_code == 200
    assert complete.json()["status"] == "completed"
    assert complete.json()["artifact_ids"] == [artifact_id]

    job = api_client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert job["lease_until"] is None
    assert job["attempts"] == 1

    assert _events(conn, job_id) == [
        "claimed",
        "progress",
        "artifact_uploaded",
        "completed",
    ]
    attempt = conn.execute(
        text(
            "SELECT status, duration_s, native_fps, parameters"
            " FROM render_attempts WHERE job_id = :id"
        ),
        {"id": job_id},
    ).one()
    assert attempt.status == "completed"
    assert float(attempt.duration_s) == pytest.approx(1.0)
    assert float(attempt.native_fps) == pytest.approx(24.0)
    # Фактические параметры рендера дописываются к параметрам claim.
    assert attempt.parameters == {
        "worker_name": "worker-a",
        "job_attempt": 1,
        "width": 576,
        "height": 1024,
        "cfg_scale": 3.0,
    }


def test_claim_inputs_carry_motion_prompt_and_shot_key(
    api_client,
    conn: Connection,
    project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
) -> None:
    """WP-N3: реальному воркеру нужен prompt из последней motion-ревизии (§5.2)."""

    _approve_keyframe(
        api_client, project_id, shot_id, character_id, location_id, make_png_reference
    )
    conn.execute(
        text(
            "INSERT INTO prompt_revisions"
            " (shot_id, prompt_type, version, prompt, parameters_json)"
            " VALUES (:shot_id, 'motion', 1, :prompt, CAST(:params AS jsonb))"
        ),
        {
            "shot_id": shot_id,
            "prompt": "older prompt",
            "params": '{"shot_key": "NLB-OLD"}',
        },
    )
    conn.execute(
        text(
            "INSERT INTO prompt_revisions"
            " (shot_id, prompt_type, version, prompt, parameters_json)"
            " VALUES (:shot_id, 'motion', 2, :prompt, CAST(:params AS jsonb))"
        ),
        {
            "shot_id": shot_id,
            "prompt": "the cat blinks slowly",
            "params": '{"shot_key": "NLB-01"}',
        },
    )
    _freeze_other_jobs(conn)
    _queue(api_client, shot_id)

    claimed = api_client.post(
        "/api/worker/claim",
        json={"worker_name": "worker-a", "lease_seconds": 30},
        headers=_token(api_client),
    )
    assert claimed.status_code == 200
    inputs = claimed.json()["inputs"]
    assert inputs["prompt"] == "the cat blinks slowly"
    assert inputs["shot_key"] == "NLB-01"


def _queue_claim(api_client, worker_name: str):
    response = api_client.post(
        "/api/worker/claim",
        json={"worker_name": worker_name},
        headers=_token(api_client),
    )
    assert response.status_code == 200
    return response.json()


def test_retry_wait_then_terminal_failure(
    api_client,
    conn: Connection,
    project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
) -> None:
    _approve_keyframe(
        api_client, project_id, shot_id, character_id, location_id, make_png_reference
    )
    _freeze_other_jobs(conn)
    job_id = _queue(api_client, shot_id)["job_id"]
    conn.execute(
        text("UPDATE jobs SET max_attempts = 2 WHERE id = :id"), {"id": job_id}
    )
    assert _queue_claim(api_client, "worker-a")["job_id"] == job_id

    failed = api_client.post(
        f"/api/worker/jobs/{job_id}/fail",
        json={"worker_name": "worker-a", "error_code": "oom", "retryable": True},
        headers=_token(api_client),
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "retry_wait"

    job = api_client.get(f"/api/jobs/{job_id}").json()
    assert job["run_after"] is not None
    # backoff ещё не истёк — job не выдаётся
    assert _queue_claim(api_client, "worker-b") is None

    conn.execute(
        text("UPDATE jobs SET run_after = now() - interval '1 second' WHERE id = :id"),
        {"id": job_id},
    )
    second = _queue_claim(api_client, "worker-b")
    assert second["job_id"] == job_id
    assert second["attempts"] == 2

    terminal = api_client.post(
        f"/api/worker/jobs/{job_id}/fail",
        json={"worker_name": "worker-b", "error_code": "bad_prompt", "retryable": True},
        headers=_token(api_client),
    )
    assert terminal.status_code == 200
    assert terminal.json()["status"] == "failed"

    job = api_client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error_code"] == "bad_prompt"
    assert job["run_after"] is None
    assert _events(conn, job_id) == ["claimed", "failed", "claimed", "failed"]
    assert _queue_claim(api_client, "worker-a") is None


def test_lease_expiry_waits_for_owner_recovery(
    api_client,
    conn: Connection,
    project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
) -> None:
    _approve_keyframe(
        api_client, project_id, shot_id, character_id, location_id, make_png_reference
    )
    _freeze_other_jobs(conn)
    job_id = _queue(api_client, shot_id)["job_id"]
    assert _queue_claim(api_client, "worker-a")["job_id"] == job_id

    conn.execute(
        text("UPDATE jobs SET lease_until = now() - interval '1 minute' WHERE id = :id"),
        {"id": job_id},
    )
    assert _queue_claim(api_client, "worker-b") is None

    job = api_client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "lease_expired"
    assert job["lease_until"] is None
    assert job["lease_owner"] == "worker-a"

    recovered = api_client.post(
        f"/api/worker/jobs/{job_id}/heartbeat",
        json={"worker_name": "worker-a", "progress": 0.7},
        headers=_token(api_client),
    )
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "running"

    foreign = api_client.post(
        f"/api/worker/jobs/{job_id}/heartbeat",
        json={"worker_name": "worker-b"},
        headers=_token(api_client),
    )
    assert foreign.status_code == 409

    no_artifact = api_client.post(
        f"/api/worker/jobs/{job_id}/complete",
        json={"worker_name": "worker-a"},
        headers=_token(api_client),
    )
    assert no_artifact.status_code == 409

    resumed = api_client.post(
        "/api/worker/resume",
        json={"worker_name": "worker-a"},
        headers=_token(api_client),
    )
    assert resumed.status_code == 200
    assert [item["job_id"] for item in resumed.json()["jobs"]] == [job_id]

    events = _events(conn, job_id)
    assert events == ["claimed", "lease_expired", "progress", "resumed"]


def test_scene_scoped_job_is_rejected(api_client, conn: Connection, scene_id) -> None:
    _freeze_other_jobs(conn)
    job_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO jobs (id, kind, scene_id, status)"
            " VALUES (:id, 'render_video', :scene_id, 'pending')"
        ),
        {"id": job_id, "scene_id": scene_id},
    )
    response = api_client.post(
        "/api/worker/claim",
        json={"worker_name": "worker-a"},
        headers=_token(api_client),
    )
    assert response.status_code == 409

    job = api_client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error_code"] == "unsupported_job_target"
    assert _events(conn, job_id) == ["failed"]


def test_render_idempotency_and_render_already_active(
    api_client,
    conn: Connection,
    project_id,
    scene_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
    make_shot,
) -> None:
    _approve_keyframe(
        api_client, project_id, shot_id, character_id, location_id, make_png_reference
    )

    headers = {"Idempotency-Key": "render-abc"}
    first = _queue(api_client, shot_id, headers)
    second = _queue(api_client, shot_id, headers)
    assert first["job_id"] == second["job_id"]

    duplicate = api_client.post(f"/api/shots/{shot_id}/render")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error"] == "render_already_active"

    other_shot = make_shot(scene_id=scene_id, sequence_no=2)
    _approve_keyframe(
        api_client,
        project_id,
        other_shot,
        character_id,
        location_id,
        make_png_reference,
    )
    foreign_key = api_client.post(
        f"/api/shots/{other_shot}/render", headers={"Idempotency-Key": "render-abc"}
    )
    assert foreign_key.status_code == 409
    assert foreign_key.json()["detail"] == "idempotency key belongs to another shot"

    blank = api_client.post(
        f"/api/shots/{other_shot}/render", headers={"Idempotency-Key": "   "}
    )
    assert blank.status_code == 422

    job = api_client.get(f"/api/jobs/{first['job_id']}")
    assert job.status_code == 200
    assert job.json()["status"] == "pending"
    assert api_client.get(f"/api/jobs/{uuid.uuid4()}").status_code == 404

    listed = api_client.get("/api/jobs", params={"status": "pending"}).json()
    assert first["job_id"] in [item["id"] for item in listed]
    assert (
        conn.execute(
            text("SELECT count(*) FROM jobs WHERE shot_id = :id"), {"id": shot_id}
        ).scalar()
        == 1
    )
