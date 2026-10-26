from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.comfyui.workflows import (
    build_positive_prompt,
    render_workflow,
    select_character_template,
)
from pipeline.config import Settings


SAMPLE_TEMPLATE = {
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "{{POSITIVE_PROMPT}}",
            "clip": ["1", 1],
        },
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": "{{SEED}}",
            "steps": "{{STEPS}}",
            "cfg": "{{CFG}}",
        },
    },
}


def test_render_workflow_substitutes_variables():
    rendered = render_workflow(
        SAMPLE_TEMPLATE,
        {
            "POSITIVE_PROMPT": "orange tabby cat, 2D cartoon",
            "SEED": 42,
            "STEPS": 28,
            "CFG": 7.5,
        },
    )
    assert rendered["2"]["inputs"]["text"] == "orange tabby cat, 2D cartoon"
    assert rendered["5"]["inputs"]["seed"] == 42
    assert rendered["5"]["inputs"]["steps"] == 28


def test_render_workflow_missing_variable_raises():
    with pytest.raises(KeyError, match="POSITIVE_PROMPT"):
        render_workflow(SAMPLE_TEMPLATE, {"SEED": 1, "STEPS": 20, "CFG": 7})


def test_select_character_template_front_is_txt2img():
    assert (
        select_character_template(
            "reference_front",
            {"use_ipadapter": False},
            anchor_exists=False,
            pose_skeleton_exists=False,
        )
        == "txt2img"
    )


def test_select_character_template_with_anchor_uses_ipadapter():
    assert (
        select_character_template(
            "reference_side",
            {"use_ipadapter": True},
            anchor_exists=True,
            pose_skeleton_exists=False,
        )
        == "ipadapter"
    )


def test_build_positive_prompt_uses_bible_prompt_block():
    bible = (
        "ПЕРСОНАЖ: ГИННЕСС\n"
        "Промпт для генерации:\n"
        "orange tabby cat, 2D cartoon"
    )
    prompt = build_positive_prompt(bible, "standing front view")
    assert "orange tabby cat" in prompt
    assert "standing front view" in prompt


def test_workflow_files_exist():
    root = Path(__file__).resolve().parent.parent
    workflows = root / "comfyui-workflows"
    required = [
        "character_pose_gen.json",
        "character_pose_gen.api.json",
        "character_pose_openpose.api.json",
        "character_pose_ipadapter.api.json",
        "scene_draft_ltx.json",
        "scene_draft_ltx.api.json",
        "controlnet_pose.json",
        "workflow_config.json",
    ]
    for name in required:
        assert (workflows / name).exists(), name


def test_settings_loads_comfyui_root_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("COMFYUI_ROOT", str(tmp_path))
    settings = Settings.from_env(project_root=tmp_path)
    assert settings.comfyui_root == tmp_path
