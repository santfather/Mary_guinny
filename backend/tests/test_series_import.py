from __future__ import annotations

import io
import uuid
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

from app.series_import import CREATE, ERROR, ImportOptions, import_series
from app.series_manifest import parse_manifest
from app.storage import BlobStore

SHOTS_BY_PROJECT = (
    "SELECT count(*) FROM shots s JOIN scenes sc ON sc.id = s.scene_id"
    " WHERE sc.project_id = :id"
)
PROMPTS_BY_PROJECT = (
    "SELECT count(*) FROM prompt_revisions p JOIN shots s ON s.id = p.shot_id"
    " JOIN scenes sc ON sc.id = s.scene_id WHERE sc.project_id = :id"
)
ASSETS_BY_PROJECT = "SELECT count(*) FROM reference_assets WHERE project_id = :id"
LINKS_BY_PROJECT = "SELECT count(*) FROM shot_references WHERE project_id = :id"


def png_bytes(
    width: int = 64, height: int = 48, color: tuple[int, int, int, int] = (10, 20, 30, 255)
) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _shot(order: int, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "order": order,
        "shot_key": f"NLB-{order:02d}",
        "title": f"Шот {order}",
        "category": "performer",
        "reference_filename_from_plan": "01_vocalist_clean.png",
        "start_frame_filename": "01_vocalist_clean.png",
        "identity_reference_filename": None,
        "prompt_original": f"prompt {order}",
        "target_duration_seconds": [7, 8],
        "status": "needs_preflight",
        "approved": False,
        "seed": None,
        "workflow_version": None,
        "output_name_prefix": f"NLB_{order:02d}",
    }
    data.update(overrides)
    return data


def _manifest(shots: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "project": "The Nine Lives Band",
        "episode": "Ночной тыгыдык",
        "source_document": "plan.docx",
        "target_aspect_ratio": "9:16",
        "target_fps": None,
        "concurrency": 1,
        "shots": shots,
    }


def _three_shots() -> list[dict[str, object]]:
    return [
        _shot(1),
        _shot(2),
        _shot(
            3,
            category="story",
            start_frame_filename=None,
            reference_filename_from_plan="Guiness_clean.png",
            identity_reference_filename="Guiness_clean.png",
        ),
    ]


def _named_reference(
    tmp_path: Path,
    make_reference: Callable[..., uuid.UUID],
    project_id: uuid.UUID,
    name: str,
    *,
    status: str = "approved",
    color: tuple[int, int, int, int] = (10, 20, 30, 255),
) -> uuid.UUID:
    store = BlobStore(tmp_path / "storage")
    blob = store.put_bytes(png_bytes(color=color), suffix=".png")
    return make_reference(
        project_id=project_id,
        status=status,
        storage_key=blob.storage_key,
        sha256=blob.sha256,
        metadata={"original_name": name},
        width=64,
        height=48,
    )


def _count(conn: Connection, sql: str, **params: object) -> int:
    return int(conn.scalar(text(sql), params) or 0)


def test_import_creates_structure_and_is_idempotent(
    conn: Connection,
    tmp_path: Path,
    project_id: uuid.UUID,
    make_reference: Callable[..., uuid.UUID],
) -> None:
    _named_reference(tmp_path, make_reference, project_id, "01_vocalist_clean.png")
    _named_reference(
        tmp_path,
        make_reference,
        project_id,
        "Guiness_clean.png",
        color=(200, 100, 50, 255),
    )
    manifest = parse_manifest(_manifest(_three_shots()))
    store = BlobStore(tmp_path / "storage")
    options = ImportOptions(project_title="Project A")

    with Session(bind=conn) as session:
        report = import_series(session, store, manifest, options, apply=True)

    assert report.errors == []
    assert report.shots_created == 3
    assert report.project_id == project_id
    assert _count(conn, "SELECT count(*) FROM episodes WHERE project_id = :id", id=project_id) == 1
    assert _count(conn, "SELECT count(*) FROM scenes WHERE project_id = :id", id=project_id) == 1
    assert _count(conn, SHOTS_BY_PROJECT, id=project_id) == 3
    assert _count(conn, PROMPTS_BY_PROJECT, id=project_id) == 3
    assert _count(conn, LINKS_BY_PROJECT, id=project_id) == 3

    shot = conn.execute(
        text(
            "SELECT s.sequence_no, s.target_duration_frames, s.timeline_fps, s.status,"
            " s.current_prompt_revision_id FROM shots s"
            " JOIN scenes sc ON sc.id = s.scene_id"
            " WHERE sc.project_id = :id AND s.sequence_no = 1"
        ),
        {"id": project_id},
    ).one()
    assert shot.sequence_no == 1
    assert shot.target_duration_frames == 193
    assert float(shot.timeline_fps) == 24.0
    assert shot.status == "prompt_ready"
    assert shot.current_prompt_revision_id is not None

    parameters = conn.scalar(
        text(
            "SELECT p.parameters_json FROM prompt_revisions p"
            " JOIN shots s ON s.id = p.shot_id JOIN scenes sc ON sc.id = s.scene_id"
            " WHERE sc.project_id = :id AND s.sequence_no = 1 AND p.version = 1"
        ),
        {"id": project_id},
    )
    assert parameters["source"] == "nine_lives_band_manifest"
    assert parameters["shot_key"] == "NLB-01"
    assert parameters["manifest_sha256"] == manifest.sha256
    assert parameters["duration_seconds"] == [7, 8]
    assert parameters["target_frames"] == 193

    with Session(bind=conn) as session:
        again = import_series(session, store, manifest, options, apply=True)

    assert again.shots_created == 0
    assert again.shots_existing == 3
    assert _count(conn, SHOTS_BY_PROJECT, id=project_id) == 3
    assert _count(conn, PROMPTS_BY_PROJECT, id=project_id) == 3
    assert _count(conn, LINKS_BY_PROJECT, id=project_id) == 3
    counts = again.counts()
    assert counts["shot"][CREATE] == 0
    assert counts["prompt"][CREATE] == 0
    assert counts["shot_reference"][CREATE] == 0


def test_import_reports_missing_reference_without_substitution(
    conn: Connection, tmp_path: Path, project_id: uuid.UUID
) -> None:
    manifest = parse_manifest(_manifest([_shot(1)]))
    store = BlobStore(tmp_path / "storage")

    with Session(bind=conn) as session:
        report = import_series(
            session,
            store,
            manifest,
            ImportOptions(project_title="Project A"),
            apply=True,
        )

    assert any("фиктивная подстановка запрещена" in item for item in report.errors)
    assert _count(conn, SHOTS_BY_PROJECT, id=project_id) == 1
    assert _count(conn, ASSETS_BY_PROJECT, id=project_id) == 0
    assert _count(conn, LINKS_BY_PROJECT, id=project_id) == 0
    assert (ERROR, "reference") in {(row.action, row.category) for row in report.rows}


def test_import_uploads_missing_reference_from_directory(
    conn: Connection, tmp_path: Path, project_id: uuid.UUID
) -> None:
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "07_extra_clean.png").write_bytes(png_bytes())
    manifest = parse_manifest(
        _manifest(
            [
                _shot(
                    1,
                    reference_filename_from_plan="07_extra_clean.png",
                    start_frame_filename="07_extra_clean.png",
                )
            ]
        )
    )
    store = BlobStore(tmp_path / "storage")

    with Session(bind=conn) as session:
        report = import_series(
            session,
            store,
            manifest,
            ImportOptions(project_title="Project A", reference_dirs=(refs,)),
            apply=True,
        )

    assert report.errors == []
    row = conn.execute(
        text(
            "SELECT kind, status, storage_key, metadata FROM reference_assets"
            " WHERE project_id = :id"
        ),
        {"id": project_id},
    ).one()
    assert row.kind == "uploaded"
    assert row.status == "draft"
    assert row.metadata["original_name"] == "07_extra_clean.png"
    assert store.exists(row.storage_key)
    assert _count(conn, LINKS_BY_PROJECT, id=project_id) == 1


def test_import_rejects_asset_with_wrong_sha(
    conn: Connection,
    tmp_path: Path,
    project_id: uuid.UUID,
    make_reference: Callable[..., uuid.UUID],
) -> None:
    store = BlobStore(tmp_path / "storage")
    blob = store.put_bytes(png_bytes(), suffix=".png")
    make_reference(
        project_id=project_id,
        status="approved",
        storage_key=blob.storage_key,
        sha256="0" * 64,
        metadata={"original_name": "01_vocalist_clean.png"},
    )
    manifest = parse_manifest(_manifest([_shot(1)]))

    with Session(bind=conn) as session:
        report = import_series(
            session, store, manifest, ImportOptions(project_title="Project A"), apply=True
        )

    assert any("sha256" in item for item in report.warnings)
    assert any("не прошло проверку" in item for item in report.errors)
    assert _count(conn, LINKS_BY_PROJECT, id=project_id) == 0


def test_import_ignores_reference_of_other_project(
    conn: Connection,
    tmp_path: Path,
    project_id: uuid.UUID,
    second_project_id: uuid.UUID,
    make_reference: Callable[..., uuid.UUID],
) -> None:
    _named_reference(tmp_path, make_reference, second_project_id, "01_vocalist_clean.png")
    manifest = parse_manifest(_manifest([_shot(1)]))
    store = BlobStore(tmp_path / "storage")

    with Session(bind=conn) as session:
        report = import_series(
            session, store, manifest, ImportOptions(project_title="Project A"), apply=True
        )

    assert any("не найден ни в библиотеке" in item for item in report.errors)
    assert _count(conn, LINKS_BY_PROJECT, id=project_id) == 0


def test_import_creates_new_prompt_version_only_when_text_changes(
    conn: Connection,
    tmp_path: Path,
    project_id: uuid.UUID,
    make_reference: Callable[..., uuid.UUID],
) -> None:
    _named_reference(tmp_path, make_reference, project_id, "01_vocalist_clean.png")
    store = BlobStore(tmp_path / "storage")
    options = ImportOptions(project_title="Project A")

    with Session(bind=conn) as session:
        import_series(
            session, store, parse_manifest(_manifest([_shot(1)])), options, apply=True
        )
    with Session(bind=conn) as session:
        import_series(
            session,
            store,
            parse_manifest(_manifest([_shot(1, prompt_original="новый текст")])),
            options,
            apply=True,
        )
    with Session(bind=conn) as session:
        report = import_series(
            session,
            store,
            parse_manifest(_manifest([_shot(1, prompt_original="новый текст")])),
            options,
            apply=True,
        )

    rows = conn.execute(
        text(
            "SELECT p.version, p.prompt FROM prompt_revisions p"
            " JOIN shots s ON s.id = p.shot_id JOIN scenes sc ON sc.id = s.scene_id"
            " WHERE sc.project_id = :id ORDER BY p.version"
        ),
        {"id": project_id},
    ).all()
    assert [(row.version, row.prompt) for row in rows] == [
        (1, "prompt 1"),
        (2, "новый текст"),
    ]
    assert report.counts().get("prompt", {}).get(CREATE, 0) == 0
    current = conn.scalar(
        text(
            "SELECT s.current_prompt_revision_id FROM shots s"
            " JOIN scenes sc ON sc.id = s.scene_id WHERE sc.project_id = :id"
        ),
        {"id": project_id},
    )
    latest = conn.scalar(
        text(
            "SELECT p.id FROM prompt_revisions p"
            " JOIN shots s ON s.id = p.shot_id JOIN scenes sc ON sc.id = s.scene_id"
            " WHERE sc.project_id = :id AND p.version = 2"
        ),
        {"id": project_id},
    )
    assert current == latest


def test_import_requires_existing_project_without_flag(
    conn: Connection, tmp_path: Path
) -> None:
    manifest = parse_manifest(_manifest([_shot(1)]))
    store = BlobStore(tmp_path / "storage")

    with Session(bind=conn) as session:
        report = import_series(
            session, store, manifest, ImportOptions(project_title="Нет такого"), apply=True
        )

    assert report.project_id is None
    assert any("проект не найден" in item for item in report.errors)

    with Session(bind=conn) as session:
        created = import_series(
            session,
            store,
            manifest,
            ImportOptions(project_title="Нет такого", create_project=True),
            apply=True,
        )

    assert created.project_id is not None
    assert _count(conn, "SELECT count(*) FROM projects WHERE title = 'Нет такого'") == 1
