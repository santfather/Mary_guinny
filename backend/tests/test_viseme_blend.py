"""WP-VOICE-06: viseme-набор, проверка совместимости и движок `viseme_frame_blend_v1`."""

from __future__ import annotations

import io
import math
import struct
import uuid
import wave
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import Connection, text

from app.mouth_animation import MouthRegion
from app import rhubarb
from app.rhubarb import (
    RhubarbError,
    check_pauses,
    parse_output,
    verify_binary,
)
from app.viseme_assets import (
    VISEME_STATES,
    check_compatibility,
    comparison_sheet,
    decode_image,
)
from app.viseme_blend import (
    MODE,
    VisemeSpan,
    check_timing_bounds,
    frame_mixes,
    frame_targets,
    parse_timings,
    render_blend_preview,
)
from app.video_probe import probe_mp4

FPS = 24
DURATION = 1.5
BASE_COLOR = (40, 80, 120)
REGION = MouthRegion(x=0.4, y=0.6, width=0.2, height=0.12)
# Пиксельный прямоугольник области рта на кадре 120×160.
MOUTH_BOX = (48, 96, 72, 115)


def _scene_png(
    *,
    mouth: str | None = None,
    size: tuple[int, int] = (120, 160),
    noise: bool = True,
) -> bytes:
    """Кадр-заготовка: фон и одна форма рта внутри области калибровки."""

    image = Image.new("RGB", size, BASE_COLOR)
    draw = ImageDraw.Draw(image)
    # Постоянные черты головы вне области морды: по ним проверяется сдвиг головы.
    draw.ellipse((26, 34, 44, 52), fill=(235, 230, 220))
    draw.ellipse((76, 34, 94, 52), fill=(235, 230, 220))
    draw.ellipse((33, 40, 37, 44), fill=(20, 20, 20))
    draw.ellipse((83, 40, 87, 44), fill=(20, 20, 20))
    draw.ellipse((54, 70, 66, 82), fill=(150, 90, 80))
    draw.line((18, 88, 48, 92), fill=(220, 220, 210), width=1)
    draw.line((72, 92, 102, 88), fill=(220, 220, 210), width=1)
    if mouth == "closed":
        draw.line((50, 106, 70, 106), fill=(90, 40, 30), width=2)
    elif mouth == "small_open":
        draw.rectangle((52, 102, 68, 107), fill=(30, 14, 18))
    elif mouth == "medium_open":
        draw.rectangle((52, 102, 68, 112), fill=(30, 14, 18))
    elif mouth == "wide_open":
        draw.rectangle((51, 102, 69, 118), fill=(30, 14, 18))
    elif mouth == "rounded":
        draw.ellipse((55, 102, 66, 111), fill=(30, 14, 18))
    elif mouth == "corner":
        # Рот закрыт как в источнике, но вне морды есть чужое пятно.
        draw.line((50, 106, 70, 106), fill=(90, 40, 30), width=2)
        draw.rectangle((0, 0, 40, 40), fill=(250, 250, 250))
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="PNG",
        pnginfo=_png_nonce() if noise else None,
    )
    return buffer.getvalue()


def _png_nonce():
    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("nonce", uuid.uuid4().hex)
    return info


def _variants() -> dict[str, bytes]:
    return {
        "closed": _scene_png(mouth="closed"),
        "small_open": _scene_png(mouth="small_open"),
        "medium_open": _scene_png(mouth="medium_open"),
        "wide_open": _scene_png(mouth="wide_open"),
        "rounded": _scene_png(mouth="rounded"),
    }


def _wav_bytes(
    segments: tuple[tuple[float, float], ...] = ((0.3, 0.75), (0.95, 1.3)),
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


def _timing() -> list[VisemeSpan]:
    return [
        VisemeSpan(0.0, 0.3, "closed"),
        VisemeSpan(0.3, 0.75, "medium_open"),
        VisemeSpan(0.75, 0.95, "closed"),
        VisemeSpan(0.95, 1.3, "wide_open"),
        VisemeSpan(1.3, 1.5, "rounded"),
    ]


# --- Тайминги -------------------------------------------------------------------


def test_parse_timings_accepts_rhubarb_like_json() -> None:
    spans = parse_timings(
        {
            "visemes": [
                {"start_s": 0.0, "end_s": 0.2, "state": "closed"},
                {"start": 0.2, "end": 0.4, "viseme": "wide_open"},
            ]
        }
    )
    assert [span.viseme for span in spans] == ["closed", "wide_open"]
    assert spans[1].as_metadata() == {"start": 0.2, "end": 0.4, "viseme": "wide_open"}


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        [{"start": 0.0, "end": 0.2, "viseme": "smile"}],
        [{"start": 0.4, "end": 0.2, "viseme": "closed"}],
        [{"start": -0.1, "end": 0.2, "viseme": "closed"}],
        [
            {"start": 0.0, "end": 0.4, "viseme": "closed"},
            {"start": 0.3, "end": 0.6, "viseme": "wide_open"},
        ],
    ],
)
def test_parse_timings_rejects_invalid_payload(payload) -> None:
    with pytest.raises(RhubarbError if False else Exception) as error:
        parse_timings(payload)
    assert getattr(error.value, "code", "") == "viseme_timing_invalid"


def test_timing_bounds_reject_overrun() -> None:
    with pytest.raises(Exception) as error:
        check_timing_bounds([VisemeSpan(0.0, 3.0, "closed")], DURATION)
    assert error.value.code == "viseme_timing_invalid"


# --- Кадры и переходы -----------------------------------------------------------


def test_frame_targets_close_mouth_in_silence_and_drop_short_spans() -> None:
    spans = [
        VisemeSpan(0.0, 0.5, "wide_open"),
        # Короче min_hold_ms: такой визем не должен дёргать рот.
        VisemeSpan(0.5, 0.52, "rounded"),
        VisemeSpan(0.52, 1.0, "small_open"),
    ]
    targets = frame_targets(
        spans,
        fps=FPS,
        duration_s=1.0,
        min_hold_ms=60,
        silence_segments=[{"start_s": 0.0, "end_s": 0.25}],
    )
    assert len(targets) == 24
    assert all(state == "closed" for state in targets[:6])
    assert targets[8] == "wide_open"
    assert targets[13] == "small_open"
    assert "rounded" not in targets


def test_frame_mixes_crossfade_the_boundary() -> None:
    targets = ["closed"] * 10 + ["wide_open"] * 10
    mixes = frame_mixes(targets, fps=FPS, blend_ms=60)
    boundary = mixes[9:12]
    assert any(mix.secondary is not None and 0 < mix.mix < 1 for mix in boundary)
    assert mixes[0].primary == "closed" and mixes[0].secondary is None
    assert mixes[-1].primary == "wide_open"


# --- Проверка совместимости ------------------------------------------------------


def test_compatibility_accepts_consistent_set() -> None:
    report = check_compatibility(
        _scene_png(mouth="closed"),
        _variants(),
        REGION,
        statuses={state: "approved" for state in VISEME_STATES},
    )
    assert report.ready is True, report.blockers
    assert report.missing == []
    assert report.metrics["flicker_ratio"] == pytest.approx(0.0)
    assert {row["state"] for row in report.variants} == set(VISEME_STATES)


def test_compatibility_blocks_incomplete_and_unapproved_set() -> None:
    variants = _variants()
    variants.pop("rounded")
    report = check_compatibility(
        _scene_png(mouth="closed"), variants, REGION, statuses={"closed": "draft"}
    )
    codes = {blocker["code"] for blocker in report.blockers}
    assert "viseme_set_incomplete" in codes
    assert "viseme_set_not_approved" in codes
    assert report.missing == ["rounded"]


def test_compatibility_blocks_resolution_and_noise_outside_mouth() -> None:
    variants = _variants()
    variants["wide_open"] = _scene_png(mouth="wide_open", size=(122, 160))
    report = check_compatibility(_scene_png(mouth="closed"), variants, REGION)
    assert "viseme_resolution_mismatch" in {
        blocker["code"] for blocker in report.blockers
    }

    variants = _variants()
    variants["medium_open"] = _scene_png(mouth="corner")
    report = check_compatibility(_scene_png(mouth="closed"), variants, REGION)
    codes = {blocker["code"] for blocker in report.blockers}
    assert "viseme_outside_mouth_changes" in codes
    assert "viseme_no_articulation" in codes


def test_compatibility_blocks_closed_mismatch_and_head_shift() -> None:
    variants = _variants()
    variants["closed"] = _scene_png(mouth="wide_open")
    report = check_compatibility(_scene_png(mouth="closed"), variants, REGION)
    assert "viseme_closed_mismatch" in {b["code"] for b in report.blockers}

    # Сдвиг всей картинки на 6 px: голова «уехала».
    shifted = Image.open(io.BytesIO(_scene_png(mouth="closed")))
    canvas = Image.new("RGB", shifted.size, BASE_COLOR)
    canvas.paste(shifted, (6, 0))
    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    variants = _variants()
    variants["closed"] = buffer.getvalue()
    report = check_compatibility(
        _scene_png(mouth="closed"), variants, REGION, max_shift_px=2
    )
    assert "viseme_head_shift" in {b["code"] for b in report.blockers}


def test_comparison_sheet_is_png_with_all_states() -> None:
    png = comparison_sheet(_scene_png(mouth="closed"), _variants(), REGION)
    image = decode_image(png)
    # Шесть плиток (источник + пять вариантов) в одну горизонтальную полосу.
    assert image.width > image.height * 2


# --- Сборка MP4 ------------------------------------------------------------------


def test_render_blend_preview_produces_mp4_with_audio(tmp_path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(_wav_bytes())
    output = tmp_path / "viseme.mp4"

    info = render_blend_preview(
        _scene_png(mouth="closed"),
        _variants(),
        _timing(),
        DURATION,
        audio_path,
        REGION,
        output_path=output,
        fps=FPS,
    )

    assert (info.width, info.height) == (120, 160)
    assert info.fps == FPS
    assert info.frames == round(DURATION * FPS)
    assert info.duration_s == pytest.approx(DURATION, abs=0.12)

    probe = probe_mp4(output.read_bytes())
    assert probe.has_video is True
    assert probe.has_audio is True


def test_render_blend_preview_rejects_broken_set(tmp_path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(_wav_bytes())
    missing = _variants()
    missing.pop("rounded")

    with pytest.raises(Exception) as error:
        render_blend_preview(
            _scene_png(mouth="closed"),
            missing,
            _timing(),
            DURATION,
            audio_path,
            REGION,
            output_path=tmp_path / "x.mp4",
        )
    assert error.value.code == "viseme_set_incomplete"

    mismatched = _variants()
    mismatched["wide_open"] = _scene_png(mouth="wide_open", size=(122, 160))
    with pytest.raises(Exception) as error:
        render_blend_preview(
            _scene_png(mouth="closed"),
            mismatched,
            _timing(),
            DURATION,
            audio_path,
            REGION,
            output_path=tmp_path / "y.mp4",
        )
    assert error.value.code == "viseme_resolution_mismatch"


# --- Rhubarb (без скачивания) -----------------------------------------------------


def test_rhubarb_status_without_binary(tmp_path) -> None:
    status = verify_binary(configured=tmp_path / "rhubarb")
    assert status.installed is False
    assert status.verified is False
    assert status.reasons[0]["code"] == "rhubarb_not_installed"
    assert status.as_dict()["download_performed"] is False


def _fake_binary(tmp_path: Path, *, res: bool = True) -> Path:
    path = tmp_path / "rhubarb"
    path.write_bytes(b"#!/bin/sh\n")
    path.chmod(0o755)
    if res:
        (tmp_path / "res").mkdir()
    return path


def test_rhubarb_accepts_x86_64_under_rosetta(tmp_path, monkeypatch) -> None:
    path = _fake_binary(tmp_path)
    monkeypatch.setattr(rhubarb.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        rhubarb, "file_architecture", lambda _p: "Mach-O 64-bit executable x86_64"
    )
    monkeypatch.setattr(rhubarb, "rosetta_available", lambda: True)

    status = verify_binary(configured=path, expected_sha256=rhubarb.sha256_of(path))

    assert status.rosetta is True
    assert status.verified is True
    assert status.reasons == []
    assert [note["code"] for note in status.notes] == ["rhubarb_runs_under_rosetta"]


def test_rhubarb_rejects_x86_64_without_rosetta(tmp_path, monkeypatch) -> None:
    path = _fake_binary(tmp_path)
    monkeypatch.setattr(rhubarb.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        rhubarb, "file_architecture", lambda _p: "Mach-O 64-bit executable x86_64"
    )
    monkeypatch.setattr(rhubarb, "rosetta_available", lambda: False)

    status = verify_binary(configured=path, expected_sha256=rhubarb.sha256_of(path))

    assert status.verified is False
    assert [reason["code"] for reason in status.reasons] == [
        "rhubarb_arch_unsupported"
    ]


def test_rhubarb_requires_res_directory(tmp_path, monkeypatch) -> None:
    path = _fake_binary(tmp_path, res=False)
    monkeypatch.setattr(rhubarb.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        rhubarb, "file_architecture", lambda _p: "Mach-O 64-bit executable arm64"
    )

    status = verify_binary(configured=path, expected_sha256=rhubarb.sha256_of(path))

    assert status.verified is False
    assert [reason["code"] for reason in status.reasons] == ["rhubarb_res_missing"]


def test_rhubarb_rejects_unsupported_audio_suffix(tmp_path, monkeypatch) -> None:
    path = _fake_binary(tmp_path)
    monkeypatch.setattr(rhubarb.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        rhubarb, "file_architecture", lambda _p: "Mach-O 64-bit executable arm64"
    )

    with pytest.raises(RhubarbError) as error:
        rhubarb.analyze(
            tmp_path / "voice.mp3",
            configured=path,
            expected_sha256=rhubarb.sha256_of(path),
        )

    assert error.value.code == "rhubarb_input_unsupported"


def test_rhubarb_parse_output_maps_shapes_to_states() -> None:
    spans = parse_output(
        {
            "mouthCues": [
                {"start": 0.0, "end": 0.1, "value": "A"},
                {"start": 0.1, "end": 0.2, "value": "D"},
                {"start": 0.2, "end": 0.3, "value": "X"},
                {"start": 0.3, "end": 0.4, "value": "wide_open"},
            ]
        }
    )
    assert [span["viseme"] for span in spans] == [
        "closed",
        "wide_open",
        "closed",
        "wide_open",
    ]

    with pytest.raises(RhubarbError) as error:
        parse_output({"mouthCues": [{"start": 0.0, "end": 0.1, "value": "?"}]})
    assert error.value.code == "rhubarb_output_invalid"


def test_rhubarb_pause_check_reports_unclosed_pause() -> None:
    warnings = check_pauses(
        [{"start": 0.0, "end": 0.4, "viseme": "wide_open"}],
        [{"start_s": 0.4, "end_s": 0.9}],
    )
    assert warnings and warnings[0]["code"] == "viseme_pause_not_closed"

    assert (
        check_pauses(
            [{"start": 0.4, "end": 0.9, "viseme": "closed"}],
            [{"start_s": 0.4, "end_s": 0.9}],
        )
        == []
    )


# --- API: импорт набора, проверка и генерация --------------------------------------


def _upload_audio(client, shot_id):
    return client.post(
        f"/api/shots/{shot_id}/audio",
        content=_wav_bytes(),
        headers={"Content-Type": "audio/wav"},
    )


def _upload_variant(client, shot_id, state: str, data: bytes):
    return client.post(
        f"/api/shots/{shot_id}/viseme-set/{state}",
        content=data,
        headers={"Content-Type": "image/png"},
    )


def _approve(client, asset_id) -> None:
    assert client.post(f"/api/reference-assets/{asset_id}/approve").status_code == 200


def _prepare_shot(client, conn: Connection, tmp_path: Path, project_id, shot_id):
    """Approved-источник + запись + калибровка: минимальный вход для сборки."""

    from app.storage import BlobStore

    png = _scene_png(mouth="closed")
    blob = BlobStore(tmp_path / "storage").put_bytes(png, suffix=".png")
    asset_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO reference_assets"
            " (id, project_id, kind, status, storage_key, sha256, mime_type,"
            "  width, height, approved_at)"
            " VALUES (:id, :project_id, 'uploaded', 'approved', :storage_key, :sha256,"
            "  'image/png', 120, 160, now())"
        ),
        {
            "id": asset_id,
            "project_id": project_id,
            "storage_key": blob.storage_key,
            "sha256": blob.sha256,
        },
    )
    attached = client.post(
        f"/api/shots/{shot_id}/references",
        json={"reference_asset_id": str(asset_id), "purpose": "character"},
    )
    assert attached.status_code == 201

    audio = _upload_audio(client, shot_id)
    audio_id = audio.json()["reference_asset_id"]
    _approve(client, audio_id)

    calibration = client.post(
        f"/api/shots/{shot_id}/mouth-calibrations",
        json={
            "reference_asset_id": str(asset_id),
            "x": REGION.x,
            "y": REGION.y,
            "width": REGION.width,
            "height": REGION.height,
        },
    )
    assert calibration.status_code == 201
    return asset_id, audio_id, calibration.json()["id"]


def _fill_set(client, shot_id, variants: dict[str, bytes] | None = None) -> dict[str, str]:
    ids = {}
    for state, data in (variants or _variants()).items():
        response = _upload_variant(client, shot_id, state, data)
        assert response.status_code == 201, response.text
        ids[state] = response.json()["reference_asset_id"]
    return ids


def test_viseme_set_upload_report_and_preview(
    api_client, conn: Connection, tmp_path, project_id, shot_id
) -> None:
    asset_id, _audio, calibration_id = _prepare_shot(
        api_client, conn, tmp_path, project_id, shot_id
    )

    empty = api_client.get(f"/api/shots/{shot_id}/viseme-set")
    assert empty.status_code == 200, empty.text
    # closed подставляется из approved-источника неявно.
    assert empty.json()["missing"] == [
        "small_open",
        "medium_open",
        "wide_open",
        "rounded",
    ]
    assert empty.json()["ready"] is False

    images = _variants()
    ids = _fill_set(api_client, shot_id, images)
    report = api_client.get(f"/api/shots/{shot_id}/viseme-set")
    assert report.status_code == 200
    payload = report.json()
    assert payload["calibration_id"] == calibration_id
    assert payload["ready"] is False
    codes = {blocker["code"] for blocker in payload["blockers"]}
    assert "viseme_set_not_approved" in codes
    assert {row["state"] for row in payload["variants"]} == set(VISEME_STATES)

    for state, reference_id in ids.items():
        _approve(api_client, reference_id)

    approved = api_client.get(f"/api/shots/{shot_id}/viseme-set").json()
    assert approved["ready"] is True, approved["blockers"]
    assert approved["missing"] == []
    assert approved["metrics"]["flicker_ratio"] == pytest.approx(0.0)

    preview = api_client.get(approved["preview_url"])
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.headers["cache-control"] == "no-store"

    # Тот же файл в другой роли — конфликт, а не второй ассет.
    duplicate = _upload_variant(api_client, shot_id, "rounded", images["closed"])
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error"] == "duplicate_reference"

    assert (
        _upload_variant(api_client, shot_id, "smile", _variants()["closed"]).status_code
        == 422
    )
    broken = api_client.post(
        f"/api/shots/{shot_id}/viseme-set/wide_open",
        content=b"not an image",
        headers={"Content-Type": "image/png"},
    )
    assert broken.status_code == 422
    assert broken.json()["detail"]["error"] == "viseme_image_invalid"
    assert asset_id  # источник не менялся


def test_viseme_generation_blocked_then_reviewable(
    api_client, conn: Connection, tmp_path, project_id, shot_id
) -> None:
    asset_id, audio_id, calibration_id = _prepare_shot(
        api_client, conn, tmp_path, project_id, shot_id
    )
    body = {
        "engine": "viseme_frame_blend_v1",
        "reference_asset_id": str(asset_id),
        "audio_asset_id": audio_id,
        "calibration_id": calibration_id,
        "timing": [
            {"start": 0.0, "end": 0.3, "viseme": "closed"},
            {"start": 0.3, "end": 0.75, "viseme": "medium_open"},
            {"start": 0.95, "end": 1.3, "viseme": "wide_open"},
            {"start": 1.3, "end": 1.5, "viseme": "rounded"},
        ],
    }

    blocked = api_client.post(f"/api/shots/{shot_id}/mouth-animation", json=body)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"] == "viseme_set_blocked"
    assert "small_open" in blocked.json()["detail"]["missing"]

    ids = _fill_set(api_client, shot_id)
    for reference_id in ids.values():
        _approve(api_client, reference_id)

    no_timing = api_client.post(
        f"/api/shots/{shot_id}/mouth-animation",
        json={**body, "timing": None},
    )
    assert no_timing.status_code == 409
    assert no_timing.json()["detail"]["error"] == "viseme_timing_required"

    bad_timing = api_client.post(
        f"/api/shots/{shot_id}/mouth-animation",
        json={**body, "timing": [{"start": 0.0, "end": 0.0, "viseme": "closed"}]},
    )
    assert bad_timing.status_code == 422
    assert bad_timing.json()["detail"]["error"] == "viseme_timing_invalid"

    missing_reference = api_client.post(
        f"/api/shots/{shot_id}/mouth-animation",
        json={**body, "reference_asset_id": str(uuid.uuid4())},
    )
    assert missing_reference.status_code == 404

    # До успешной сборки попыток нет: блокировки ничего не пишут в БД.
    assert (
        conn.execute(
            text("SELECT count(*) FROM render_attempts WHERE shot_id = :shot"),
            {"shot": shot_id},
        ).scalar_one()
        == 0
    )

    created = api_client.post(f"/api/shots/{shot_id}/mouth-animation", json=body)
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["mode"] == MODE
    assert payload["fps"] == FPS
    assert payload["frames"] == round(DURATION * FPS)
    assert payload["audio_asset_id"] == audio_id
    assert payload["calibration_id"] == calibration_id

    attempts = api_client.get(f"/api/shots/{shot_id}/attempts").json()
    attempt = next(row for row in attempts if row["id"] == payload["attempt_id"])
    assert attempt["kind"] == "video"
    assert attempt["status"] == "completed"
    assert attempt["workflow_version"] == MODE

    # Полный провенанс живёт в render_attempts.parameters (в API — подмножество).
    parameters = conn.execute(
        text("SELECT parameters FROM render_attempts WHERE id = CAST(:id AS uuid)"),
        {"id": payload["attempt_id"]},
    ).scalar_one()
    assert parameters["mode"] == MODE
    assert parameters["engine"] == "viseme_frame_blend_v1"
    assert parameters["timing_source"] == "payload"
    assert len(parameters["timings"]) == 4
    assert set(parameters["viseme_set"]) == set(VISEME_STATES)
    assert parameters["compatibility"]["ready"] is True

    # Автоматического утверждения нет.
    assert api_client.get(f"/api/shots/{shot_id}").json()["approved_attempt_id"] is None

    reviewed = api_client.post(
        f"/api/shots/{shot_id}/attempts/{payload['attempt_id']}/approve"
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["approved_attempt_id"] == payload["attempt_id"]
