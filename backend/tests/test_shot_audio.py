"""WP-VOICE-02: импорт аудио шота, рабочая копия 48 кГц mono, огибающая."""

from __future__ import annotations

import hashlib
import io
import json
import math
import struct
import subprocess
import tempfile
import uuid
import wave
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import Connection, text

from app.api.deps import get_settings
from app.config import Settings
from app.shot_audio import analyse_envelope, waveform_peaks
from app.storage import BlobStore

# Синтетический сигнал: две «реплики» и паузы между ними (только для тестов).
SPEECH = ((0.3, 0.75), (0.95, 1.3))
DURATION = 1.5


def _wav_bytes(
    segments: tuple[tuple[float, float], ...] = SPEECH,
    *,
    duration: float = DURATION,
    rate: int = 16000,
    amplitude: int = 12000,
) -> bytes:
    frames = bytearray()
    total = int(rate * duration)
    for index in range(total):
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


def _transcode(data: bytes, *, suffix: str, args: list[str]) -> bytes:
    with tempfile.TemporaryDirectory(prefix="mary-audio-test-") as workdir:
        source = Path(workdir) / "source.wav"
        source.write_bytes(data)
        target = Path(workdir) / f"target{suffix}"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                *args,
                str(target),
            ],
            check=True,
            capture_output=True,
        )
        return target.read_bytes()


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(client, shot_id, data: bytes, *, mime: str = "audio/wav", headers=None):
    return client.post(
        f"/api/shots/{shot_id}/audio",
        content=data,
        headers={"Content-Type": mime, **(headers or {})},
    )


def _asset_row(conn: Connection, asset_id: str):
    return conn.execute(
        text("SELECT role, status, sha256, metadata FROM reference_assets WHERE id = :id"),
        {"id": asset_id},
    ).one()


def test_import_wav_keeps_original_and_prepares_work_copy(
    api_client, conn: Connection, shot_id, tmp_path
) -> None:
    data = _wav_bytes()

    response = _upload(
        api_client, shot_id, data, headers={"X-Original-Name": "gns05 take 1.wav"}
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "draft"
    assert payload["selected"] is False
    assert payload["sha256"] == hashlib.sha256(data).hexdigest()
    assert payload["duration_s"] == pytest.approx(DURATION, abs=0.05)
    assert payload["sample_rate"] == 16000
    assert payload["channels"] == 1
    assert payload["codec"] == "pcm_s16le"
    assert payload["original_name"] == "gns05 take 1.wav"
    # Рабочая копия приведена к 48 кГц mono, оригинал остаётся 16 кГц.
    assert payload["work_sample_rate"] == 48000
    assert payload["work_channels"] == 1
    assert payload["envelope_rate_hz"] == 50
    assert 0 < payload["speech_ratio"] < 1
    assert payload["speech_segments"]
    assert payload["silence_segments"]

    # Оригинал не перекодируется и не нормализуется.
    content = api_client.get(payload["content_url"])
    assert content.status_code == 200
    assert content.content == data

    role, status, sha256, metadata = _asset_row(conn, payload["reference_asset_id"])
    assert role == "shot_audio"
    assert status == "draft"
    assert sha256 == payload["sha256"]
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    assert metadata["source"] == "upload"
    assert len(metadata["envelope"]) == round(DURATION * 50)

    work_path = BlobStore(tmp_path / "storage").resolve(metadata["work_storage_key"])
    with wave.open(str(work_path), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 48000
        assert handle.getsampwidth() == 2

    purpose = conn.execute(
        text(
            "SELECT purpose FROM shot_references"
            " WHERE shot_id = :shot AND reference_asset_id = :asset"
        ),
        {"shot": shot_id, "asset": payload["reference_asset_id"]},
    ).scalar_one()
    assert purpose == "other"

    listed = api_client.get(f"/api/shots/{shot_id}/audio")
    assert listed.status_code == 200
    assert [item["reference_asset_id"] for item in listed.json()] == [
        payload["reference_asset_id"]
    ]
    assert listed.json()[0]["selected"] is False


@pytest.mark.parametrize(
    ("mime", "suffix", "args", "codec"),
    [
        ("audio/mpeg", ".mp3", ["-vn", "-c:a", "libmp3lame", "-b:a", "128k", "-f", "mp3"], "mp3"),
        ("audio/mp4", ".m4a", ["-vn", "-c:a", "aac", "-b:a", "128k", "-f", "mp4"], "aac"),
        ("audio/aac", ".aac", ["-vn", "-c:a", "aac", "-b:a", "128k", "-f", "adts"], "aac"),
    ],
)
def test_import_mp3_m4a_and_aac(
    api_client, shot_id, mime: str, suffix: str, args: list[str], codec: str
) -> None:
    data = _transcode(_wav_bytes(), suffix=suffix, args=args)

    response = _upload(api_client, shot_id, data, mime=mime)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["codec"] == codec
    assert payload["format_name"]
    assert payload["mime_type"] == mime
    assert payload["duration_s"] == pytest.approx(DURATION, abs=0.15)
    assert payload["work_sample_rate"] == 48000
    assert payload["speech_segments"]

    content = api_client.get(payload["content_url"])
    assert content.content == data


def test_import_rejects_invalid_input(api_client, shot_id) -> None:
    wrong_mime = _upload(api_client, shot_id, _png(), mime="image/png")
    assert wrong_mime.status_code == 422
    assert wrong_mime.json()["detail"]["error"] == "unsupported_audio_type"

    broken = _upload(api_client, shot_id, b"this is not an audio stream")
    assert broken.status_code == 422
    assert broken.json()["detail"]["error"] in {"ffprobe_failed", "missing_audio_stream"}

    not_audio = _upload(api_client, shot_id, _png())
    assert not_audio.status_code == 422
    assert not_audio.json()["detail"]["error"] == "missing_audio_stream"

    empty = _upload(api_client, shot_id, b"")
    assert empty.status_code == 422
    assert empty.json()["detail"] == {"error": "empty_body"}

    mismatch = _upload(
        api_client, shot_id, _wav_bytes(), headers={"X-Content-SHA256": "0" * 64}
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["error"] == "sha256_mismatch"

    assert api_client.get(f"/api/shots/{uuid.uuid4()}/audio").status_code == 404
    # Ни одна некорректная загрузка не оставила записей.
    assert api_client.get(f"/api/shots/{shot_id}/audio").json() == []


def test_import_rejects_recording_over_duration_limit(
    api_client, shot_id, tmp_path
) -> None:
    api_client.app.dependency_overrides[get_settings] = lambda: Settings(
        storage_root=tmp_path / "storage", shot_audio_max_duration_s=1.0
    )
    try:
        response = _upload(api_client, shot_id, _wav_bytes(duration=2.0))
    finally:
        api_client.app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "audio_too_long"
    assert api_client.get(f"/api/shots/{shot_id}/audio").json() == []


def test_reimport_is_idempotent_and_replacement_keeps_old_record(
    api_client, scene_id, shot_id, make_shot
) -> None:
    data = _wav_bytes()
    first = _upload(api_client, shot_id, data)
    assert first.status_code == 201

    repeated = _upload(api_client, shot_id, data)
    assert repeated.status_code == 200
    assert repeated.json()["reference_asset_id"] == first.json()["reference_asset_id"]
    assert repeated.json()["link_id"] == first.json()["link_id"]

    # Тот же файл на другом шоте проекта: новый link, тот же ассет.
    second_shot = make_shot(scene_id=scene_id, sequence_no=2)
    reused = _upload(api_client, second_shot, data)
    assert reused.status_code == 200
    assert reused.json()["reference_asset_id"] == first.json()["reference_asset_id"]
    assert reused.json()["link_id"] != first.json()["link_id"]
    assert api_client.get(f"/api/shots/{second_shot}/audio").json()[0][
        "reference_asset_id"
    ] == first.json()["reference_asset_id"]

    replacement = _upload(
        api_client, shot_id, _wav_bytes(segments=((0.2, 0.6),), duration=1.2)
    )
    assert replacement.status_code == 201
    assert replacement.json()["reference_asset_id"] != first.json()["reference_asset_id"]

    library = api_client.get(f"/api/shots/{shot_id}/audio").json()
    assert len(library) == 2
    assert not any(item["selected"] for item in library)

    # «Выбранная» запись — последняя утверждённая; старая не удаляется.
    first_id = first.json()["reference_asset_id"]
    second_id = replacement.json()["reference_asset_id"]
    assert api_client.post(f"/api/reference-assets/{first_id}/approve").status_code == 200
    library = api_client.get(f"/api/shots/{shot_id}/audio").json()
    assert [item["reference_asset_id"] for item in library if item["selected"]] == [first_id]

    assert api_client.post(f"/api/reference-assets/{second_id}/approve").status_code == 200
    library = api_client.get(f"/api/shots/{shot_id}/audio").json()
    assert [item["reference_asset_id"] for item in library if item["selected"]] == [second_id]
    assert {item["reference_asset_id"]: item["status"] for item in library} == {
        first_id: "approved",
        second_id: "approved",
    }


def test_duplicate_sha256_of_another_role_is_a_conflict(
    api_client, shot_id, character_id
) -> None:
    data = _wav_bytes()

    voice = api_client.post(
        f"/api/characters/{character_id}/voice",
        content=data,
        headers={"Content-Type": "audio/wav"},
    )
    assert voice.status_code == 201

    conflict = _upload(api_client, shot_id, data)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["error"] == "duplicate_reference"
    assert conflict.json()["detail"]["reference_asset_id"] == voice.json()["id"]


def test_waveform_uses_metadata_and_recomputes_from_work_copy(
    api_client, conn: Connection, shot_id
) -> None:
    created = _upload(api_client, shot_id, _wav_bytes())
    asset_id = created.json()["reference_asset_id"]

    response = api_client.get(
        f"/api/shots/{shot_id}/audio/{asset_id}/waveform", params={"buckets": 32}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["buckets"] == 32
    assert len(payload["peaks"]) == 32
    assert max(payload["peaks"]) > 0
    assert max(payload["peaks"]) <= 1
    assert payload["duration_s"] == pytest.approx(DURATION, abs=0.05)

    too_few = api_client.get(
        f"/api/shots/{shot_id}/audio/{asset_id}/waveform", params={"buckets": 4}
    )
    assert too_few.status_code == 422
    assert (
        api_client.get(
            f"/api/shots/{shot_id}/audio/{uuid.uuid4()}/waveform"
        ).status_code
        == 404
    )

    conn.execute(
        text("UPDATE reference_assets SET metadata = metadata - 'envelope' WHERE id = :id"),
        {"id": asset_id},
    )
    recomputed = api_client.get(
        f"/api/shots/{shot_id}/audio/{asset_id}/waveform", params={"buckets": 32}
    )
    assert recomputed.status_code == 200
    assert len(recomputed.json()["peaks"]) == 32


def test_envelope_detects_speech_and_pauses() -> None:
    envelope = [0.0] * 10 + [0.4] * 20 + [0.0] * 10 + [0.5] * 20 + [0.0] * 10

    analysis = analyse_envelope(envelope)

    assert analysis["envelope_rate_hz"] == 50
    assert analysis["peak_rms"] == pytest.approx(0.5)
    assert analysis["gate"] == pytest.approx(0.03, abs=0.001)
    assert analysis["speech_segments"] == [
        {"start_s": 0.2, "end_s": 0.6},
        {"start_s": 0.8, "end_s": 1.2},
    ]
    assert analysis["silence_segments"] == [
        {"start_s": 0.0, "end_s": 0.2},
        {"start_s": 0.6, "end_s": 0.8},
        {"start_s": 1.2, "end_s": 1.4},
    ]
    assert analysis["speech_ratio"] == pytest.approx(0.571, abs=0.002)


def test_silent_envelope_has_no_speech_and_zero_gate() -> None:
    analysis = analyse_envelope([0.0] * 25)

    assert analysis["speech_segments"] == []
    assert analysis["silence_segments"] == [{"start_s": 0.0, "end_s": 0.5}]
    assert analysis["speech_ratio"] == 0.0
    assert analysis["gate"] == 1e-06


def test_waveform_peaks_returns_exact_bucket_count() -> None:
    envelope = [index / 50 for index in range(50)]

    peaks = waveform_peaks(envelope, 32)

    assert len(peaks) == 32
    assert peaks == sorted(peaks)
    assert peaks[-1] == pytest.approx(0.98)
    assert waveform_peaks(envelope, 50) == [round(value, 4) for value in envelope]
    assert waveform_peaks([], 10) == []
    assert waveform_peaks(envelope, 0) == []
