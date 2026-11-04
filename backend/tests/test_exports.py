"""WP-M2: сборка вертикального MP4 из видео-попыток (экспорт)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Connection, text

from app.storage import BlobStore

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="нужны ffmpeg и ffprobe")


def _render_clip(
    target: Path, *, color: str, duration_s: float, with_audio: bool
) -> Path:
    """Генерирует маленький валидный MP4 через ffmpeg (тестовый клип)."""

    command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=64x64:d={duration_s}:r=24",
    ]
    if with_audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_s}"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if with_audio:
        command += ["-c:a", "aac", "-shortest"]
    command += [str(target)]
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    return target


def _render_audio(target: Path, *, duration_s: float) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=330:duration={duration_s}",
            "-c:a",
            "aac",
            str(target),
        ],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return target


def _store_blob(tmp_path: Path, source: Path) -> tuple[str, str, int]:
    blob = BlobStore(tmp_path / "storage").put_file(source, suffix=".mp4")
    return blob.storage_key, blob.sha256, blob.size


def _video_attempt(
    conn: Connection,
    tmp_path: Path,
    shot_id: uuid.UUID,
    *,
    source: Path | None = None,
    kind: str = "video",
    status: str = "completed",
    with_artifact: bool = True,
) -> tuple[uuid.UUID, uuid.UUID | None]:
    """job + attempt (+artifact с настоящим MP4) прямыми INSERT."""

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
            "INSERT INTO render_attempts (id, shot_id, job_id, kind, status, duration_s)"
            " VALUES (:id, :shot, :job, :kind, :status, 8.04)"
        ),
        {
            "id": attempt_id,
            "shot": shot_id,
            "job": job_id,
            "kind": kind,
            "status": status,
        },
    )
    artifact_id: uuid.UUID | None = None
    if with_artifact:
        assert source is not None
        storage_key, sha256, size = _store_blob(tmp_path, source)
        artifact_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO artifacts"
                " (id, attempt_id, source, kind, storage_key, sha256, bytes, mime_type)"
                " VALUES (:id, :attempt, 'attempt', 'video', :key, :sha, :size,"
                "  'video/mp4')"
            ),
            {
                "id": artifact_id,
                "attempt": attempt_id,
                "key": storage_key,
                "sha": sha256,
                "size": size,
            },
        )
    return attempt_id, artifact_id


def _audio_artifact(conn: Connection, tmp_path: Path, source: Path) -> uuid.UUID:
    storage_key, sha256, size = _store_blob(tmp_path, source)
    value = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO artifacts"
            " (id, source, kind, storage_key, sha256, bytes, mime_type)"
            " VALUES (:id, 'upload', 'audio', :key, :sha, :size, 'audio/mp4')"
        ),
        {"id": value, "key": storage_key, "sha": sha256, "size": size},
    )
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _probe_video(path: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return json.loads(result.stdout)["streams"][0]


@needs_ffmpeg
def test_create_export_builds_1080x1920_and_keeps_sources(
    api_client, conn: Connection, tmp_path, make_shot, project_id, scene_id
) -> None:
    first = make_shot(scene_id=scene_id, sequence_no=1)
    second = make_shot(scene_id=scene_id, sequence_no=2)
    first_src = _render_clip(tmp_path / "a.mp4", color="red", duration_s=0.6, with_audio=True)
    second_src = _render_clip(
        tmp_path / "b.mp4", color="blue", duration_s=0.6, with_audio=False
    )
    first_attempt, first_artifact = _video_attempt(conn, tmp_path, first, source=first_src)
    second_attempt, second_artifact = _video_attempt(conn, tmp_path, second, source=second_src)
    first_sha, second_sha = _sha256(first_src), _sha256(second_src)

    response = api_client.post(
        f"/api/projects/{project_id}/exports",
        json={
            "clips": [
                {"shot_id": str(first), "attempt_id": str(first_attempt)},
                {
                    "shot_id": str(second),
                    "attempt_id": str(second_attempt),
                    "trim_end_s": 0.3,
                },
            ]
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["width"] == 1080
    assert payload["height"] == 1920
    assert payload["fps"] == 24
    assert payload["clip_count"] == 2
    assert payload["audio_artifact_id"] is None
    assert 0.6 < payload["duration_s"] < 1.4
    assert payload["content_url"] == f"/api/artifacts/{payload['artifact_id']}/content"

    # `/api/artifacts/{id}/content` берёт отдельную сессию и не видит строку
    # незакоммиченной транзакции теста — проверяем блоб прямо в storage.
    store = BlobStore(tmp_path / "storage")
    export_path = store.resolve(store.key_for(payload["sha256"], ".mp4"))
    assert _sha256(export_path) == payload["sha256"]
    assert export_path.stat().st_size == payload["bytes"]
    stream = _probe_video(export_path)
    assert stream["codec_name"] == "h264"
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert str(stream["r_frame_rate"]).startswith("24/")

    # Исходные блобы не изменились (DoD WP-M2).
    assert _sha256(first_src) == first_sha
    assert _sha256(second_src) == second_sha

    export_row = conn.execute(
        text("SELECT source, kind, metadata FROM artifacts WHERE id = :id"),
        {"id": uuid.UUID(payload["artifact_id"])},
    ).one()
    assert export_row.source == "export"
    assert export_row.kind == "export_video"
    metadata = export_row.metadata
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    assert metadata["project_id"] == str(project_id)
    assert metadata["width"] == 1080
    assert [clip["artifact_id"] for clip in metadata["clips"]] == [
        str(first_artifact),
        str(second_artifact),
    ]
    assert metadata["clips"][1]["trim_end_s"] == 0.3
    assert metadata["clips"][0]["sha256"] == first_sha
    assert metadata["audio_artifact_id"] is None

    listed = api_client.get(f"/api/projects/{project_id}/exports")
    assert listed.status_code == 200
    assert [item["artifact_id"] for item in listed.json()] == [payload["artifact_id"]]


@needs_ffmpeg
def test_external_audio_replaces_clip_sound(
    api_client, conn: Connection, tmp_path, make_shot, project_id, scene_id
) -> None:
    shot = make_shot(scene_id=scene_id, sequence_no=1)
    clip = _render_clip(tmp_path / "clip.mp4", color="green", duration_s=0.6, with_audio=True)
    attempt_id, _ = _video_attempt(conn, tmp_path, shot, source=clip)
    audio_path = _render_audio(tmp_path / "music.m4a", duration_s=3.0)
    audio_id = _audio_artifact(conn, tmp_path, audio_path)

    response = api_client.post(
        f"/api/projects/{project_id}/exports",
        json={
            "clips": [{"shot_id": str(shot), "attempt_id": str(attempt_id)}],
            "audio_artifact_id": str(audio_id),
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["audio_artifact_id"] == str(audio_id)
    # `-shortest`: длинная музыка обрезается по видео.
    assert payload["duration_s"] < 1.2


def _insert_artifact(
    conn: Connection,
    *,
    source: str,
    kind: str,
    mime_type: str,
    attempt_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO artifacts"
            " (id, attempt_id, source, kind, storage_key, sha256, bytes, mime_type)"
            " VALUES (:id, :attempt, :source, :kind, :key, :sha, 10, :mime)"
        ),
        {
            "id": value,
            "attempt": attempt_id,
            "source": source,
            "kind": kind,
            "key": f"blobs/{value.hex[:2]}/{value.hex}.bin",
            "sha": uuid.uuid4().hex + uuid.uuid4().hex,
            "mime": mime_type,
        },
    )
    return value


def test_export_guards(
    api_client,
    conn: Connection,
    tmp_path,
    make_shot,
    project_id,
    second_project_id,
    scene_id,
) -> None:
    shot = make_shot(scene_id=scene_id, sequence_no=1)
    other_shot = make_shot(scene_id=scene_id, sequence_no=2)
    url = f"/api/projects/{project_id}/exports"

    assert (
        api_client.post(
            f"/api/projects/{uuid.uuid4()}/exports",
            json={"clips": [{"shot_id": str(shot), "attempt_id": str(uuid.uuid4())}]},
        ).status_code
        == 404
    )
    assert api_client.post(url, json={"clips": []}).status_code == 422
    assert (
        api_client.post(
            url,
            json={"clips": [{"shot_id": str(shot), "attempt_id": str(uuid.uuid4())}]},
        ).status_code
        == 404
    )

    keyframe_attempt, _ = _video_attempt(
        conn, tmp_path, shot, kind="keyframe", with_artifact=False
    )
    running_attempt, _ = _video_attempt(
        conn, tmp_path, shot, status="running", with_artifact=False
    )
    no_artifact_attempt, _ = _video_attempt(conn, tmp_path, shot, with_artifact=False)
    # Артефакт видео-попытки с неверным mime: файл не нужен, проверка идёт до ffmpeg.
    not_mp4_attempt, _ = _video_attempt(conn, tmp_path, shot, with_artifact=False)
    not_mp4_artifact = _insert_artifact(
        conn,
        source="attempt",
        kind="video",
        mime_type="image/png",
        attempt_id=not_mp4_attempt,
    )
    # Валидный клип для проверок аудио: mime MP4, до чтения файла дело не дойдёт.
    valid_attempt, _ = _video_attempt(conn, tmp_path, shot, with_artifact=False)
    _insert_artifact(
        conn,
        source="attempt",
        kind="video",
        mime_type="video/mp4",
        attempt_id=valid_attempt,
    )

    keyframe = api_client.post(
        url, json={"clips": [{"shot_id": str(shot), "attempt_id": str(keyframe_attempt)}]}
    )
    assert keyframe.status_code == 409
    assert "video" in keyframe.json()["detail"]

    running = api_client.post(
        url, json={"clips": [{"shot_id": str(shot), "attempt_id": str(running_attempt)}]}
    )
    assert running.status_code == 409
    assert "completed" in running.json()["detail"]

    missing = api_client.post(
        url, json={"clips": [{"shot_id": str(shot), "attempt_id": str(no_artifact_attempt)}]}
    )
    assert missing.status_code == 409
    assert "artifact" in missing.json()["detail"]

    not_mp4 = api_client.post(
        url, json={"clips": [{"shot_id": str(shot), "attempt_id": str(not_mp4_attempt)}]}
    )
    assert not_mp4.status_code == 409
    assert "MP4" in not_mp4.json()["detail"]

    # Попытка другого шота.
    foreign_attempt, _ = _video_attempt(conn, tmp_path, other_shot, with_artifact=False)
    crossed = api_client.post(
        url, json={"clips": [{"shot_id": str(shot), "attempt_id": str(foreign_attempt)}]}
    )
    assert crossed.status_code == 409
    assert "does not belong" in crossed.json()["detail"]

    # Чужой проект.
    other_project = api_client.post(
        f"/api/projects/{second_project_id}/exports",
        json={"clips": [{"shot_id": str(shot), "attempt_id": str(foreign_attempt)}]},
    )
    assert other_project.status_code == 409
    assert "another project" in other_project.json()["detail"]

    # Аудио: 404 для неизвестного и 409 для не-аудио артефакта.
    valid_clip = {"shot_id": str(shot), "attempt_id": str(valid_attempt)}
    assert (
        api_client.post(
            url,
            json={
                "clips": [valid_clip],
                "audio_artifact_id": str(_insert_artifact(
                    conn, source="attempt", kind="video", mime_type="image/png",
                    attempt_id=not_mp4_attempt,
                )),
            },
        ).status_code
        == 409
    )
    assert (
        api_client.post(
            url,
            json={"clips": [valid_clip], "audio_artifact_id": str(uuid.uuid4())},
        ).status_code
        == 404
    )
    assert (
        api_client.post(
            url,
            json={
                "clips": [valid_clip],
                "audio_artifact_id": str(
                    _insert_artifact(
                        conn, source="upload", kind="keyframe", mime_type="image/png"
                    )
                ),
            },
        ).status_code
        == 409
    )
    assert not_mp4_artifact is not None

    assert api_client.get(f"/api/projects/{uuid.uuid4()}/exports").status_code == 404


@needs_ffmpeg
def test_export_rejects_trim_out_of_range(
    api_client, conn: Connection, tmp_path, make_shot, project_id, scene_id
) -> None:
    shot = make_shot(scene_id=scene_id, sequence_no=1)
    clip = _render_clip(tmp_path / "clip.mp4", color="black", duration_s=0.6, with_audio=False)
    attempt_id, _ = _video_attempt(conn, tmp_path, shot, source=clip)

    response = api_client.post(
        f"/api/projects/{project_id}/exports",
        json={
            "clips": [
                {"shot_id": str(shot), "attempt_id": str(attempt_id), "trim_end_s": 5.0}
            ]
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "trim_out_of_range"

    # Экспорт не создан.
    listed = api_client.get(f"/api/projects/{project_id}/exports").json()
    assert listed == []
