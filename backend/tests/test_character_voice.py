"""WP-M6: голосовой референс персонажа и запрет multi-view стартового кадра."""

from __future__ import annotations

import io
import uuid
import wave

import pytest
from PIL import Image
from sqlalchemy import Connection, text


def _wav(seconds: float = 0.5, rate: int = 8000) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buffer.getvalue()


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(
    api_client, character_id: uuid.UUID, data: bytes, mime: str = "audio/wav"
):
    return api_client.post(
        f"/api/characters/{character_id}/voice",
        content=data,
        headers={"Content-Type": mime},
    )


def test_upload_voice_creates_draft_reference(api_client, character_id) -> None:
    data = _wav()

    response = _upload(api_client, character_id, data)

    assert response.status_code == 201
    payload = response.json()
    assert payload["role"] == "voice"
    assert payload["kind"] == "character_reference"
    assert payload["status"] == "draft"
    assert payload["character_id"] == str(character_id)
    assert payload["mime_type"] == "audio/wav"
    assert payload["width"] is None
    assert payload["height"] is None
    assert payload["multi_view"] is False
    assert payload["duration_s"] == pytest.approx(0.5, abs=0.05)

    content = api_client.get(payload["content_url"])
    assert content.status_code == 200
    assert content.content == data

    listed = api_client.get(f"/api/characters/{character_id}/references").json()
    assert [item["id"] for item in listed] == [payload["id"]]
    assert listed[0]["role"] == "voice"
    assert listed[0]["duration_s"] == pytest.approx(0.5, abs=0.05)


def test_upload_voice_deduplicates_within_project(
    api_client, conn: Connection, character_id, project_id
) -> None:
    data = _wav()
    first = _upload(api_client, character_id, data)
    assert first.status_code == 201

    repeat = _upload(api_client, character_id, data)
    assert repeat.status_code == 200
    assert repeat.json()["id"] == first.json()["id"]

    other_character = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO characters (id, project_id, slug, name, kind)"
            " VALUES (:id, :project_id, 'drummer', 'Drummer', 'cat')"
        ),
        {"id": other_character, "project_id": project_id},
    )
    conflict = _upload(api_client, other_character, data)
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["reference_asset_id"] == first.json()["id"]


def test_upload_voice_validates_character_type_and_body(
    api_client, character_id
) -> None:
    assert _upload(api_client, uuid.uuid4(), _wav()).status_code == 404
    assert _upload(api_client, character_id, _png(), mime="image/png").status_code == 422
    assert _upload(api_client, character_id, b"").status_code == 422

    not_audio = _upload(api_client, character_id, _png(), mime="audio/wav")
    assert not_audio.status_code == 422

    too_long = _upload(api_client, character_id, _wav(31))
    assert too_long.status_code == 422
    assert "maximum is 30" in too_long.json()["detail"]


def test_voice_reference_is_approved_by_human(api_client, character_id) -> None:
    created = _upload(api_client, character_id, _wav())
    assert created.status_code == 201
    asset_id = created.json()["id"]

    approved = api_client.post(f"/api/reference-assets/{asset_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    # S15: approved-референс нельзя переразметить.
    relabel = api_client.patch(
        f"/api/reference-assets/{asset_id}", json={"expression": "calm"}
    )
    assert relabel.status_code == 409


def test_voice_reference_cannot_be_start_keyframe(api_client, character_id, shot_id) -> None:
    created = _upload(api_client, character_id, _wav())
    asset_id = created.json()["id"]
    assert api_client.post(f"/api/reference-assets/{asset_id}/approve").status_code == 200

    response = api_client.post(
        f"/api/shots/{shot_id}/keyframe", json={"reference_asset_id": asset_id}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "reference asset is not an image"


def test_multi_view_reference_cannot_be_start_keyframe(
    api_client, project_id, shot_id, make_png_reference
) -> None:
    asset_id = make_png_reference(project_id=project_id, status="draft")

    marked = api_client.patch(
        f"/api/reference-assets/{asset_id}", json={"multi_view": True}
    )
    assert marked.status_code == 200
    assert marked.json()["multi_view"] is True
    assert api_client.post(f"/api/reference-assets/{asset_id}/approve").status_code == 200

    response = api_client.post(
        f"/api/shots/{shot_id}/keyframe", json={"reference_asset_id": str(asset_id)}
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "multi-view reference cannot be used as a start frame"


def test_multi_view_flag_can_be_cleared(api_client, project_id, make_png_reference) -> None:
    asset_id = make_png_reference(project_id=project_id, status="draft")

    marked = api_client.patch(
        f"/api/reference-assets/{asset_id}",
        json={"multi_view": True, "expression": "angry"},
    )
    assert marked.status_code == 200
    assert marked.json()["multi_view"] is True
    assert marked.json()["expression"] == "angry"

    cleared = api_client.patch(
        f"/api/reference-assets/{asset_id}", json={"multi_view": False}
    )
    assert cleared.status_code == 200
    assert cleared.json()["multi_view"] is False
    assert cleared.json()["expression"] == "angry"
