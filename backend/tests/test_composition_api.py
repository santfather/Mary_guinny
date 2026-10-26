"""WP-05: ревизии композиции, approve/supersede и render."""

from __future__ import annotations

import io

from PIL import Image
from sqlalchemy import text

from app.storage import BlobStore


def _layer(asset_id, z_index: int = 0, **overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "reference_asset_id": str(asset_id),
        "z_index": z_index,
    }
    payload.update(overrides)
    return payload


def test_composition_revisions_and_layer_rules(
    api_client,
    project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
) -> None:
    approved = make_png_reference(project_id=project_id, character_id=character_id)
    draft = make_png_reference(
        project_id=project_id, character_id=character_id, status="draft"
    )
    location = make_png_reference(project_id=project_id, location_id=location_id)
    uploaded = make_png_reference(project_id=project_id)

    body = {
        "width": 64,
        "height": 64,
        "layers": [_layer(location, 0), _layer(approved, 1, x=4, y=4, scale=0.5)],
    }
    first = api_client.post(f"/api/shots/{shot_id}/compositions", json=body)
    assert first.status_code == 201
    assert first.json()["revision"] == 1
    assert first.json()["status"] == "draft"
    assert first.json()["layer_count"] == 2
    assert first.json()["preview_artifact_id"] is None
    assert [layer["z_index"] for layer in first.json()["layers"]] == [0, 1]
    assert first.json()["layers"][1]["reference"]["id"] == str(approved)

    second = api_client.post(f"/api/shots/{shot_id}/compositions", json=body)
    assert second.status_code == 201
    assert second.json()["revision"] == 2

    listed = api_client.get(f"/api/shots/{shot_id}/compositions")
    assert listed.status_code == 200
    assert [item["revision"] for item in listed.json()] == [2, 1]

    detail = api_client.get(f"/api/shots/{shot_id}/compositions/1")
    assert detail.status_code == 200
    assert len(detail.json()["layers"]) == 2

    updated = api_client.put(
        f"/api/shots/{shot_id}/compositions/1",
        json={
            "width": 80,
            "height": 60,
            "layers": [
                _layer(
                    location,
                    0,
                    x=5,
                    y=6,
                    scale=2,
                    rotation=15,
                    opacity=0.5,
                ),
                _layer(uploaded, 5),
            ],
        },
    )
    assert updated.status_code == 200
    payload = updated.json()
    assert (payload["width"], payload["height"]) == (80, 60)
    assert payload["layers"][0]["x"] == 5.0
    assert payload["layers"][0]["scale"] == 2.0
    assert payload["layers"][0]["rotation"] == 15.0
    assert payload["layers"][0]["opacity"] == 0.5
    assert payload["layers"][1]["z_index"] == 5

    duplicate_z = api_client.post(
        f"/api/shots/{shot_id}/compositions",
        json={"width": 16, "height": 16, "layers": [_layer(approved, 1), _layer(location, 1)]},
    )
    assert duplicate_z.status_code == 422

    unapproved = api_client.post(
        f"/api/shots/{shot_id}/compositions",
        json={"width": 16, "height": 16, "layers": [_layer(draft, 0)]},
    )
    assert unapproved.status_code == 409

    unknown_asset = api_client.post(
        f"/api/shots/{shot_id}/compositions",
        json={"width": 16, "height": 16, "layers": [_layer("00000000-0000-0000-0000-000000000000", 0)]},
    )
    assert unknown_asset.status_code == 404

    too_large = api_client.post(
        f"/api/shots/{shot_id}/compositions",
        json={"width": 5000, "height": 5000, "layers": [_layer(approved, 0)]},
    )
    assert too_large.status_code == 413

    empty = api_client.post(
        f"/api/shots/{shot_id}/compositions",
        json={"width": 16, "height": 16, "layers": []},
    )
    assert empty.status_code == 422

    assert api_client.get(f"/api/shots/{shot_id}/compositions/9").status_code == 404
    assert (
        api_client.put(
            f"/api/shots/{shot_id}/compositions/9",
            json={"width": 16, "height": 16, "layers": [_layer(approved, 0)]},
        ).status_code
        == 404
    )


def test_approve_requires_render_and_supersede_is_explicit(
    api_client, project_id, shot_id, character_id, make_png_reference
) -> None:
    asset = make_png_reference(project_id=project_id, character_id=character_id)
    body = {"width": 32, "height": 32, "layers": [_layer(asset, 0)]}

    assert api_client.post(f"/api/shots/{shot_id}/compositions", json=body).status_code == 201
    unreleased = api_client.post(f"/api/shots/{shot_id}/compositions/1/approve")
    assert unreleased.status_code == 409
    assert "render" in unreleased.json()["detail"]

    assert api_client.post(f"/api/shots/{shot_id}/compositions/1/render").status_code == 200
    approved = api_client.post(f"/api/shots/{shot_id}/compositions/1/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_at"] is not None
    assert (
        api_client.post(f"/api/shots/{shot_id}/compositions/1/approve").json()["status"]
        == "approved"
    )

    assert api_client.post(f"/api/shots/{shot_id}/compositions", json=body).status_code == 201
    assert api_client.post(f"/api/shots/{shot_id}/compositions/2/render").status_code == 200
    blocked = api_client.post(f"/api/shots/{shot_id}/compositions/2/approve")
    assert blocked.status_code == 409
    assert "supersede" in blocked.json()["detail"]

    superseded = api_client.post(f"/api/shots/{shot_id}/compositions/1/supersede")
    assert superseded.status_code == 200
    assert superseded.json()["status"] == "superseded"
    assert (
        api_client.post(f"/api/shots/{shot_id}/compositions/1/supersede").json()["status"]
        == "superseded"
    )

    assert api_client.post(f"/api/shots/{shot_id}/compositions/2/approve").status_code == 200
    assert api_client.post(f"/api/shots/{shot_id}/compositions/2/supersede").status_code == 200
    assert (
        api_client.post(f"/api/shots/{shot_id}/compositions/2/approve").status_code == 409
    )

    assert api_client.post(f"/api/shots/{shot_id}/compositions", json=body).status_code == 201
    assert api_client.post(f"/api/shots/{shot_id}/compositions/3/approve").status_code == 409
    draft = api_client.post(f"/api/shots/{shot_id}/compositions/3/supersede")
    assert draft.status_code == 409


def test_render_creates_artifact_and_keeps_preview_pointer(
    api_client,
    conn,
    tmp_path,
    project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
) -> None:
    character = make_png_reference(project_id=project_id, character_id=character_id)
    location = make_png_reference(project_id=project_id, location_id=location_id)
    body = {
        "width": 40,
        "height": 24,
        "layers": [_layer(location, 0), _layer(character, 1, x=2, y=2)],
    }
    assert api_client.post(f"/api/shots/{shot_id}/compositions", json=body).status_code == 201

    rendered = api_client.post(f"/api/shots/{shot_id}/compositions/1/render")
    assert rendered.status_code == 200
    payload = rendered.json()
    assert payload["width"] == 40
    assert payload["height"] == 24
    assert payload["warnings"] == []
    assert payload["preview_artifact_id"] == payload["artifact_id"]

    # Артефакт создан в тестовой транзакции, поэтому content_url читаем через storage.
    storage_key = conn.execute(
        text("SELECT storage_key FROM artifacts WHERE id = :id"),
        {"id": payload["artifact_id"]},
    ).scalar_one()
    image = Image.open(io.BytesIO(BlobStore(tmp_path / "storage").read_bytes(storage_key)))
    assert image.mode == "RGBA"
    assert image.size == (40, 24)

    composition = api_client.get(f"/api/shots/{shot_id}/compositions/1").json()
    assert composition["preview_artifact_id"] == payload["artifact_id"]

    repeated = api_client.post(f"/api/shots/{shot_id}/compositions/1/render")
    assert repeated.status_code == 200
    assert repeated.json()["artifact_id"] != payload["artifact_id"]
    assert repeated.json()["preview_artifact_id"] == payload["artifact_id"]
    assert (
        api_client.get(f"/api/shots/{shot_id}").json()["start_keyframe_artifact_id"] is None
    )

    opaque = make_png_reference(
        project_id=project_id,
        character_id=character_id,
        has_alpha=False,
    )
    assert (
        api_client.post(
            f"/api/shots/{shot_id}/compositions",
            json={"width": 24, "height": 24, "layers": [_layer(opaque, 0)]},
        ).status_code
        == 201
    )
    warned = api_client.post(f"/api/shots/{shot_id}/compositions/2/render")
    assert warned.status_code == 200
    assert [item["code"] for item in warned.json()["warnings"]] == [
        "opaque_character_reference"
    ]
