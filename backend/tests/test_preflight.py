from __future__ import annotations

import io
import uuid
from collections.abc import Callable
from pathlib import Path

from PIL import Image
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.preflight import FAIL, OK, WARN, run_preflight
from app.series_import import ImportOptions, import_series
from app.series_manifest import parse_manifest
from app.storage import BlobStore


def png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (64, 48), (10, 20, 30, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _shot(order: int, reference: str) -> dict[str, object]:
    return {
        "order": order,
        "shot_key": f"NLB-{order:02d}",
        "title": f"Шот {order}",
        "category": "performer",
        "reference_filename_from_plan": reference,
        "start_frame_filename": reference,
        "identity_reference_filename": None,
        "prompt_original": f"prompt {order}",
        "target_duration_seconds": [7, 8],
        "status": "needs_preflight",
        "approved": False,
        "seed": None,
        "workflow_version": None,
        "output_name_prefix": f"NLB_{order:02d}",
    }


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


def test_preflight_accepts_portrait_8_seconds_and_reports_start_frames_as_warning(
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
        sha256=blob.sha256,
        metadata={"original_name": "01_vocalist_clean.png"},
    )
    manifest = parse_manifest(_manifest([_shot(1, "01_vocalist_clean.png")]))

    with Session(bind=conn) as session:
        import_series(
            session, store, manifest, ImportOptions(project_title="Project A"), apply=True
        )
    with Session(bind=conn) as session:
        report = run_preflight(session, store, manifest, project_title="Project A")

    checks = {check.name: check for check in report.checks}
    # 193 = 8k+1 при шаге 8: нода LTX2MLX принимает такое число кадров.
    assert checks["video_params"].status == WARN
    assert "1080x1920" in checks["video_params"].detail
    assert "193 кадров @ 24 fps" in checks["video_params"].detail
    assert checks["references"].status == OK
    assert checks["shots"].status == OK
    assert checks["start_frames"].status == WARN
    assert report.status != FAIL


def test_preflight_marks_shots_blocked_without_extending_status_enum(
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
        sha256=blob.sha256,
        metadata={"original_name": "01_vocalist_clean.png"},
    )
    manifest = parse_manifest(
        _manifest(
            [
                _shot(1, "01_vocalist_clean.png"),
                _shot(2, "wide_cinematic_concert_stage_scene_a_realistic.png"),
            ]
        )
    )

    with Session(bind=conn) as session:
        import_series(
            session, store, manifest, ImportOptions(project_title="Project A"), apply=True
        )
    with Session(bind=conn) as session:
        report = run_preflight(session, store, manifest, project_title="Project A")

    checks = {check.name: check for check in report.checks}
    assert checks["references"].status == FAIL
    assert "NLB-02" in checks["references"].detail
    assert [item["blocked"] for item in report.shots] == [
        "missing_start_frame",
        "missing_reference",
    ]
    assert report.status == FAIL
