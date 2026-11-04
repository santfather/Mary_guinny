"""WP-M3: аудио проекта, таймлайн и черновые планы производства."""

from __future__ import annotations

import hashlib
import io
import json
import math
import shutil
import struct
import uuid
import wave

import httpx
import pytest

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="нужны ffmpeg и ffprobe")

SAMPLE_RATE = 8000


def _click_wav_bytes() -> bytes:
    """6 секунд кликов каждые 0.5 с: таймлайн строится, план генерируется."""

    duration_s = 6.0
    interval_s = 0.5
    frames = int(SAMPLE_RATE * duration_s)
    samples = [0] * frames
    click = int(SAMPLE_RATE * 0.05)
    moment = 0.0
    while moment < duration_s:
        start = int(moment * SAMPLE_RATE)
        for offset in range(click):
            if start + offset >= frames:
                break
            envelope = 1 - offset / click
            samples[start + offset] = int(
                12000 * envelope * math.sin(2 * math.pi * 1000.0 * offset / SAMPLE_RATE)
            )
        moment += interval_s
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return _append_junk(buffer.getvalue(), size=16)


def _append_junk(payload: bytes, *, size: int) -> bytes:
    """Уникальный JUNK-чанк: дедупликация артефактов по sha256 не должна возвращать
    артефакт прошлого прогона, чей blob уже удалён вместе с временным каталогом."""

    chunk = b"JUNK" + struct.pack("<I", size) + uuid.uuid4().bytes[:size]
    riff_size = struct.unpack("<I", payload[4:8])[0] + len(chunk)
    return payload[:4] + struct.pack("<I", riff_size) + payload[8:] + chunk


def _upload(client, data: bytes, *, kind: str, content_type: str) -> str:
    digest = hashlib.sha256(data).hexdigest()
    response = client.post(
        f"/api/artifacts?kind={kind}",
        content=data,
        headers={"X-Content-SHA256": digest, "Content-Type": content_type},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _attach_audio(client, project_id: uuid.UUID) -> str:
    data = _click_wav_bytes()
    artifact_id = _upload(client, data, kind="project_audio", content_type="audio/wav")
    response = client.post(
        f"/api/projects/{project_id}/audio", json={"artifact_id": artifact_id}
    )
    assert response.status_code == 201, response.text
    return artifact_id


def _valid_response() -> str:
    return json.dumps(
        {
            "logline": "Кот-гитарист ведёт группу через неоновую ночь.",
            "scenes": [
                {
                    "section_index": 0,
                    "title": "Вступление",
                    "intent": "Задать настроение",
                    "shots": [
                        {
                            "action": "Гиннесс выходит на сцену",
                            "prompt": "slow dolly-in on the cat",
                            "framing": "medium",
                            "camera_movement": "dolly",
                        },
                        {
                            "action": "Группа играет",
                            "prompt": "wide pan across the neon stage",
                            "framing": "wide",
                            "camera_movement": "pan",
                        },
                    ],
                }
            ],
            "notes": ["Холодный неоновый свет"],
        },
        ensure_ascii=False,
    )


@needs_ffmpeg
def test_attach_audio_and_build_timeline(api_client, project_id) -> None:
    artifact_id = _attach_audio(api_client, project_id)

    audio = api_client.get(f"/api/projects/{project_id}/audio")
    assert audio.status_code == 200
    body = audio.json()
    assert body["artifact_id"] == artifact_id
    assert body["mime_type"] == "audio/wav"
    assert body["duration_s"] == pytest.approx(6.0, abs=0.2)
    assert body["content_url"] == f"/api/artifacts/{artifact_id}/content"

    timeline = api_client.get(f"/api/projects/{project_id}/timeline")
    assert timeline.status_code == 200, timeline.text
    payload = timeline.json()
    assert payload["bpm"] == pytest.approx(120.0, abs=3.0)
    assert payload["duration_s"] == pytest.approx(6.0, abs=0.2)
    assert payload["sections"]
    assert payload["method"] == "ffmpeg_envelope_v1"


def test_audio_and_plan_guards(api_client, project_id) -> None:
    assert api_client.get(f"/api/projects/{project_id}/audio").status_code == 409
    assert api_client.get(f"/api/projects/{project_id}/timeline").status_code == 409
    generate = api_client.post(
        f"/api/projects/{project_id}/production-plans/generate", json={}
    )
    assert generate.status_code == 409

    text = _upload(api_client, b"just text", kind="note", content_type="text/plain")
    not_audio = api_client.post(
        f"/api/projects/{project_id}/audio", json={"artifact_id": text}
    )
    assert not_audio.status_code == 409

    missing = api_client.post(
        f"/api/projects/{project_id}/audio", json={"artifact_id": str(uuid.uuid4())}
    )
    assert missing.status_code == 404


@needs_ffmpeg
def test_generate_creates_draft_revisions(api_client, project_id, monkeypatch) -> None:
    calls: list[str] = []

    def fake(prompt: str, settings) -> str:
        calls.append(prompt)
        return _valid_response()

    monkeypatch.setattr("app.production_plan._call_ollama", fake)
    _attach_audio(api_client, project_id)

    first = api_client.post(
        f"/api/projects/{project_id}/production-plans/generate",
        json={"brief": "Неоновая ночь, кот-гитарист"},
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["revision"] == 1
    assert body["status"] == "draft"
    assert body["source"] == "llm"
    assert body["plan"]["scenes"][0]["title"] == "Вступление"
    assert body["plan"]["scenes"][0]["shots"][0]["prompt"] == "slow dolly-in on the cat"
    assert body["timeline"]["bpm"] == pytest.approx(120.0, abs=3.0)
    assert len(calls) == 1

    second = api_client.post(
        f"/api/projects/{project_id}/production-plans/generate", json={}
    )
    assert second.status_code == 201, second.text
    assert second.json()["revision"] == 2

    listed = api_client.get(f"/api/projects/{project_id}/production-plans")
    assert listed.status_code == 200
    revisions = {item["revision"]: item["status"] for item in listed.json()}
    assert revisions == {2: "draft", 1: "superseded"}

    detail = api_client.get(f"/api/production-plans/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["revision"] == 1
    assert api_client.get(f"/api/production-plans/{uuid.uuid4()}").status_code == 404


@needs_ffmpeg
def test_generate_repairs_invalid_response(api_client, project_id, monkeypatch) -> None:
    replies = iter(["not json at all", _valid_response()])

    def fake(prompt: str, settings) -> str:
        return next(replies)

    monkeypatch.setattr("app.production_plan._call_ollama", fake)
    _attach_audio(api_client, project_id)

    response = api_client.post(
        f"/api/projects/{project_id}/production-plans/generate", json={}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "llm"
    assert [warning["code"] for warning in body["warnings"]] == ["plan_repair"]


@needs_ffmpeg
def test_generate_falls_back_when_model_unavailable(
    api_client, project_id, monkeypatch
) -> None:
    def fake(prompt: str, settings) -> str:
        raise httpx.ConnectError("ollama is down")

    monkeypatch.setattr("app.production_plan._call_ollama", fake)
    _attach_audio(api_client, project_id)

    response = api_client.post(
        f"/api/projects/{project_id}/production-plans/generate", json={}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "fallback"
    assert body["plan"]["needs_review"] is True
    assert [warning["code"] for warning in body["warnings"]] == ["plan_model_unavailable"]


@needs_ffmpeg
def test_generate_stops_after_bounded_repair(api_client, project_id, monkeypatch) -> None:
    calls: list[int] = []

    def fake(prompt: str, settings) -> str:
        calls.append(1)
        return "{}"

    monkeypatch.setattr("app.production_plan._call_ollama", fake)
    _attach_audio(api_client, project_id)

    response = api_client.post(
        f"/api/projects/{project_id}/production-plans/generate", json={}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "fallback"
    assert len(calls) == 3
    assert [warning["code"] for warning in body["warnings"]] == [
        "plan_repair",
        "plan_repair",
        "plan_invalid",
    ]


@needs_ffmpeg
def test_generate_without_llm_keeps_skeleton(api_client, project_id, monkeypatch) -> None:
    def fake(prompt: str, settings) -> str:
        raise AssertionError("LLM не должен вызываться")

    monkeypatch.setattr("app.production_plan._call_ollama", fake)
    _attach_audio(api_client, project_id)

    response = api_client.post(
        f"/api/projects/{project_id}/production-plans/generate",
        json={"use_llm": False},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"] == "manual"
    assert body["plan"]["needs_review"] is True
    assert body["plan"]["scenes"][0]["shots"]
