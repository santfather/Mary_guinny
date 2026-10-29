from __future__ import annotations

import copy

import pytest

from app.config import REPO_ROOT
from app.series_manifest import (
    ManifestError,
    cross_check_queue,
    load_manifest,
    load_queue_csv,
    parse_manifest,
    parse_queue_csv,
    snap_frame_count,
)

MANIFEST_PATH = REPO_ROOT / "docs" / "Nine_Lives_Band_Render_Manifest.json"
QUEUE_PATH = REPO_ROOT / "docs" / "Nine_Lives_Band_Shot_Queue.csv"


def _shot(order: int, key: str | None = None) -> dict[str, object]:
    return {
        "order": order,
        "shot_key": key or f"NLB-{order:02d}",
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


def test_snap_frame_count_keeps_8k_plus_one() -> None:
    assert snap_frame_count(8, 24) == 193
    assert snap_frame_count(7, 24) == 169
    assert (snap_frame_count(8, 24) - 1) % 8 == 0
    assert snap_frame_count(1, 24) == 25
    assert snap_frame_count(60, 24) == 257


def test_parse_manifest_builds_shots_and_references() -> None:
    data = _manifest([_shot(1), _shot(2, "NLB-02")])
    data["shots"].append(
        {
            **_shot(3),
            "category": "story",
            "start_frame_filename": None,
            "reference_filename_from_plan": "Guiness_clean.png",
            "identity_reference_filename": "Guiness_clean.png",
        }
    )

    manifest = parse_manifest(data)

    assert len(manifest.shots) == 3
    assert manifest.reference_names == ("01_vocalist_clean.png", "Guiness_clean.png")
    assert [shot.order for shot in manifest.blocked_shots] == [3]
    assert manifest.effective_fps() == 24
    assert manifest.shots[0].frames(24) == 193
    assert manifest.sha256


def test_parse_manifest_rejects_duplicate_order() -> None:
    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(_manifest([_shot(1), _shot(1, "NLB-01b")]))

    assert any("повторяется" in item for item in excinfo.value.errors)


def test_parse_manifest_rejects_bad_duration() -> None:
    bad = copy.deepcopy(_shot(2))
    bad["target_duration_seconds"] = [9, 3]

    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(_manifest([_shot(1), bad]))

    errors = " ".join(excinfo.value.errors)
    assert "target_duration_seconds" in errors


def test_parse_manifest_rejects_unsupported_schema() -> None:
    data = _manifest([_shot(1)])
    data["schema_version"] = "2.0"

    with pytest.raises(ManifestError) as excinfo:
        parse_manifest(data)

    assert any("schema_version" in item for item in excinfo.value.errors)


def test_cross_check_detects_prompt_drift() -> None:
    manifest = parse_manifest(_manifest([_shot(1)]))
    csv_text = (
        "order,shot_key,title,category,reference_filename_from_plan,start_frame_filename,"
        "identity_reference_filename,prompt_original,status,output_name_prefix\n"
        "1,NLB-01,Шот 1,performer,01_vocalist_clean.png,01_vocalist_clean.png,,"
        "другой промпт,needs_preflight,NLB_01\n"
    )

    errors = cross_check_queue(manifest, parse_queue_csv(csv_text))

    assert len(errors) == 1
    assert "prompt_original" in errors[0]


def test_cross_check_ignores_bom() -> None:
    manifest = parse_manifest(_manifest([_shot(1)]))
    csv_text = (
        "\ufefforder,shot_key,title,category,reference_filename_from_plan,start_frame_filename,"
        "identity_reference_filename,prompt_original,status,output_name_prefix\n"
        "1,NLB-01,Шот 1,performer,01_vocalist_clean.png,01_vocalist_clean.png,,"
        "prompt 1,needs_preflight,NLB_01\n"
    )

    assert cross_check_queue(manifest, parse_queue_csv(csv_text)) == []


@pytest.mark.skipif(not MANIFEST_PATH.is_file(), reason="манифест ещё не добавлен")
def test_real_manifest_matches_real_queue() -> None:
    manifest = load_manifest(MANIFEST_PATH)

    assert len(manifest.shots) == 30
    assert len(manifest.reference_names) == 7
    assert [shot.order for shot in manifest.shots] == list(range(1, 31))
    assert len(manifest.blocked_shots) == 7
    assert manifest.target_aspect_ratio == "9:16"
    assert manifest.audio_master_duration_seconds == 204

    if QUEUE_PATH.is_file():
        assert cross_check_queue(manifest, load_queue_csv(QUEUE_PATH)) == []
