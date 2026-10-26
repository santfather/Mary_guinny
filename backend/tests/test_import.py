from __future__ import annotations

import hashlib
import struct
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.legacy_import import (
    CREATE,
    EXISTS,
    SKIP,
    ImportOptions,
    render_report,
    run_import,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

SCRIPT = """СЦЕНА 1: Морозильная камера
ГИННЕСС: Мяу.
МАРИЯ: Привет.
ДЕЙСТВИЕ: Кот лежит на полу.

СЦЕНА 2: Вторая сцена
ГИННЕСС: Ещё.
МАРИЯ: Да.
ДЕЙСТВИЕ: Кот спит.
"""


def _chunk(chunk_type: bytes, payload: bytes) -> bytes:
    return len(payload).to_bytes(4, "big") + chunk_type + payload + b"\x00\x00\x00\x00"


def make_png(
    width: int = 64, height: int = 48, color_type: int = 2, trns: bool = False
) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    data = PNG_SIGNATURE + _chunk(b"IHDR", header)
    if trns:
        data += _chunk(b"tRNS", b"\x00" * 6)
    return data + _chunk(b"IDAT", b"\x00") + _chunk(b"IEND", b"")


def make_jpeg(width: int = 40, height: int = 30) -> bytes:
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof = (
        b"\xff\xc0"
        + (17).to_bytes(2, "big")
        + b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    return b"\xff\xd8" + app0 + sof + b"\xff\xd9"


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def legacy_tree(tmp_path: Path) -> Path:
    root = tmp_path / "legacy"
    guinness = root / "characters" / "guinness"
    guinness.mkdir(parents=True)
    (guinness / "character_bible.txt").write_text("Guinness — кот.", encoding="utf-8")
    (guinness / "reference_front.png").write_bytes(make_png(64, 48, color_type=6))
    (guinness / "reference_sit.png").write_bytes(make_png(32, 24, color_type=2))
    (guinness / "reference_side.jpeg").write_bytes(make_jpeg(40, 30))
    (guinness / "1.png").write_bytes(make_png(8, 8))

    episode = root / "episodes" / "ep01"
    (episode / "scenes").mkdir(parents=True)
    (episode / "audio").mkdir()
    (episode / "poc").mkdir()
    (episode / "script.txt").write_text(SCRIPT, encoding="utf-8")
    (episode / "scenes" / "scene_01_keyframe.png").write_bytes(make_png(64, 48, color_type=6))
    (episode / "scenes" / "scene_01_draft.mp4").write_bytes(b"fake-mp4-draft")
    (episode / "scenes" / "scene_01_final.mp4").write_bytes(b"fake-mp4-final")
    (episode / "scenes" / "scene_02_keyframe.png").write_bytes(make_png(64, 48))
    (episode / "audio" / "voice.mp3").write_bytes(b"fake-mp3")
    (episode / "poc" / "ltx.meta.json").write_text("{}", encoding="utf-8")
    return root


def _options(legacy_tree: Path, tmp_path: Path, title: str) -> ImportOptions:
    return ImportOptions(
        legacy_root=legacy_tree,
        storage_root=tmp_path / "storage",
        project_title=title,
    )


def _blob_count(storage_root: Path) -> int:
    blobs = storage_root / "blobs"
    if not blobs.is_dir():
        return 0
    return sum(1 for path in blobs.rglob("*") if path.is_file())


def test_dry_run_reports_plan_without_side_effects(
    conn: Connection, legacy_tree: Path, tmp_path: Path
) -> None:
    title = f"dry-run-{uuid.uuid4()}"
    before = _hash_tree(legacy_tree)

    with Session(bind=conn) as session:
        report = run_import(session, _options(legacy_tree, tmp_path, title), apply=False)

    assert report.mode == "dry-run"
    assert report.created > 0
    assert not (tmp_path / "storage").exists()
    assert conn.scalar(
        text("SELECT count(*) FROM projects WHERE title = :title"), {"title": title}
    ) == 0
    assert _hash_tree(legacy_tree) == before

    categories = {(operation.category, operation.action) for operation in report.operations}
    assert ("project", CREATE) in categories
    assert ("character", CREATE) in categories
    assert ("reference", CREATE) in categories
    assert ("keyframe", CREATE) in categories
    assert ("video", CREATE) in categories
    assert ("file", SKIP) in categories

    markdown = render_report(report)
    assert "alpha=да" in markdown
    assert "alpha=нет" in markdown
    assert "scene_01_final.mp4" in markdown
    assert "1.png" in markdown


def test_apply_imports_data_and_is_idempotent(
    conn: Connection, legacy_tree: Path, tmp_path: Path
) -> None:
    title = f"apply-{uuid.uuid4()}"
    storage_root = tmp_path / "storage"
    before = _hash_tree(legacy_tree)

    with Session(bind=conn) as session:
        first = run_import(session, _options(legacy_tree, tmp_path, title), apply=True)
        session.flush()

    assert first.created > 0
    # 6 файлов, но reference_front.png и scene_01_keyframe.png совпадают побайтно:
    # content-addressed storage хранит их как один blob.
    assert first.blob_writes == 5
    assert first.blob_hits == 1
    assert _blob_count(storage_root) == 5

    project_id = conn.scalar(
        text("SELECT id FROM projects WHERE title = :title"), {"title": title}
    )
    assert project_id is not None

    assert conn.scalar(
        text("SELECT count(*) FROM characters WHERE project_id = :project_id"),
        {"project_id": project_id},
    ) == 1
    assert conn.scalar(
        text("SELECT kind FROM characters WHERE project_id = :project_id"),
        {"project_id": project_id},
    ) == "other"

    bible = conn.execute(
        text(
            "SELECT version, status, source, sha256 FROM character_bible_versions"
            " WHERE project_id = :project_id"
        ),
        {"project_id": project_id},
    ).one()
    assert bible.version == 1
    assert bible.status == "draft"
    assert bible.source == "import"
    assert len(bible.sha256) == 64

    assets = conn.execute(
        text(
            "SELECT role, view, pose, expression, width, height, mime_type,"
            " metadata, storage_key FROM reference_assets"
            " WHERE project_id = :project_id ORDER BY role"
        ),
        {"project_id": project_id},
    ).all()
    assert len(assets) == 3
    by_role = {row.role: row for row in assets}
    assert by_role["reference_front"].metadata["has_alpha"] is True
    assert by_role["reference_sit"].metadata["has_alpha"] is False
    assert by_role["reference_side"].metadata["has_alpha"] is False
    assert by_role["reference_front"].width == 64
    assert by_role["reference_front"].height == 48
    assert by_role["reference_front"].view == "front"
    assert by_role["reference_sit"].pose == "sit"
    assert by_role["reference_side"].mime_type == "image/jpeg"
    assert by_role["reference_side"].width == 40
    for row in assets:
        assert row.storage_key.startswith("blobs/")
        assert not row.storage_key.startswith("/")

    assert conn.scalar(
        text("SELECT count(*) FROM episodes WHERE project_id = :project_id"),
        {"project_id": project_id},
    ) == 1
    assert conn.scalar(
        text("SELECT count(*) FROM scenes WHERE project_id = :project_id"),
        {"project_id": project_id},
    ) == 2
    assert conn.scalar(
        text(
            "SELECT count(*) FROM shots s JOIN scenes c ON c.id = s.scene_id"
            " WHERE c.project_id = :project_id"
        ),
        {"project_id": project_id},
    ) == 2
    assert conn.scalar(
        text(
            "SELECT count(*) FROM prompt_revisions p JOIN shots s ON s.id = p.shot_id"
            " JOIN scenes c ON c.id = s.scene_id"
            " WHERE c.project_id = :project_id AND p.prompt_type = 'script'"
        ),
        {"project_id": project_id},
    ) == 2

    keyframe_attempts = conn.execute(
        text(
            "SELECT r.job_id, r.status FROM render_attempts r"
            " JOIN shots s ON s.id = r.shot_id JOIN scenes c ON c.id = s.scene_id"
            " WHERE c.project_id = :project_id AND r.kind = 'keyframe'"
        ),
        {"project_id": project_id},
    ).all()
    assert len(keyframe_attempts) == 2
    assert all(row.job_id is None and row.status == "completed" for row in keyframe_attempts)

    video_job = conn.execute(
        text(
            "SELECT j.id, j.status, j.idempotency_key FROM jobs j"
            " JOIN shots s ON s.id = j.shot_id JOIN scenes c ON c.id = s.scene_id"
            " WHERE c.project_id = :project_id AND j.idempotency_key LIKE 'legacy:%'"
        ),
        {"project_id": project_id},
    ).one()
    assert video_job.status == "completed"
    assert len(video_job.idempotency_key.split(":")[1]) == 64

    video_attempt = conn.execute(
        text(
            "SELECT input_artifact_ids FROM render_attempts"
            " WHERE kind = 'video' AND job_id = :job_id"
        ),
        {"job_id": video_job.id},
    ).one()
    assert video_attempt.input_artifact_ids is not None
    assert len(video_attempt.input_artifact_ids) == 1

    artifact_kinds = conn.execute(
        text(
            "SELECT a.kind, count(*) AS total FROM artifacts a"
            " JOIN render_attempts r ON r.id = a.attempt_id"
            " JOIN shots s ON s.id = r.shot_id JOIN scenes c ON c.id = s.scene_id"
            " WHERE c.project_id = :project_id GROUP BY a.kind ORDER BY a.kind"
        ),
        {"project_id": project_id},
    ).all()
    assert {row.kind: row.total for row in artifact_kinds} == {
        "keyframe": 2,
        "video_draft": 1,
    }

    assert conn.scalar(
        text(
            "SELECT count(*) FROM shots s JOIN scenes c ON c.id = s.scene_id"
            " WHERE c.project_id = :project_id"
            " AND s.start_keyframe_artifact_id IS NOT NULL"
        ),
        {"project_id": project_id},
    ) == 0

    assert _hash_tree(legacy_tree) == before

    with Session(bind=conn) as session:
        second = run_import(session, _options(legacy_tree, tmp_path, title), apply=True)
        session.flush()

    assert second.created == 0
    assert second.blob_writes == 0
    assert _blob_count(storage_root) == 5
    assert {
        (operation.category, operation.action) for operation in second.operations
    } >= {("project", EXISTS), ("reference", EXISTS), ("keyframe", EXISTS), ("video", EXISTS)}
    assert conn.scalar(
        text("SELECT count(*) FROM reference_assets WHERE project_id = :project_id"),
        {"project_id": project_id},
    ) == 3
