from __future__ import annotations

import uuid

from app.storage import BlobStore


def test_projects_and_character_list(
    api_client, project_id, character_id, make_reference, make_bible
) -> None:
    make_reference(project_id=project_id, character_id=character_id)
    make_reference(project_id=project_id, character_id=character_id, status="approved")
    make_bible(project_id=project_id, character_id=character_id, body="# Guinness")

    projects = api_client.get("/api/projects")
    assert projects.status_code == 200
    titles = [item["title"] for item in projects.json()]
    assert "Project A" in titles
    assert str(project_id) in [item["id"] for item in projects.json()]

    response = api_client.get(f"/api/projects/{project_id}/characters")
    assert response.status_code == 200
    items = response.json()
    assert len(items) == 1
    character = items[0]
    assert character["slug"] == "guinness"
    assert character["kind"] == "cat"
    assert character["reference_count"] == 2
    assert character["approved_reference_count"] == 1
    assert character["bible_version_count"] == 1
    assert character["latest_bible_version"] == 1
    assert character["latest_bible_status"] == "draft"

    assert api_client.get(f"/api/projects/{project_id}/characters?kind=cat").json() == items
    assert api_client.get(f"/api/projects/{project_id}/characters?kind=human").json() == []

    missing = api_client.get(f"/api/projects/{uuid.uuid4()}/characters")
    assert missing.status_code == 404


def test_character_detail_and_bible(
    api_client, project_id, character_id, make_reference, make_bible
) -> None:
    make_bible(
        project_id=project_id,
        character_id=character_id,
        version=1,
        body="# Guinness\n\nРыжий кот.",
    )
    reference_id = make_reference(
        project_id=project_id,
        character_id=character_id,
        view="front",
        metadata={"has_alpha": False},
    )

    detail = api_client.get(f"/api/characters/{character_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["name"] == "Guinness"
    assert payload["reference_count"] == 1
    assert len(payload["bible_versions"]) == 1
    assert payload["bible_versions"][0]["version"] == 1

    bible = api_client.get(f"/api/characters/{character_id}/bible")
    assert bible.status_code == 200
    versions = bible.json()
    assert len(versions) == 1
    assert versions[0]["body"].startswith("# Guinness")
    assert versions[0]["status"] == "draft"
    assert versions[0]["source"] == "import"

    references = api_client.get(f"/api/characters/{character_id}/references")
    assert references.status_code == 200
    asset = references.json()[0]
    assert asset["id"] == str(reference_id)
    assert asset["has_alpha"] is False
    assert asset["content_url"] == f"/api/reference-assets/{reference_id}/content"

    assert api_client.get(f"/api/characters/{uuid.uuid4()}").status_code == 404
    assert api_client.get(f"/api/characters/{uuid.uuid4()}/bible").status_code == 404
    assert api_client.get(f"/api/characters/{uuid.uuid4()}/references").status_code == 404


def test_reference_filters(api_client, project_id, character_id, make_reference) -> None:
    make_reference(
        project_id=project_id, character_id=character_id, view="front", pose="sit"
    )
    make_reference(
        project_id=project_id,
        character_id=character_id,
        view="front",
        pose="stand",
        status="approved",
    )
    make_reference(
        project_id=project_id, character_id=character_id, view="side", pose="sit"
    )

    base = f"/api/characters/{character_id}/references"
    assert len(api_client.get(base).json()) == 3
    assert len(api_client.get(f"{base}?view=front").json()) == 2
    assert len(api_client.get(f"{base}?pose=sit").json()) == 2
    assert len(api_client.get(f"{base}?view=front&pose=sit").json()) == 1
    assert len(api_client.get(f"{base}?status=approved").json()) == 1
    assert api_client.get(f"{base}?status=draft&view=side").json()[0]["pose"] == "sit"
    assert api_client.get(f"{base}?view=unknown").status_code == 422


def test_reference_content_is_served_from_storage(
    api_client, project_id, character_id, make_reference, tmp_path
) -> None:
    payload = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    store = BlobStore(tmp_path / "storage")
    blob = store.put_bytes(payload, suffix=".png")
    asset_id = make_reference(
        project_id=project_id,
        character_id=character_id,
        storage_key=blob.storage_key,
        sha256=blob.sha256,
        metadata={"has_alpha": True},
    )

    metadata = api_client.get(f"/api/reference-assets/{asset_id}")
    assert metadata.status_code == 200
    assert metadata.json()["has_alpha"] is True
    assert metadata.json()["status"] == "draft"

    content = api_client.get(f"/api/reference-assets/{asset_id}/content")
    assert content.status_code == 200
    assert content.content == payload
    assert content.headers["content-type"] == "image/png"

    broken_id = make_reference(
        project_id=project_id,
        character_id=character_id,
        storage_key="blobs/aa/missing.png",
    )
    missing = api_client.get(f"/api/reference-assets/{broken_id}/content")
    assert missing.status_code == 404

    assert api_client.get(f"/api/reference-assets/{uuid.uuid4()}").status_code == 404


def test_locations_and_props(
    api_client, project_id, location_id, prop_id, make_reference
) -> None:
    make_reference(project_id=project_id, location_id=location_id)
    make_reference(project_id=project_id, prop_id=prop_id)

    locations = api_client.get(f"/api/projects/{project_id}/locations")
    assert locations.status_code == 200
    assert locations.json() == [
        {
            "id": str(location_id),
            "slug": "living-room",
            "name": "Living room",
            "description": None,
            "status": "draft",
            "reference_count": 1,
        }
    ]

    location = api_client.get(f"/api/locations/{location_id}")
    assert location.status_code == 200
    assert len(location.json()["references"]) == 1
    assert location.json()["references"][0]["kind"] == "location_reference"

    props = api_client.get(f"/api/projects/{project_id}/props")
    assert props.status_code == 200
    assert props.json()[0]["reference_count"] == 1

    prop = api_client.get(f"/api/props/{prop_id}")
    assert prop.status_code == 200
    assert prop.json()["references"][0]["kind"] == "prop_reference"

    assert api_client.get(f"/api/locations/{uuid.uuid4()}").status_code == 404
    assert api_client.get(f"/api/props/{uuid.uuid4()}").status_code == 404
    assert api_client.get(f"/api/projects/{uuid.uuid4()}/locations").status_code == 404
    assert api_client.get(f"/api/projects/{uuid.uuid4()}/props").status_code == 404
