"""WP-VOICE-02: движок `mouth_animation_mvp`, калибровка рта и Talking Preview."""

from __future__ import annotations

import hashlib
import io
import math
import struct
import tempfile
import uuid
import wave
from pathlib import Path

import pytest
from PIL import Image, ImageChops
from sqlalchemy import Connection, text

from app.mouth_animation import (
    LIMITATION,
    MODE,
    MouthAnimationError,
    MouthRegion,
    decode_source_image,
    openness_curve,
    render_frame,
    render_talking_preview,
)
from app.storage import BlobStore
from app.video_probe import probe_mp4

SPEECH = ((0.3, 0.75), (0.95, 1.3))
DURATION = 1.5
FPS = 24


def _wav_bytes(
    segments: tuple[tuple[float, float], ...] = SPEECH,
    *,
    duration: float = DURATION,
    rate: int = 16000,
    amplitude: int = 12000,
) -> bytes:
    frames = bytearray()
    for index in range(int(rate * duration)):
        moment = index / rate
        active = any(start <= moment < end for start, end in segments)
        value = int(amplitude * math.sin(2 * math.pi * 220 * moment)) if active else 0
        frames += struct.pack("<h", value)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def _synth_envelope(duration: float = DURATION) -> list[float]:
    """50 Гц огибающая того же синтетического сигнала (только для тестов)."""

    envelope: list[float] = []
    for index in range(round(duration * 50)):
        moment = index / 50
        envelope.append(
            0.26 if any(start <= moment < end for start, end in SPEECH) else 0.0
        )
    return envelope


def _png_bytes(width: int = 48, height: int = 48) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 80, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_audio(client, shot_id, data: bytes | None = None):
    return client.post(
        f"/api/shots/{shot_id}/audio",
        content=data if data is not None else _wav_bytes(),
        headers={"Content-Type": "audio/wav"},
    )


def _attach(client, shot_id, asset_id, purpose: str = "character"):
    return client.post(
        f"/api/shots/{shot_id}/references",
        json={"reference_asset_id": str(asset_id), "purpose": purpose},
    )


def _approve(client, asset_id) -> None:
    assert client.post(f"/api/reference-assets/{asset_id}/approve").status_code == 200


def _keyframe_artifact(conn: Connection, tmp_path, shot_id) -> uuid.UUID:
    """Стартовый кадр шота без запуска композитора: keyframe-попытка + artifact."""

    blob = BlobStore(tmp_path / "storage").put_bytes(_png_bytes(), suffix=".png")
    attempt_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO render_attempts (id, shot_id, kind, status)"
            " VALUES (:id, :shot_id, 'keyframe', 'completed')"
        ),
        {"id": attempt_id, "shot_id": shot_id},
    )
    conn.execute(
        text(
            "INSERT INTO artifacts"
            " (id, attempt_id, source, kind, storage_key, sha256, bytes, mime_type)"
            " VALUES (:id, :attempt_id, 'attempt', 'keyframe', :storage_key,"
            "  :sha256, :bytes, 'image/png')"
        ),
        {
            "id": artifact_id,
            "attempt_id": attempt_id,
            "storage_key": blob.storage_key,
            "sha256": blob.sha256,
            "bytes": blob.size,
        },
    )
    conn.execute(
        text("UPDATE shots SET start_keyframe_artifact_id = :artifact WHERE id = :shot"),
        {"artifact": artifact_id, "shot": shot_id},
    )
    return artifact_id


def _calibrate(client, shot_id, **source):
    return client.post(
        f"/api/shots/{shot_id}/mouth-calibrations",
        json={**source, "x": 0.4, "y": 0.6, "width": 0.2, "height": 0.12},
    )


# --- Движок: детерминизм, тишина, ограничение кадра -----------------------------


def test_openness_curve_is_silent_in_pauses_and_deterministic() -> None:
    envelope = [0.0] * 10 + [0.4] * 20 + [0.0] * 10 + [0.5] * 20 + [0.0] * 25

    first = openness_curve(envelope, fps=FPS, duration_s=len(envelope) / 50, max_open=0.8)
    second = openness_curve(envelope, fps=FPS, duration_s=len(envelope) / 50, max_open=0.8)

    assert first == second
    assert len(first) == round(len(envelope) / 50 * FPS)
    assert all(value == 0.0 for value in first[:4])
    assert all(value == 0.0 for value in first[-6:])
    assert max(first) <= 0.8
    assert max(first) > 0.3

    silent = openness_curve([0.0] * 50, fps=FPS, duration_s=1.0)
    assert silent == [0.0] * FPS

    empty = openness_curve([], fps=FPS, duration_s=0.5)
    assert empty == [0.0] * round(0.5 * FPS)


def test_openness_curve_closes_mouth_in_short_pause() -> None:
    """WP-VOICE-04: пауза ~0.16 с закрывает рот полностью, а не «дотягивает» release."""

    # 10 Гц: один кадр = 5 отсчётов огибающей = 0.1 с; речь 0.3 с, пауза 0.2 с.
    envelope = [0.5] * 15 + [0.0] * 10 + [0.5] * 15
    curve = openness_curve(envelope, fps=10, duration_s=len(envelope) / 50)

    assert curve[0] > 0.0
    assert curve[3:5] == [0.0, 0.0]
    assert curve[5] > 0.0


def test_render_frame_opens_downward_with_soft_edge() -> None:
    base = Image.new("RGB", (120, 120), (40, 80, 120))
    region = MouthRegion(x=0.4, y=0.4, width=0.2, height=0.1, max_open=1.0)

    opened = render_frame(base, region, 1.0)
    changed = ImageChops.difference(base, opened).getbbox()
    assert changed is not None
    left, top, right, bottom = changed

    mouth_line = (region.y + region.height / 2) * base.height
    # Верх маски на линии рта (плюс небольшое размытие), раскрытие — только вниз.
    assert top >= mouth_line - 5
    assert bottom > top + 4
    assert left > 0 and right < base.width


def test_render_frame_closed_is_identical_and_open_stays_inside_region() -> None:
    base = Image.new("RGB", (120, 90), (40, 80, 120))
    region = MouthRegion(x=0.4, y=0.55, width=0.2, height=0.15, max_open=0.9)

    closed = render_frame(base, region, 0.0)
    assert ImageChops.difference(base, closed).getbbox() is None

    opened = render_frame(base, region, 0.9)
    changed = ImageChops.difference(base, opened).getbbox()
    assert changed is not None
    left, top, right, bottom = changed
    assert left > 0 and top > 0
    assert right < base.width and bottom < base.height
    assert opened.getpixel((0, 0)) == base.getpixel((0, 0))
    assert render_frame(base, region, 0.9).tobytes() == opened.tobytes()


def test_decode_source_image_limits_side_and_keeps_even_size() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (2400, 1200), (10, 20, 30)).save(buffer, format="PNG")

    decoded = decode_source_image(buffer.getvalue(), max_side=1000)

    assert max(decoded.size) == 1000
    assert decoded.width % 2 == 0 and decoded.height % 2 == 0
    assert decoded.mode == "RGB"

    odd = io.BytesIO()
    Image.new("RGB", (101, 51), (10, 20, 30)).save(odd, format="PNG")
    cropped = decode_source_image(odd.getvalue())
    assert cropped.size == (100, 50)

    with pytest.raises(MouthAnimationError) as error:
        decode_source_image(b"")
    assert error.value.code == "source_image_invalid"


def test_region_validation_rejects_out_of_bounds() -> None:
    with pytest.raises(MouthAnimationError) as error:
        MouthRegion(x=0.9, y=0.1, width=0.2, height=0.2).validate()
    assert error.value.code == "mouth_region_out_of_bounds"

    MouthRegion(x=0.0, y=0.0, width=1.0, height=1.0).validate()


def test_render_talking_preview_produces_mp4_with_audio(tmp_path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(_wav_bytes())
    output = tmp_path / "preview.mp4"
    region = MouthRegion(x=0.35, y=0.5, width=0.3, height=0.2)

    info = render_talking_preview(
        _png_bytes(64, 64),
        audio_path,
        _synth_envelope(),
        DURATION,
        region,
        output_path=output,
        fps=FPS,
    )

    assert (info.width, info.height) == (64, 64)
    assert info.fps == FPS
    assert info.frames == round(DURATION * FPS)
    assert info.duration_s == pytest.approx(DURATION, abs=0.12)

    probe = probe_mp4(output.read_bytes())
    assert probe.has_video is True
    assert probe.has_audio is True


# --- Калибровка рта -------------------------------------------------------------


def test_calibration_upsert_list_and_validation(
    api_client, project_id, shot_id, second_project_id, make_png_reference
) -> None:
    reference = make_png_reference(project_id=project_id, status="approved")
    assert _attach(api_client, shot_id, reference).status_code == 201

    created = _calibrate(api_client, shot_id, reference_asset_id=str(reference))
    assert created.status_code == 201
    payload = created.json()
    assert payload["reference_asset_id"] == str(reference)
    assert payload["keyframe_artifact_id"] is None
    assert payload["project_id"] == str(project_id)
    assert payload["max_open"] == pytest.approx(0.8)
    assert payload["sensitivity"] == pytest.approx(1.0)
    assert payload["smoothing"] == pytest.approx(0.5)

    changed = api_client.post(
        f"/api/shots/{shot_id}/mouth-calibrations",
        json={
            "reference_asset_id": str(reference),
            "x": 0.45,
            "y": 0.6,
            "width": 0.2,
            "height": 0.12,
            "max_open": 0.5,
            "sensitivity": 1.4,
        },
    )
    assert changed.status_code == 200
    assert changed.json()["id"] == payload["id"]
    assert changed.json()["max_open"] == pytest.approx(0.5)
    assert changed.json()["sensitivity"] == pytest.approx(1.4)

    listed = api_client.get(f"/api/shots/{shot_id}/mouth-calibrations")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [payload["id"]]
    assert listed.json()[0]["x"] == pytest.approx(0.45)

    base = {"x": 0.4, "y": 0.6, "width": 0.2, "height": 0.12}
    no_source = api_client.post(
        f"/api/shots/{shot_id}/mouth-calibrations", json=base
    )
    assert no_source.status_code == 422

    both_sources = api_client.post(
        f"/api/shots/{shot_id}/mouth-calibrations",
        json={
            **base,
            "reference_asset_id": str(reference),
            "keyframe_artifact_id": str(uuid.uuid4()),
        },
    )
    assert both_sources.status_code == 422

    out_of_bounds = api_client.post(
        f"/api/shots/{shot_id}/mouth-calibrations",
        json={**base, "reference_asset_id": str(reference), "width": 0.9},
    )
    assert out_of_bounds.status_code == 422

    negative = api_client.post(
        f"/api/shots/{shot_id}/mouth-calibrations",
        json={**base, "reference_asset_id": str(reference), "x": -0.1},
    )
    assert negative.status_code == 422

    unlinked = make_png_reference(project_id=project_id, status="approved")
    not_linked = _calibrate(api_client, shot_id, reference_asset_id=str(unlinked))
    assert not_linked.status_code == 409
    assert not_linked.json()["detail"]["error"] == "reference_not_linked"

    foreign = make_png_reference(project_id=second_project_id, status="approved")
    assert _calibrate(api_client, shot_id, reference_asset_id=str(foreign)).status_code == 404
    assert _calibrate(api_client, uuid.uuid4(), reference_asset_id=str(reference)).status_code == 404


def test_calibration_accepts_keyframe_source_and_rejects_foreign(
    api_client, conn: Connection, tmp_path, shot_id
) -> None:
    artifact_id = _keyframe_artifact(conn, tmp_path, shot_id)

    created = _calibrate(api_client, shot_id, keyframe_artifact_id=str(artifact_id))
    assert created.status_code == 201
    assert created.json()["keyframe_artifact_id"] == str(artifact_id)
    assert created.json()["reference_asset_id"] is None

    missing = _calibrate(api_client, shot_id, keyframe_artifact_id=str(uuid.uuid4()))
    assert missing.status_code == 404
    assert missing.json()["detail"] == "keyframe artifact not found"


def test_audio_reference_cannot_be_calibration_source(api_client, shot_id) -> None:
    audio = _upload_audio(api_client, shot_id)
    assert audio.status_code == 201

    response = _calibrate(
        api_client, shot_id, reference_asset_id=audio.json()["reference_asset_id"]
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "source_image_required"


def test_calibration_check_constraints(
    conn: Connection, project_id, shot_id, make_png_reference, expect_violation
) -> None:
    reference = make_png_reference(project_id=project_id, status="approved")
    insert = (
        "INSERT INTO mouth_calibrations"
        " (id, project_id, shot_id, reference_asset_id, keyframe_artifact_id,"
        "  x, y, width, height) VALUES (:id, :project_id, :shot, :reference, NULL,"
        "  :x, 0.6, :width, 0.12)"
    )

    expect_violation(
        "INSERT INTO mouth_calibrations"
        " (id, project_id, shot_id, reference_asset_id, keyframe_artifact_id,"
        "  x, y, width, height) VALUES (:id, :project_id, :shot, NULL, NULL,"
        "  0.4, 0.6, 0.2, 0.12)",
        {"id": uuid.uuid4(), "project_id": project_id, "shot": shot_id},
        "ck_mouth_calibrations_single_source",
    )
    expect_violation(
        insert,
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "shot": shot_id,
            "reference": reference,
            "x": 0.9,
            "width": 0.2,
        },
        "ck_mouth_calibrations_region",
    )

    conn.execute(
        text(
            "INSERT INTO mouth_calibrations"
            " (id, project_id, shot_id, reference_asset_id, x, y, width, height)"
            " VALUES (:id, :project_id, :shot, :reference, 0.4, 0.6, 0.2, 0.12)"
        ),
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "shot": shot_id,
            "reference": reference,
        },
    )
    expect_violation(
        insert,
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "shot": shot_id,
            "reference": reference,
            "x": 0.4,
            "width": 0.2,
        },
        "uq_mouth_calibrations_shot_reference",
    )


def test_preview_endpoints_render_closed_and_open_mouth(
    api_client, project_id, shot_id, make_png_reference
) -> None:
    reference = make_png_reference(project_id=project_id, status="approved", width=64, height=48)
    assert _attach(api_client, shot_id, reference).status_code == 201
    body = {
        "reference_asset_id": str(reference),
        "x": 0.4,
        "y": 0.55,
        "width": 0.2,
        "height": 0.2,
    }

    closed = api_client.post(
        f"/api/shots/{shot_id}/mouth-calibrations/preview", json=body, params={"state": "closed"}
    )
    assert closed.status_code == 200
    assert closed.headers["content-type"] == "image/png"
    assert closed.headers["cache-control"] == "no-store"

    response = api_client.get(f"/api/reference-assets/{reference}/content")
    assert response.status_code == 200
    source = Image.open(io.BytesIO(response.content)).convert("RGB")
    closed_frame = Image.open(io.BytesIO(closed.content)).convert("RGB")
    assert closed_frame.size == source.size
    assert ImageChops.difference(source, closed_frame).getbbox() is None

    opened = api_client.post(
        f"/api/shots/{shot_id}/mouth-calibrations/preview", json=body, params={"state": "open"}
    )
    assert opened.status_code == 200
    opened_frame = Image.open(io.BytesIO(opened.content)).convert("RGB")
    assert opened_frame.size == source.size
    assert ImageChops.difference(source, opened_frame).getbbox() is not None

    assert (
        api_client.post(
            f"/api/shots/{shot_id}/mouth-calibrations/preview",
            json=body,
            params={"state": "half"},
        ).status_code
        == 422
    )


# --- Генерация Talking Preview --------------------------------------------------


def test_generation_is_blocked_without_ready_inputs(
    api_client, conn: Connection, project_id, scene_id, shot_id, make_shot, make_png_reference
) -> None:
    def _post(shot, payload):
        return api_client.post(f"/api/shots/{shot}/mouth-animation", json=payload)

    assert _post(uuid.uuid4(), {}).status_code == 404

    empty_shot = make_shot(scene_id=scene_id, sequence_no=2)
    no_audio = _post(empty_shot, {})
    assert no_audio.status_code == 409
    assert no_audio.json()["detail"]["error"] == "audio_required"

    assert _post(empty_shot, {"source_kind": "video"}).json()["detail"]["error"] == (
        "video_talking_not_supported"
    )
    assert _post(empty_shot, {"audio_asset_id": str(uuid.uuid4())}).status_code == 404

    reference = make_png_reference(project_id=project_id, status="approved")
    assert _attach(api_client, empty_shot, reference).status_code == 201
    audio = _upload_audio(api_client, empty_shot)
    assert audio.status_code == 201
    audio_id = audio.json()["reference_asset_id"]

    draft_audio = _post(
        empty_shot,
        {"reference_asset_id": str(reference), "audio_asset_id": audio_id},
    )
    assert draft_audio.status_code == 409
    assert draft_audio.json()["detail"]["error"] == "audio_not_approved"

    # Неутверждённая запись не становится «выбранной» автоматически.
    not_selected = _post(empty_shot, {"reference_asset_id": str(reference)})
    assert not_selected.status_code == 409
    assert not_selected.json()["detail"]["error"] == "audio_required"

    _approve(api_client, audio_id)
    no_source_shot = make_shot(scene_id=scene_id, sequence_no=3)
    other_audio = _upload_audio(api_client, no_source_shot)
    _approve(api_client, other_audio.json()["reference_asset_id"])
    no_calibration = _post(no_source_shot, {})
    assert no_calibration.status_code == 409
    assert no_calibration.json()["detail"]["error"] == "source_image_required"

    missing_calibration = _post(empty_shot, {"reference_asset_id": str(reference)})
    assert missing_calibration.status_code == 409
    assert missing_calibration.json()["detail"]["error"] == "calibration_required"

    # Чужой аудиоассет (привязан к другому шоту) не принимается.
    foreign_audio = _post(shot_id, {"audio_asset_id": str(audio_id)})
    assert foreign_audio.status_code == 409
    assert foreign_audio.json()["detail"]["error"] == "audio_required"

    video_reference = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO reference_assets"
            " (id, project_id, kind, status, storage_key, sha256, mime_type, approved_at)"
            " VALUES (:id, :project_id, 'uploaded', 'approved', :storage_key,"
            "  :sha256, 'video/mp4', now())"
        ),
        {
            "id": video_reference,
            "project_id": project_id,
            "storage_key": f"blobs/{video_reference.hex[:2]}/{video_reference.hex}.mp4",
            "sha256": video_reference.hex + video_reference.hex,
        },
    )
    video = _post(
        empty_shot,
        {"reference_asset_id": str(video_reference), "audio_asset_id": str(audio_id)},
    )
    assert video.status_code == 409
    assert video.json()["detail"]["error"] == "video_talking_not_supported"

    # Ни одной пустой попытки/job не появилось.
    scope = {"empty": empty_shot, "other": no_source_shot}
    assert (
        conn.execute(
            text(
                "SELECT count(*) FROM render_attempts"
                " WHERE shot_id IN (:empty, :other)"
            ),
            scope,
        ).scalar_one()
        == 0
    )
    assert (
        conn.execute(
            text(
                "SELECT count(*) FROM jobs"
                " WHERE kind = 'mouth_animation' AND shot_id IN (:empty, :other)"
            ),
            scope,
        ).scalar_one()
        == 0
    )


def test_generation_produces_reviewable_talking_preview(
    api_client, conn: Connection, tmp_path, project_id, shot_id, make_png_reference
) -> None:
    reference = make_png_reference(project_id=project_id, status="approved")
    assert _attach(api_client, shot_id, reference).status_code == 201
    audio = _upload_audio(api_client, shot_id)
    audio_id = audio.json()["reference_asset_id"]
    _approve(api_client, audio_id)
    calibration = _calibrate(api_client, shot_id, reference_asset_id=str(reference))
    calibration_id = calibration.json()["id"]

    before = conn.execute(
        text(
            "SELECT status, metadata, approved_at FROM reference_assets WHERE id = :id"
        ),
        {"id": reference},
    ).one()
    before_audio = conn.execute(
        text("SELECT status, metadata FROM reference_assets WHERE id = :id"),
        {"id": audio_id},
    ).one()

    response = api_client.post(
        f"/api/shots/{shot_id}/mouth-animation",
        json={"reference_asset_id": str(reference), "audio_asset_id": audio_id},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["mode"] == MODE
    assert payload["limitation"] == LIMITATION
    assert payload["audio_asset_id"] == audio_id
    assert payload["calibration_id"] == calibration_id
    assert payload["fps"] == FPS
    assert payload["frames"] == round(DURATION * FPS)
    assert payload["duration_s"] == pytest.approx(DURATION, abs=0.12)
    assert (payload["width"], payload["height"]) == (48, 48)
    assert payload["content_url"] == f"/api/artifacts/{payload['artifact_id']}/content"

    # Артефакт результата лежит в существующем content-addressed storage.
    storage_key, sha256, size, mime_type = conn.execute(
        text(
            "SELECT storage_key, sha256, bytes, mime_type FROM artifacts WHERE id = :id"
        ),
        {"id": payload["artifact_id"]},
    ).one()
    assert mime_type == "video/mp4"
    assert size == payload["bytes"]
    assert sha256 == payload["sha256"]
    data = BlobStore(tmp_path / "storage").resolve(storage_key).read_bytes()
    assert hashlib.sha256(data).hexdigest() == sha256
    probe = probe_mp4(data)
    assert probe.has_video is True
    assert probe.has_audio is True

    attempt = api_client.get(f"/api/shots/{shot_id}/attempts").json()
    assert [row["id"] for row in attempt] == [payload["attempt_id"]]
    assert attempt[0]["kind"] == "video"
    assert attempt[0]["status"] == "completed"
    assert attempt[0]["artifact_id"] == payload["artifact_id"]
    assert attempt[0]["render_parameters"]["mode"] == MODE
    assert attempt[0]["render_parameters"]["audio_asset_id"] == audio_id
    assert attempt[0]["render_parameters"]["frames"] == round(DURATION * FPS)

    job = api_client.get(f"/api/jobs/{payload['job_id']}").json()
    assert job["kind"] == "mouth_animation"
    assert job["status"] == "completed"
    assert job["shot_id"] == str(shot_id)

    # Автоматического утверждения нет: результат ждёт решения человека.
    assert api_client.get(f"/api/shots/{shot_id}").json()["approved_attempt_id"] is None

    # Approved-референс и аудиозапись не изменились.
    after = conn.execute(
        text(
            "SELECT status, metadata, approved_at FROM reference_assets WHERE id = :id"
        ),
        {"id": reference},
    ).one()
    assert tuple(after) == tuple(before)
    after_audio = conn.execute(
        text("SELECT status, metadata FROM reference_assets WHERE id = :id"),
        {"id": audio_id},
    ).one()
    assert tuple(after_audio) == tuple(before_audio)

    approved = api_client.post(
        f"/api/shots/{shot_id}/attempts/{payload['attempt_id']}/approve"
    )
    assert approved.status_code == 200
    assert approved.json()["approved_attempt_id"] == payload["attempt_id"]
    assert approved.json()["status"] == "approved"

    rejected = api_client.post(
        f"/api/shots/{shot_id}/attempts/{payload['attempt_id']}/reject"
    )
    assert rejected.status_code == 200
    assert rejected.json()["approved_attempt_id"] is None
    assert rejected.json()["status"] == "changes_requested"


def test_generation_uses_saved_calibration_and_keyframe_source(
    api_client, conn: Connection, tmp_path, project_id, shot_id, make_reference
) -> None:
    artifact_id = _keyframe_artifact(conn, tmp_path, shot_id)
    audio = _upload_audio(api_client, shot_id)
    audio_id = audio.json()["reference_asset_id"]
    _approve(api_client, audio_id)
    calibration = _calibrate(
        api_client, shot_id, keyframe_artifact_id=str(artifact_id)
    )
    assert calibration.status_code == 201

    response = api_client.post(
        f"/api/shots/{shot_id}/mouth-animation",
        json={"audio_asset_id": audio_id, "calibration_id": calibration.json()["id"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["calibration_id"] == calibration.json()["id"]
    attempts = api_client.get(f"/api/shots/{shot_id}/attempts").json()
    parameters = next(
        row["render_parameters"]
        for row in attempts
        if row["id"] == response.json()["attempt_id"]
    )
    assert parameters["mode"] == MODE

    # Калибровка другого источника не подходит к выбранному кадру.
    other_reference = make_reference(project_id=project_id, status="approved")
    assert _attach(api_client, shot_id, other_reference).status_code == 201
    mismatch = api_client.post(
        f"/api/shots/{shot_id}/mouth-animation",
        json={
            "reference_asset_id": str(other_reference),
            "audio_asset_id": audio_id,
            "calibration_id": calibration.json()["id"],
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["error"] == "calibration_source_mismatch"
