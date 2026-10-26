"""Ограничения целостности WP-02: владелец, проект, ревизии и слои."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import Connection, text

ASSET_INSERT = (
    "INSERT INTO reference_assets"
    " (id, project_id, kind, character_id, location_id, prop_id, storage_key, sha256, mime_type)"
    " VALUES (:id, :project_id, :kind, :character_id, :location_id, :prop_id,"
    " :storage_key, :sha256, 'image/png')"
)

LAYER_INSERT = (
    "INSERT INTO shot_composition_layers"
    " (id, project_id, composition_id, reference_asset_id, z_index, x, y, scale, rotation, opacity)"
    " VALUES (:id, :project_id, :composition_id, :reference_asset_id, :z_index,"
    " :x, :y, :scale, :rotation, :opacity)"
)

ARTIFACT_INSERT = (
    "INSERT INTO artifacts"
    " (id, source, kind, storage_key, sha256, bytes, mime_type, shot_composition_id)"
    " VALUES (:id, 'composition', 'keyframe', :storage_key, :sha256, 1, 'image/png',"
    " :shot_composition_id)"
)


def _sha() -> str:
    return uuid.uuid4().hex * 2


def _asset_params(
    project_id: uuid.UUID,
    *,
    kind: str,
    character_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    prop_id: uuid.UUID | None = None,
    sha256: str | None = None,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "project_id": project_id,
        "kind": kind,
        "character_id": character_id,
        "location_id": location_id,
        "prop_id": prop_id,
        "storage_key": f"projects/{project_id}/refs/{uuid.uuid4()}.png",
        "sha256": sha256 or _sha(),
    }


def _layer_params(
    project_id: uuid.UUID,
    composition_id: uuid.UUID,
    reference_asset_id: uuid.UUID,
    *,
    z_index: int = 0,
    scale: float = 1.0,
    opacity: float = 1.0,
) -> dict[str, object]:
    return {
        "id": uuid.uuid4(),
        "project_id": project_id,
        "composition_id": composition_id,
        "reference_asset_id": reference_asset_id,
        "z_index": z_index,
        "x": 0,
        "y": 0,
        "scale": scale,
        "rotation": 0,
        "opacity": opacity,
    }


def test_owner_matrix_accepts_matching_kinds(
    project_id: uuid.UUID,
    character_id: uuid.UUID,
    location_id: uuid.UUID,
    prop_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
) -> None:
    make_asset(project_id=project_id, kind="character_reference", character_id=character_id)
    make_asset(project_id=project_id, kind="location_reference", location_id=location_id)
    make_asset(project_id=project_id, kind="prop_reference", prop_id=prop_id)
    make_asset(project_id=project_id, kind="uploaded")


def test_owner_must_match_kind(
    project_id: uuid.UUID,
    character_id: uuid.UUID,
    location_id: uuid.UUID,
    prop_id: uuid.UUID,
    expect_violation: Callable[..., None],
) -> None:
    cases = (
        _asset_params(project_id, kind="character_reference"),
        _asset_params(project_id, kind="character_reference", location_id=location_id),
        _asset_params(project_id, kind="location_reference"),
        _asset_params(project_id, kind="location_reference", prop_id=prop_id),
        _asset_params(project_id, kind="prop_reference"),
        _asset_params(project_id, kind="prop_reference", character_id=character_id),
        _asset_params(project_id, kind="uploaded", character_id=character_id),
        _asset_params(project_id, kind="uploaded", location_id=location_id),
        _asset_params(project_id, kind="uploaded", prop_id=prop_id),
    )

    for params in cases:
        expect_violation(
            ASSET_INSERT, params, "ck_reference_assets_owner_matches_kind"
        )


def test_owner_of_another_project_is_rejected(
    second_project_id: uuid.UUID,
    location_id: uuid.UUID,
    expect_violation: Callable[..., None],
) -> None:
    expect_violation(
        ASSET_INSERT,
        _asset_params(second_project_id, kind="location_reference", location_id=location_id),
        "fk_reference_assets_location_project",
    )


def test_asset_checksum_is_unique_per_project(
    project_id: uuid.UUID,
    second_project_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    checksum = _sha()
    make_asset(project_id=project_id, sha256=checksum)

    expect_violation(
        ASSET_INSERT,
        _asset_params(project_id, kind="uploaded", sha256=checksum),
        "uq_reference_assets_project_sha256",
    )

    make_asset(project_id=second_project_id, sha256=checksum)


def test_shot_cannot_reference_asset_from_another_project(
    project_id: uuid.UUID,
    second_project_id: uuid.UUID,
    shot_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    foreign_asset = make_asset(project_id=second_project_id)

    expect_violation(
        "INSERT INTO shot_references"
        " (id, project_id, shot_id, reference_asset_id, purpose)"
        " VALUES (:id, :project_id, :shot_id, :asset, 'style')",
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "shot_id": shot_id,
            "asset": foreign_asset,
        },
        "fk_shot_references_asset_project",
    )


def test_shot_reference_purpose_is_validated(
    project_id: uuid.UUID,
    shot_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    asset = make_asset(project_id=project_id)

    expect_violation(
        "INSERT INTO shot_references"
        " (id, project_id, shot_id, reference_asset_id, purpose)"
        " VALUES (:id, :project_id, :shot_id, :asset, 'unknown')",
        {
            "id": uuid.uuid4(),
            "project_id": project_id,
            "shot_id": shot_id,
            "asset": asset,
        },
        "ck_shot_references_purpose",
    )


def test_composition_layer_cannot_use_asset_from_another_project(
    project_id: uuid.UUID,
    second_project_id: uuid.UUID,
    shot_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    make_composition: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    composition = make_composition(project_id=project_id, shot_id=shot_id)
    foreign_asset = make_asset(project_id=second_project_id)

    expect_violation(
        LAYER_INSERT,
        _layer_params(project_id, composition, foreign_asset),
        "fk_composition_layers_asset_project",
    )


def test_layer_order_is_unique_within_composition(
    conn: Connection,
    project_id: uuid.UUID,
    shot_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    make_composition: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    composition = make_composition(project_id=project_id, shot_id=shot_id)
    first_asset = make_asset(project_id=project_id)
    second_asset = make_asset(project_id=project_id)

    conn.execute(
        text(LAYER_INSERT),
        _layer_params(project_id, composition, first_asset, z_index=0),
    )

    expect_violation(
        LAYER_INSERT,
        _layer_params(project_id, composition, second_asset, z_index=0),
        "uq_composition_layers_z_index",
    )


def test_layer_geometry_checks(
    project_id: uuid.UUID,
    shot_id: uuid.UUID,
    make_asset: Callable[..., uuid.UUID],
    make_composition: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    composition = make_composition(project_id=project_id, shot_id=shot_id)
    asset = make_asset(project_id=project_id)

    expect_violation(
        LAYER_INSERT,
        _layer_params(project_id, composition, asset, z_index=-1),
        "ck_composition_layers_z_index_non_negative",
    )
    expect_violation(
        LAYER_INSERT,
        _layer_params(project_id, composition, asset, scale=0),
        "ck_composition_layers_scale_positive",
    )
    expect_violation(
        LAYER_INSERT,
        _layer_params(project_id, composition, asset, opacity=1.5),
        "ck_composition_layers_opacity_range",
    )


def test_artifact_composition_link_is_enforced(
    conn: Connection,
    project_id: uuid.UUID,
    shot_id: uuid.UUID,
    make_composition: Callable[..., uuid.UUID],
    expect_violation: Callable[..., None],
) -> None:
    composition = make_composition(project_id=project_id, shot_id=shot_id)
    conn.execute(
        text(ARTIFACT_INSERT),
        {
            "id": uuid.uuid4(),
            "storage_key": f"compositions/{composition}.png",
            "sha256": _sha(),
            "shot_composition_id": composition,
        },
    )

    expect_violation(
        ARTIFACT_INSERT,
        {
            "id": uuid.uuid4(),
            "storage_key": f"compositions/{uuid.uuid4()}.png",
            "sha256": _sha(),
            "shot_composition_id": uuid.uuid4(),
        },
        "fk_artifacts_shot_composition",
    )
