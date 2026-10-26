"""WP-05A: детерминированный планировщик и нормализация vision-ответа."""

from __future__ import annotations

import json
import uuid

import pytest

from app import planner
from app.planner import (
    DEFAULT_CANVAS,
    PlanError,
    PlannerUnavailable,
    PlanReference,
    build_skeleton,
    default_canvas,
    generate_candidate,
    motion_prompt,
    normalize_vision_response,
    validate_plan,
)


def _reference(role: str = "character", alias: str = "guinness") -> PlanReference:
    return PlanReference(
        asset_id=uuid.uuid4(), role=role, entity_id=uuid.uuid4(), alias=alias
    )


def _skeleton(**overrides) -> tuple[dict[str, object], list[PlanReference]]:
    references = overrides.pop("references", None) or [_reference()]
    plan = build_skeleton(
        references,
        action=overrides.pop("action", "guinness sits down"),
        camera=overrides.pop("camera", {"framing": "medium", "movement": "static"}),
        canvas=overrides.pop("canvas", DEFAULT_CANVAS),
    )
    return plan, references


def test_default_canvas_is_768x512_with_explicit_override() -> None:
    assert default_canvas(None, None) == (768, 512)
    assert default_canvas(512, None) == (512, 512)
    assert default_canvas(None, 512) == (768, 512)


def test_motion_prompt_is_deterministic_and_bounded() -> None:
    assert motion_prompt({"framing": "wide", "movement": "static"}, "") == (
        "wide shot, static camera"
    )
    assert motion_prompt({"framing": "close_up", "movement": "pan"}, "  wave  ") == (
        "close_up shot, pan camera; wave"
    )
    assert len(motion_prompt({"framing": "wide"}, "x" * 5000)) == 4000


def test_skeleton_keeps_server_assigned_identity() -> None:
    plan, references = _skeleton()
    reference = references[0]

    assert plan["schema_version"] == 1
    assert plan["canvas"] == {"width": 768, "height": 512}
    assert plan["references"] == [
        {
            "asset_id": str(reference.asset_id),
            "role": "character",
            "entity_id": str(reference.entity_id),
            "alias": "guinness",
        }
    ]
    assert plan["camera"] == {"framing": "medium", "movement": "static"}
    assert plan["initial_state"] == []
    assert plan["action_beats"] == []
    assert plan["constraints"] == {
        "preserve_character_identity": True,
        "preserve_location_layout": True,
        "no_unreferenced_characters": True,
    }
    assert plan["needs_review"] is False
    assert plan["motion_prompt"] == "medium shot, static camera; guinness sits down"
    validate_plan(plan)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda plan: plan.update(schema_version=2), "schema_version"),
        (lambda plan: plan.update(canvas={"width": 0, "height": 512}), "positive"),
        (lambda plan: plan.update(canvas={"width": "768", "height": 512}), "integers"),
        (lambda plan: plan.update(references=[]), "at least one reference"),
        (
            lambda plan: plan["references"][0].update(alias="Guinness"),
            "invalid reference alias",
        ),
        (
            lambda plan: plan["references"][0].update(role="hero"),
            "invalid reference role",
        ),
        (
            lambda plan: plan["references"][0].update(asset_id="not-a-uuid"),
            "asset_id must be a UUID",
        ),
        (
            lambda plan: plan["references"][0].update(entity_id="nope"),
            "entity_id must be a UUID",
        ),
        (
            lambda plan: plan.update(
                camera={"framing": "macro", "movement": "static"}
            ),
            "invalid camera framing",
        ),
        (
            lambda plan: plan.update(
                camera={"framing": "wide", "movement": "orbit"}
            ),
            "invalid camera movement",
        ),
        (
            lambda plan: plan.update(
                initial_state=[{"subject": "marija", "position": "", "action": ""}]
            ),
            "not a declared alias",
        ),
        (
            lambda plan: plan.update(
                action_beats=[
                    {"order": 2, "subject": "guinness", "action": "wave"},
                ]
            ),
            "1..N",
        ),
        (
            lambda plan: plan.update(
                action_beats=[
                    {
                        "order": 1,
                        "subject": "guinness",
                        "action": "wave",
                        "target": "marija",
                    }
                ]
            ),
            "not a declared alias",
        ),
        (lambda plan: plan.update(motion_prompt="   "), "non-empty"),
        (lambda plan: plan.update(motion_prompt="x" * 4001), "exceeds"),
        (lambda plan: plan.update(needs_review="no"), "boolean"),
    ],
)
def test_validate_plan_rejects_invalid_payloads(mutate, message: str) -> None:
    plan, _references = _skeleton()
    mutate(plan)
    with pytest.raises(PlanError, match=message):
        validate_plan(plan)


def test_duplicate_alias_is_rejected() -> None:
    references = [_reference(alias="guinness"), _reference(alias="guinness")]
    plan = build_skeleton(
        references, action="", camera=None, canvas=DEFAULT_CANVAS
    )
    with pytest.raises(PlanError, match="duplicate reference alias"):
        validate_plan(plan)


def test_vision_observations_become_initial_state_with_warnings() -> None:
    plan, references = _skeleton()
    raw = json.dumps(
        {
            "observations": [
                {
                    "alias": "guinness",
                    "subject": "orange cat",
                    "pose": "sitting",
                    "facing": "left",
                },
                {"alias": "ghost", "subject": "invented", "pose": "", "facing": ""},
                {"alias": "guinness", "subject": "duplicate", "pose": "", "facing": ""},
            ],
            "uncertainties": ["tail is cut off"],
        }
    )

    warnings = normalize_vision_response(raw, references, plan)

    assert plan["initial_state"] == [
        {
            "subject": "guinness",
            "position": "orange cat; left",
            "action": "sitting",
        }
    ]
    assert plan["needs_review"] is False
    assert [warning["code"] for warning in warnings] == [
        "vision_alias_mismatch",
        "vision_uncertainty",
    ]
    validate_plan(plan)


def test_vision_without_usable_observations_requires_review() -> None:
    plan, references = _skeleton()
    warnings = normalize_vision_response(
        json.dumps({"observations": [{"alias": "ghost"}]}), references, plan
    )

    assert plan["needs_review"] is True
    assert [warning["code"] for warning in warnings] == [
        "vision_alias_mismatch",
        "vision_no_observations",
    ]


@pytest.mark.parametrize("raw", ["not json", "[]"])
def test_vision_malformed_payload_is_unavailable(raw: str) -> None:
    plan, references = _skeleton()
    with pytest.raises(PlannerUnavailable):
        normalize_vision_response(raw, references, plan)


def test_generate_candidate_without_vision_is_manual() -> None:
    references = [_reference()]
    plan, warnings, source = generate_candidate(
        references,
        action="wave",
        camera={"framing": "wide", "movement": "static"},
        canvas=DEFAULT_CANVAS,
        images=[("guinness", b"png")],
        use_vision=False,
        settings=object(),
    )

    assert source == "manual"
    assert warnings == []
    assert plan["initial_state"] == []


def test_generate_candidate_uses_vision_when_available(monkeypatch) -> None:
    references = [_reference()]
    monkeypatch.setattr(
        planner,
        "analyze_images",
        lambda *args, **kwargs: json.dumps(
            {
                "observations": [
                    {"alias": "guinness", "subject": "cat", "pose": "sit", "facing": "left"}
                ]
            }
        ),
    )

    plan, warnings, source = generate_candidate(
        references,
        action="wave",
        camera=None,
        canvas=DEFAULT_CANVAS,
        images=[("guinness", b"png")],
        use_vision=True,
        settings=object(),
    )

    assert source == "llm"
    assert warnings == []
    assert plan["initial_state"][0]["subject"] == "guinness"


def test_generate_candidate_falls_back_when_vision_is_unavailable(monkeypatch) -> None:
    references = [_reference()]

    def _boom(*args, **kwargs):
        raise PlannerUnavailable("connection refused")

    monkeypatch.setattr(planner, "analyze_images", _boom)

    plan, warnings, source = generate_candidate(
        references,
        action="wave",
        camera=None,
        canvas=DEFAULT_CANVAS,
        images=[("guinness", b"png")],
        use_vision=True,
        settings=object(),
    )

    assert source == "fallback"
    assert plan["needs_review"] is True
    assert [warning["code"] for warning in warnings] == ["vision_unavailable"]
    validate_plan(plan)
