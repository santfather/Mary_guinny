"""WP-N2: адаптер LTX-2.3 MLX I2V — биндинги нод и параметры шота."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.comfyui.ltx_adapter import (
    GENERATE_NODE,
    LOAD_IMAGE_NODE,
    BindingError,
    bind_workflow,
    build_shot_binding,
    describe,
    load_template,
    resolve_size,
    snap_frames,
    workflow_version,
)

WORKFLOW = (
    Path(__file__).resolve().parent.parent
    / "comfyui-workflows"
    / "ltx23_mlx_q4_i2v.api.json"
)


@pytest.fixture
def template():
    return load_template(WORKFLOW)


def _binding(**overrides):
    values = {
        "shot_key": "NLB-01",
        "prompt": "the cat blinks slowly and twitches an ear",
        "image_name": "nlb_start_NLB-01.png",
        "seed": 42,
        "attempt_id": "4b1f0c2e",
        "aspect_ratio": "9:16",
        "seconds": 8,
        "fps": 24,
    }
    values.update(overrides)
    return build_shot_binding(**values)


def _inputs(workflow, class_type: str) -> dict:
    return next(
        node["inputs"] for node in workflow.values() if node["class_type"] == class_type
    )


def test_portrait_eight_seconds_snaps_to_193_frames() -> None:
    binding = _binding()

    assert (binding.width, binding.height) == (1080, 1920)
    assert binding.num_frames == 193
    assert binding.frame_rate == 24.0
    assert binding.output_prefix == "nlb/NLB-01/4b1f0c2e"


def test_bind_workflow_substitutes_shot_values(template) -> None:
    binding = _binding()
    workflow = bind_workflow(template, binding)

    generate = _inputs(workflow, GENERATE_NODE)
    assert generate["prompt"] == binding.prompt
    assert generate["seed"] == 42
    assert generate["width"] == 1080
    assert generate["height"] == 1920
    assert generate["num_frames"] == 193
    assert generate["frame_rate"] == 24.0
    assert generate["filename_prefix"] == binding.output_prefix
    assert generate["image"] == ["1", 0]

    assert _inputs(workflow, LOAD_IMAGE_NODE)["image"] == binding.image_name
    assert _inputs(workflow, "LTX2MLXModelLoader")["model_dir"] == "dgrauet/ltx-2.3-mlx-q4"


def test_bind_workflow_does_not_mutate_template(template) -> None:
    before = json.dumps(template, sort_keys=True)

    bind_workflow(template, _binding())

    assert json.dumps(template, sort_keys=True) == before


def test_bind_workflow_requires_all_nodes(template) -> None:
    template.pop("1")

    with pytest.raises(BindingError, match=LOAD_IMAGE_NODE):
        bind_workflow(template, _binding())


def test_bind_workflow_rejects_broken_image_link(template) -> None:
    template["3"]["inputs"]["image"] = ["1", 1]

    with pytest.raises(BindingError, match="image"):
        bind_workflow(template, _binding())


def test_bind_workflow_reports_missing_input(template) -> None:
    del template["3"]["inputs"]["seed"]

    with pytest.raises(BindingError, match="seed"):
        bind_workflow(template, _binding())


def test_snap_frames_is_8k_plus_one() -> None:
    assert snap_frames(8, 24) == 193
    assert snap_frames(7, 24) == 169
    assert snap_frames(0.1, 24) == 9
    assert snap_frames(60, 24) == 257


def test_resolve_size_from_aspect_ratio() -> None:
    assert resolve_size("9:16") == (1080, 1920)
    assert resolve_size("16:9") == (1920, 1080)
    assert resolve_size("1:1") == (1920, 1920)


def test_build_shot_binding_rejects_invalid_requests() -> None:
    with pytest.raises(BindingError, match="prompt"):
        _binding(prompt="  ")
    with pytest.raises(BindingError, match="стартовый кадр"):
        _binding(image_name="")
    with pytest.raises(BindingError, match="seed"):
        _binding(seed=-1)
    with pytest.raises(BindingError, match="fps"):
        _binding(fps=0)
    with pytest.raises(BindingError, match="длительность"):
        _binding(seconds=0)
    with pytest.raises(BindingError, match="attempt_id"):
        _binding(attempt_id=" ")


def test_output_prefix_is_unique_per_attempt() -> None:
    first = _binding(attempt_id="aaaa")
    second = _binding(attempt_id="bbbb")

    assert first.output_prefix != second.output_prefix
    assert first.output_prefix.startswith("nlb/NLB-01/")


def test_workflow_version_is_stable_and_tracks_template(template) -> None:
    version = workflow_version(template)
    assert version == workflow_version(template)
    assert version.startswith("ltx23-mlx-q4-i2v/")

    changed = json.loads(json.dumps(template))
    changed["3"]["inputs"]["cfg_scale"] = 2.5
    assert workflow_version(changed) != version


def test_describe_reports_node_ids_and_unverified_render(template) -> None:
    binding = _binding()
    report = describe(template, binding)

    assert report["render_verified"] is False
    assert report["nodes"] == {
        GENERATE_NODE: "3",
        LOAD_IMAGE_NODE: "1",
        "LTX2MLXModelLoader": "2",
    }
    assert report["inputs"]["num_frames"] == 193
    assert report["workflow_version"] == workflow_version(template)
