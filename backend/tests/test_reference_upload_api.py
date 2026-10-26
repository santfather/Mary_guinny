"""WP-05A: загрузка референсов проекта в существующий BlobStore."""

from __future__ import annotations

import hashlib
import io
import uuid

from PIL import Image
from sqlalchemy import text

from app.api.deps import get_settings
from app.config import Settings


def _png(color=(255, 0, 0, 255), size=(32, 24), mode: str = "RGBA") -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(size=(40, 20)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (0, 128, 255)).save(buffer, format="JPEG")
    return buffer.getvalue()


def _upload(client, project_id, data: bytes, **params):
    return client.post(
        f"/api/projects/{project_id}/references",
        params=params,
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )


def test_upload_png_creates_draft_reference(
    api_client, project_id, character_id
) -> None:
    data = _png()
    response = _upload(
        api_client,
        project_id,
        data,
        kind="character_reference",
        character_id=str(character_id),
        view="front",
        pose="stand",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["kind"] == "character_reference"
    assert payload["status"] == "draft"
    assert payload["view"] == "front"
    assert payload["pose"] == "stand"
    assert (payload["width"], payload["height"]) == (32, 24)
    assert payload["mime_type"] == "image/png"
    assert payload["has_alpha"] is True
    assert payload["character_id"] == str(character_id)
    assert payload["location_id"] is None
    assert payload["sha256"] == hashlib.sha256(data).hexdigest()

    content = api_client.get(payload["content_url"])
    assert content.status_code == 200
    assert content.content == data


def test_duplicate_upload_same_owner_returns_existing(
    api_client, project_id, character_id
) -> None:
    data = _png()
    params = {"kind": "character_reference", "character_id": str(character_id)}

    first = _upload(api_client, project_id, data, **params)
    second = _upload(api_client, project_id, data, **params)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["status"] == "draft"


def test_duplicate_upload_for_another_owner_conflicts(
    api_client, conn, project_id, character_id
) -> None:
    other_character = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO characters (id, project_id, slug, name, kind)"
            " VALUES (:id, :project_id, 'marija', 'Marija', 'human')"
        ),
        {"id": other_character, "project_id": project_id},
    )
    data = _png()

    first = _upload(
        api_client,
        project_id,
        data,
        kind="character_reference",
        character_id=str(character_id),
    )
    assert first.status_code == 201

    conflict = _upload(
        api_client,
        project_id,
        data,
        kind="character_reference",
        character_id=str(other_character),
    )
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert detail["error"] == "duplicate_reference"
    assert detail["reference_asset_id"] == first.json()["id"]


def test_jpeg_upload_is_stored_without_alpha(
    api_client, conn, project_id, location_id
) -> None:
    response = _upload(
        api_client,
        project_id,
        _jpeg(),
        kind="location_reference",
        location_id=str(location_id),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["mime_type"] == "image/jpeg"
    assert payload["has_alpha"] is False
    assert payload["location_id"] == str(location_id)
    assert (payload["width"], payload["height"]) == (40, 20)

    storage_key = conn.execute(
        text("SELECT storage_key FROM reference_assets WHERE id = :id"),
        {"id": payload["id"]},
    ).scalar_one()
    assert storage_key.endswith(".jpg")


def test_upload_rejects_empty_and_non_image_bodies(api_client, project_id) -> None:
    empty = _upload(api_client, project_id, b"", kind="uploaded")
    assert empty.status_code == 422
    assert empty.json()["detail"] == "empty body"

    garbage = _upload(api_client, project_id, b"not an image", kind="uploaded")
    assert garbage.status_code == 422

    truncated = _upload(api_client, project_id, _png()[:20], kind="uploaded")
    assert truncated.status_code == 422


def test_upload_validates_project_and_owner(
    api_client, second_project_id, project_id, character_id, location_id
) -> None:
    data = _png()

    assert (
        _upload(
            api_client,
            uuid.uuid4(),
            data,
            kind="character_reference",
            character_id=str(character_id),
        ).status_code
        == 404
    )

    missing_owner = _upload(api_client, project_id, data, kind="character_reference")
    assert missing_owner.status_code == 422
    assert "character_id" in missing_owner.json()["detail"]

    wrong_owner = _upload(
        api_client,
        project_id,
        data,
        kind="character_reference",
        character_id=str(character_id),
        location_id=str(location_id),
    )
    assert wrong_owner.status_code == 422
    assert "another owner" in wrong_owner.json()["detail"]

    uploaded_with_owner = _upload(
        api_client,
        project_id,
        data,
        kind="uploaded",
        character_id=str(character_id),
    )
    assert uploaded_with_owner.status_code == 422
    assert "must not have an owner" in uploaded_with_owner.json()["detail"]

    foreign_owner = _upload(
        api_client,
        second_project_id,
        data,
        kind="location_reference",
        location_id=str(location_id),
    )
    assert foreign_owner.status_code == 404

    assert (
        _upload(api_client, project_id, data, kind="avatar").status_code == 422
    )


def test_upload_rejects_body_over_limit(api_client, project_id, tmp_path) -> None:
    api_client.app.dependency_overrides[get_settings] = lambda: Settings(
        storage_root=tmp_path / "storage", reference_upload_max_bytes=16
    )
    try:
        response = _upload(api_client, project_id, _png(), kind="uploaded")
        assert response.status_code == 413
        assert "too large" in response.json()["detail"]
    finally:
        api_client.app.dependency_overrides.pop(get_settings, None)


def test_front_reference_can_be_selected_and_approved(
    api_client, project_id, character_id
) -> None:
    uploaded = _upload(
        api_client,
        project_id,
        _png(color=(10, 20, 30, 255)),
        kind="character_reference",
        character_id=str(character_id),
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["view"] is None

    labelled = api_client.patch(
        f"/api/reference-assets/{uploaded.json()['id']}", json={"view": "front"}
    )
    assert labelled.status_code == 200
    assert labelled.json()["view"] == "front"
    assert labelled.json()["status"] == "draft"

    approved = api_client.post(
        f"/api/reference-assets/{uploaded.json()['id']}/approve"
    )
    assert approved.status_code == 200
    assert approved.json()["view"] == "front"

    relabel = api_client.patch(
        f"/api/reference-assets/{uploaded.json()['id']}", json={"view": "side"}
    )
    assert relabel.status_code == 409

    assert (
        api_client.patch(
            f"/api/reference-assets/{uploaded.json()['id']}", json={"view": "diagonal"}
        ).status_code
        == 422
    )


def test_uploaded_reference_is_usable_in_scene_plan(
    api_client, project_id, shot_id
) -> None:
    uploaded = _upload(api_client, project_id, _png(), kind="uploaded", role="look")
    assert uploaded.status_code == 201
    assert uploaded.json()["character_id"] is None
    assert uploaded.json()["location_id"] is None

    plan = api_client.post(
        f"/api/shots/{shot_id}/scene-plans",
        json={
            "plan": {
                "canvas": {"width": 768, "height": 512},
                "references": [
                    {
                        "asset_id": uploaded.json()["id"],
                        "role": "style",
                        "alias": "look_ref",
                    }
                ],
                "motion_prompt": "wide shot, static camera",
            }
        },
    )
    assert plan.status_code == 201
    assert plan.json()["plan"]["references"][0]["entity_id"] is None
