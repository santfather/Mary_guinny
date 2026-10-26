"""WP-05A: Visual Scene Plan — ревизии, approve/supersede, план → композиция."""

from __future__ import annotations

import io

from PIL import Image
from sqlalchemy import text

from app import planner
from app.planner import PlannerUnavailable
from app.storage import BlobStore


def _ref(asset_id, role: str = "character", alias: str = "guinness", entity_id=None):
    payload: dict[str, object] = {
        "asset_id": str(asset_id),
        "role": role,
        "alias": alias,
    }
    if entity_id is not None:
        payload["entity_id"] = str(entity_id)
    return payload


def _plan(
    references: list[dict[str, object]],
    *,
    width: int = 768,
    height: int = 512,
    prompt: str = "wide shot, static camera",
) -> dict[str, object]:
    return {
        "canvas": {"width": width, "height": height},
        "references": references,
        "camera": {"framing": "wide", "movement": "static"},
        "motion_prompt": prompt,
        "needs_review": False,
    }


def test_scene_plan_revisions_are_append_only(
    api_client, project_id, shot_id, character_id, location_id, make_png_reference
) -> None:
    character = make_png_reference(project_id=project_id, character_id=character_id)
    location = make_png_reference(project_id=project_id, location_id=location_id)
    references = [_ref(location, "location", "living_room"), _ref(character)]
    body = {"plan": _plan(references)}

    first = api_client.post(f"/api/shots/{shot_id}/scene-plans", json=body)
    assert first.status_code == 201
    payload = first.json()
    assert payload["revision"] == 1
    assert payload["status"] == "draft"
    assert payload["source"] == "manual"
    assert payload["approved_at"] is None
    assert payload["warnings"] == []
    assert payload["plan"]["canvas"] == {"width": 768, "height": 512}
    # entity_id сервер берёт у владельца ассета, а не из запроса.
    assert payload["plan"]["references"][0]["entity_id"] == str(location_id)
    assert payload["plan"]["references"][1]["entity_id"] == str(character_id)

    identical = api_client.post(f"/api/shots/{shot_id}/scene-plans", json=body)
    assert identical.status_code == 200
    assert identical.json()["revision"] == 1

    edited = api_client.put(
        f"/api/shots/{shot_id}/scene-plans/1",
        json=_plan(references, prompt="medium shot, pan camera; guinness sits"),
    )
    assert edited.status_code == 200
    assert edited.json()["revision"] == 1
    assert edited.json()["plan"]["motion_prompt"] == (
        "medium shot, pan camera; guinness sits"
    )

    second = api_client.post(f"/api/shots/{shot_id}/scene-plans", json=body)
    assert second.status_code == 201
    assert second.json()["revision"] == 2

    listed = api_client.get(f"/api/shots/{shot_id}/scene-plans")
    assert listed.status_code == 200
    assert [item["revision"] for item in listed.json()] == [2, 1]
    assert api_client.get(f"/api/shots/{shot_id}/scene-plans/1").status_code == 200
    assert api_client.get(f"/api/shots/{shot_id}/scene-plans/9").status_code == 404

    bad_alias = api_client.post(
        f"/api/shots/{shot_id}/scene-plans",
        json={"plan": _plan([_ref(character, alias="BAD")])},
    )
    assert bad_alias.status_code == 422

    no_references = api_client.post(
        f"/api/shots/{shot_id}/scene-plans",
        json={"plan": _plan([])},
    )
    assert no_references.status_code == 422


def test_plan_references_are_validated_against_project_and_role(
    api_client,
    project_id,
    second_project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
) -> None:
    character = make_png_reference(project_id=project_id, character_id=character_id)
    draft = make_png_reference(
        project_id=project_id, character_id=character_id, status="draft"
    )
    foreign = make_png_reference(project_id=second_project_id)
    uploaded = make_png_reference(project_id=project_id)

    def _create(references):
        return api_client.post(
            f"/api/shots/{shot_id}/scene-plans", json={"plan": _plan(references)}
        )

    assert _create([_ref(character)]).status_code == 201

    unapproved = _create([_ref(draft)])
    assert unapproved.status_code == 409
    assert "approved" in unapproved.json()["detail"]

    assert _create([_ref(foreign)]).status_code == 404
    assert (
        _create([_ref("00000000-0000-0000-0000-000000000000")]).status_code == 404
    )

    mismatch = _create([_ref(character, entity_id=location_id)])
    assert mismatch.status_code == 422
    assert "entity_id does not match" in mismatch.json()["detail"]

    no_owner = _create([_ref(uploaded, "character")])
    assert no_owner.status_code == 422
    assert "no character owner" in no_owner.json()["detail"]

    style_with_entity = _create(
        [_ref(character, "style", "look_ref", entity_id=character_id)]
    )
    assert style_with_entity.status_code == 422
    assert "cannot have entity_id" in style_with_entity.json()["detail"]


def test_approve_supersede_and_approved_plan_is_immutable(
    api_client,
    conn,
    expect_violation,
    project_id,
    shot_id,
    character_id,
    make_png_reference,
) -> None:
    character = make_png_reference(project_id=project_id, character_id=character_id)
    body = {"plan": _plan([_ref(character)])}
    created = api_client.post(f"/api/shots/{shot_id}/scene-plans", json=body)
    plan_id = created.json()["id"]

    approved = api_client.post(f"/api/shots/{shot_id}/scene-plans/1/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_at"] is not None
    assert (
        api_client.post(f"/api/shots/{shot_id}/scene-plans/1/approve").json()["status"]
        == "approved"
    )

    expect_violation(
        "UPDATE visual_scene_plans SET plan = '{}'::jsonb WHERE id = :id",
        {"id": plan_id},
        match="immutable",
    )
    expect_violation(
        "DELETE FROM visual_scene_plans WHERE id = :id",
        {"id": plan_id},
        match="cannot be deleted",
    )

    blocked = api_client.put(
        f"/api/shots/{shot_id}/scene-plans/1",
        json=_plan([_ref(character)], prompt="edited after approval"),
    )
    assert blocked.status_code == 409
    assert "draft" in blocked.json()["detail"]

    assert api_client.post(f"/api/shots/{shot_id}/scene-plans", json=body).status_code == 201
    conflict = api_client.post(f"/api/shots/{shot_id}/scene-plans/2/approve")
    assert conflict.status_code == 409
    assert "supersede" in conflict.json()["detail"]

    superseded = api_client.post(f"/api/shots/{shot_id}/scene-plans/1/supersede")
    assert superseded.status_code == 200
    assert superseded.json()["status"] == "superseded"
    assert (
        api_client.post(f"/api/shots/{shot_id}/scene-plans/1/supersede").json()["status"]
        == "superseded"
    )

    assert api_client.post(f"/api/shots/{shot_id}/scene-plans/2/approve").status_code == 200
    assert api_client.post(f"/api/shots/{shot_id}/scene-plans/2/supersede").status_code == 200
    assert api_client.post(f"/api/shots/{shot_id}/scene-plans/2/approve").status_code == 409

    draft = api_client.post(f"/api/shots/{shot_id}/scene-plans", json=body)
    assert draft.json()["revision"] == 3
    assert api_client.post(f"/api/shots/{shot_id}/scene-plans/3/supersede").status_code == 409


def test_generate_returns_candidate_without_persisting(
    api_client,
    project_id,
    shot_id,
    character_id,
    make_png_reference,
    monkeypatch,
) -> None:
    character = make_png_reference(project_id=project_id, character_id=character_id)
    body = {
        "action": "guinness sits down",
        "references": [_ref(character)],
        "use_vision": False,
    }

    manual = api_client.post(f"/api/shots/{shot_id}/scene-plans/generate", json=body)
    assert manual.status_code == 200
    payload = manual.json()
    assert payload["source"] == "manual"
    assert payload["warnings"] == []
    assert payload["plan"]["motion_prompt"] == (
        "wide shot, static camera; guinness sits down"
    )
    assert payload["plan"]["references"][0]["alias"] == "guinness"
    assert payload["plan"]["references"][0]["entity_id"] == str(character_id)

    def _unavailable(*_args, **_kwargs):
        raise PlannerUnavailable("connection refused")

    monkeypatch.setattr(planner, "analyze_images", _unavailable)
    fallback = api_client.post(
        f"/api/shots/{shot_id}/scene-plans/generate",
        json={**body, "use_vision": True},
    )
    assert fallback.status_code == 200
    assert fallback.json()["source"] == "fallback"
    assert fallback.json()["plan"]["needs_review"] is True
    assert [item["code"] for item in fallback.json()["warnings"]] == [
        "vision_unavailable"
    ]

    # Generate ничего не пишет: история планов пуста.
    assert api_client.get(f"/api/shots/{shot_id}/scene-plans").json() == []


def test_plan_to_composition_and_keyframe_provenance(
    api_client,
    project_id,
    shot_id,
    character_id,
    location_id,
    make_png_reference,
) -> None:
    character = make_png_reference(
        project_id=project_id, character_id=character_id, width=48, height=48
    )
    location = make_png_reference(
        project_id=project_id, location_id=location_id, width=96, height=64
    )
    created = api_client.post(
        f"/api/shots/{shot_id}/scene-plans",
        json={
            "plan": _plan(
                [_ref(location, "location", "living_room"), _ref(character)]
            )
        },
    )
    plan_id = created.json()["id"]

    blocked = api_client.post(f"/api/shots/{shot_id}/scene-plans/1/composition")
    assert blocked.status_code == 409
    assert "approve" in blocked.json()["detail"]

    assert api_client.post(f"/api/shots/{shot_id}/scene-plans/1/approve").status_code == 200
    composed = api_client.post(f"/api/shots/{shot_id}/scene-plans/1/composition")
    assert composed.status_code == 201
    payload = composed.json()
    assert (payload["width"], payload["height"]) == (768, 512)
    assert payload["source_plan_id"] == plan_id
    assert payload["status"] == "draft"
    assert [layer["z_index"] for layer in payload["layers"]] == [0, 1]
    assert payload["layers"][0]["reference"]["id"] == str(location)
    assert payload["layers"][0]["scale"] == 8.0  # fit-cover локации
    assert payload["layers"][1]["reference"]["id"] == str(character)

    # Повторный вызов создаёт новую ревизию композиции, план не меняется.
    assert api_client.post(f"/api/shots/{shot_id}/scene-plans/1/composition").json()[
        "revision"
    ] == 2

    assert api_client.post(f"/api/shots/{shot_id}/compositions/1/render").status_code == 200
    assert api_client.post(f"/api/shots/{shot_id}/compositions/1/approve").status_code == 200

    keyframe = api_client.post(
        f"/api/shots/{shot_id}/keyframe", json={"composition_revision": 1}
    )
    assert keyframe.status_code == 201
    attempt_id = keyframe.json()["attempt_id"]
    artifact_id = keyframe.json()["artifact_id"]

    promoted = api_client.post(
        f"/api/shots/{shot_id}/attempts/{attempt_id}/promote-keyframe"
    )
    assert promoted.status_code == 200
    assert promoted.json()["start_keyframe_artifact_id"] == artifact_id

    attempts = api_client.get(f"/api/shots/{shot_id}/attempts").json()
    assert attempts[0]["visual_plan_revision"] == 1
    assert attempts[0]["composition_revision"] == 1


def test_layout_mockup_and_square_export(
    api_client,
    conn,
    tmp_path,
    project_id,
    shot_id,
    character_id,
    make_png_reference,
) -> None:
    opaque = make_png_reference(
        project_id=project_id,
        character_id=character_id,
        width=48,
        height=48,
        has_alpha=False,
    )
    created = api_client.post(
        f"/api/shots/{shot_id}/scene-plans",
        json={"plan": _plan([_ref(opaque)])},
    )
    plan_id = created.json()["id"]
    assert api_client.post(f"/api/shots/{shot_id}/scene-plans/1/approve").status_code == 200
    composition = api_client.post(f"/api/shots/{shot_id}/scene-plans/1/composition")
    assert composition.status_code == 201
    assert composition.json()["layout_mockup"] is True
    assert composition.json()["source_plan_id"] == plan_id

    before_render = api_client.post(
        f"/api/shots/{shot_id}/compositions/1/export",
        json={"size": 512, "mode": "crop"},
    )
    assert before_render.status_code == 409
    assert "render" in before_render.json()["detail"]

    rendered = api_client.post(f"/api/shots/{shot_id}/compositions/1/render")
    assert rendered.status_code == 200
    assert rendered.json()["is_layout_mockup"] is True

    detail = api_client.get(f"/api/shots/{shot_id}").json()
    assert detail["composition_revisions"][0]["layout_mockup"] is True

    cropped = api_client.post(
        f"/api/shots/{shot_id}/compositions/1/export",
        json={"size": 512, "mode": "crop"},
    )
    assert cropped.status_code == 200
    assert cropped.json()["size"] == 512
    assert cropped.json()["mode"] == "crop"
    assert cropped.json()["is_layout_mockup"] is True
    assert cropped.json()["source_composition_revision"] == 1

    padded = api_client.post(
        f"/api/shots/{shot_id}/compositions/1/export",
        json={"size": 512, "mode": "pad"},
    )
    assert padded.status_code == 200

    store = BlobStore(tmp_path / "storage")
    for artifact_id in (cropped.json()["artifact_id"], padded.json()["artifact_id"]):
        storage_key = conn.execute(
            text("SELECT storage_key FROM artifacts WHERE id = :id"),
            {"id": artifact_id},
        ).scalar_one()
        image = Image.open(io.BytesIO(store.read_bytes(storage_key)))
        assert image.size == (512, 512)
        assert image.mode == "RGBA"

    too_large_for_crop = api_client.post(
        f"/api/shots/{shot_id}/compositions/1/export",
        json={"size": 1024, "mode": "crop"},
    )
    assert too_large_for_crop.status_code == 422
    assert "padding" in too_large_for_crop.json()["detail"]

    assert (
        api_client.post(
            f"/api/shots/{shot_id}/compositions/1/export",
            json={"size": 512, "mode": "stretch"},
        ).status_code
        == 422
    )
