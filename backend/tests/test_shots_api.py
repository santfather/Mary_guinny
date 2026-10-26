"""WP-05: сцены, шоты, привязки, keyframe, promote и render-гейт."""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, text


def _attach(client, shot_id, asset_id, purpose: str = "character"):
    return client.post(
        f"/api/shots/{shot_id}/references",
        json={"reference_asset_id": str(asset_id), "purpose": purpose},
    )


def test_scenes_and_shots_crud(api_client, project_id, scene_id, shot_id) -> None:
    scenes = api_client.get(f"/api/projects/{project_id}/scenes")
    assert scenes.status_code == 200
    payload = scenes.json()
    assert len(payload) == 1
    assert payload[0]["id"] == str(scene_id)
    assert payload[0]["sequence_no"] == 1
    assert [shot["id"] for shot in payload[0]["shots"]] == [str(shot_id)]
    assert payload[0]["shots"][0]["project_id"] == str(project_id)

    scene = api_client.get(f"/api/scenes/{scene_id}")
    assert scene.status_code == 200
    assert len(scene.json()["shots"]) == 1

    created = api_client.post(
        f"/api/projects/{project_id}/scenes", json={"title": "Second scene"}
    )
    assert created.status_code == 201
    assert created.json()["sequence_no"] == 2
    assert created.json()["shots"] == []

    shot = api_client.post(
        f"/api/scenes/{created.json()['id']}/shots",
        json={"target_duration_frames": 73, "timeline_fps": 24},
    )
    assert shot.status_code == 201
    assert shot.json()["sequence_no"] == 1
    assert shot.json()["target_duration_frames"] == 73
    assert shot.json()["timeline_fps"] == 24.0
    assert shot.json()["start_keyframe_artifact_id"] is None

    detail = api_client.get(f"/api/shots/{shot.json()['id']}")
    assert detail.status_code == 200
    assert detail.json()["references"] == []
    assert detail.json()["composition_revisions"] == []
    assert detail.json()["attempts"] == []

    assert api_client.get(f"/api/projects/{uuid.uuid4()}/scenes").status_code == 404
    assert api_client.get(f"/api/scenes/{uuid.uuid4()}").status_code == 404
    assert api_client.get(f"/api/shots/{uuid.uuid4()}").status_code == 404
    assert (
        api_client.post(
            f"/api/scenes/{uuid.uuid4()}/shots", json={}
        ).status_code
        == 404
    )


def test_shot_references_attach_detach_and_project_picker(
    api_client,
    project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
    make_reference,
    second_project_id,
) -> None:
    character_ref = make_png_reference(project_id=project_id, character_id=character_id)
    location_ref = make_png_reference(
        project_id=project_id, location_id=location_id, status="draft"
    )

    attached = _attach(api_client, shot_id, character_ref, "character")
    assert attached.status_code == 201
    link = attached.json()
    assert link["purpose"] == "character"
    assert link["reference"]["id"] == str(character_ref)
    assert link["reference"]["content_url"] == (
        f"/api/reference-assets/{character_ref}/content"
    )

    repeated = _attach(api_client, shot_id, character_ref, "character")
    assert repeated.status_code == 201
    assert repeated.json()["id"] == link["id"]

    location_link = _attach(api_client, shot_id, location_ref, "location")
    assert location_link.status_code == 201
    assert location_link.json()["id"] != link["id"]

    listed = api_client.get(f"/api/shots/{shot_id}/references")
    assert listed.status_code == 200
    assert len(listed.json()) == 2

    approved = api_client.get(f"/api/projects/{project_id}/references?status=approved")
    assert approved.status_code == 200
    assert [item["id"] for item in approved.json()] == [str(character_ref)]
    locations = api_client.get(
        f"/api/projects/{project_id}/references?kind=location_reference"
    )
    assert [item["id"] for item in locations.json()] == [str(location_ref)]

    rejected_ref = make_png_reference(
        project_id=project_id, character_id=character_id, status="rejected"
    )
    rejected = _attach(api_client, shot_id, rejected_ref, "character")
    assert rejected.status_code == 409

    foreign_ref = make_reference(project_id=second_project_id)
    foreign = _attach(api_client, shot_id, foreign_ref, "other")
    assert foreign.status_code == 404

    detached = api_client.delete(
        f"/api/shots/{shot_id}/references/{link['id']}"
    )
    assert detached.status_code == 204
    assert len(api_client.get(f"/api/shots/{shot_id}/references").json()) == 1
    assert (
        api_client.delete(f"/api/shots/{shot_id}/references/{link['id']}").status_code
        == 404
    )
    assert api_client.get(f"/api/projects/{uuid.uuid4()}/references").status_code == 404


def test_keyframe_promote_and_render_gate(
    api_client,
    conn: Connection,
    project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
) -> None:
    character_ref = make_png_reference(project_id=project_id, character_id=character_id)
    location_ref = make_png_reference(project_id=project_id, location_id=location_id)
    composition = api_client.post(
        f"/api/shots/{shot_id}/compositions",
        json={
            "width": 64,
            "height": 64,
            "layers": [
                {"reference_asset_id": str(location_ref), "z_index": 0},
                {
                    "reference_asset_id": str(character_ref),
                    "z_index": 1,
                    "x": 8,
                    "y": 8,
                    "scale": 0.5,
                },
            ],
        },
    )
    assert composition.status_code == 201

    assert api_client.post(f"/api/shots/{shot_id}/render").status_code == 409

    not_approved = api_client.post(f"/api/shots/{shot_id}/keyframe", json={})
    assert not_approved.status_code == 409
    assert "approved" in not_approved.json()["detail"]

    render = api_client.post(f"/api/shots/{shot_id}/compositions/1/render")
    assert render.status_code == 200
    approve = api_client.post(f"/api/shots/{shot_id}/compositions/1/approve")
    assert approve.status_code == 200

    keyframe = api_client.post(f"/api/shots/{shot_id}/keyframe", json={})
    assert keyframe.status_code == 201
    keyframe_payload = keyframe.json()
    assert keyframe_payload["composition_revision"] == 1
    assert keyframe_payload["status"] == "completed"

    shot = api_client.get(f"/api/shots/{shot_id}").json()
    assert shot["start_keyframe_artifact_id"] is None
    assert shot["start_keyframe_content_url"] is None

    promoted = api_client.post(
        f"/api/shots/{shot_id}/attempts/{keyframe_payload['attempt_id']}/promote-keyframe"
    )
    assert promoted.status_code == 200
    assert promoted.json()["start_keyframe_artifact_id"] == keyframe_payload["artifact_id"]
    assert (
        promoted.json()["start_keyframe_attempt_id"] == keyframe_payload["attempt_id"]
    )
    assert promoted.json()["start_keyframe_content_url"] == (
        f"/api/artifacts/{keyframe_payload['artifact_id']}/content"
    )

    repeated = api_client.post(
        f"/api/shots/{shot_id}/attempts/{keyframe_payload['attempt_id']}/promote-keyframe"
    )
    assert repeated.status_code == 200
    assert repeated.json()["start_keyframe_attempt_id"] == keyframe_payload["attempt_id"]

    attempts = api_client.get(f"/api/shots/{shot_id}/attempts")
    assert attempts.status_code == 200
    assert len(attempts.json()) == 1
    assert attempts.json()[0]["kind"] == "keyframe"
    assert attempts.json()[0]["artifact_id"] == keyframe_payload["artifact_id"]

    queued = api_client.post(f"/api/shots/{shot_id}/render")
    assert queued.status_code == 202
    assert queued.json()["status"] == "pending"
    job = conn.execute(
        text("SELECT kind, status, payload FROM jobs WHERE id = :id"),
        {"id": queued.json()["job_id"]},
    ).one()
    assert job.kind == "render_video"
    assert job.status == "pending"
    assert job.payload["start_keyframe_artifact_id"] == keyframe_payload["artifact_id"]

    duplicate = api_client.post(f"/api/shots/{shot_id}/render")
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["error"] == "render_already_active"

    assert (
        api_client.post(
            f"/api/shots/{shot_id}/attempts/{uuid.uuid4()}/promote-keyframe"
        ).status_code
        == 404
    )
