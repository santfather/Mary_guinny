from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any


_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_workflow_config(workflows_dir: Path) -> dict[str, Any]:
    return load_json(workflows_dir / "workflow_config.json")


def load_pose_config(prompts_dir: Path) -> dict[str, Any]:
    return load_json(prompts_dir / "character_poses.json")


def render_workflow(template: dict[str, Any], variables: dict[str, Any]) -> dict[str, Any]:
    """Подставляет {{VAR}} в workflow API JSON, сохраняя типы чисел."""

    def render_value(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: render_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [render_value(item) for item in value]
        if isinstance(value, str):
            match = _PLACEHOLDER.fullmatch(value)
            if match:
                key = match.group(1)
                if key not in variables:
                    raise KeyError(f"Переменная {key} не задана для workflow")
                return variables[key]
            return _PLACEHOLDER.sub(
                lambda m: str(variables[m.group(1)]) if m.group(1) in variables else m.group(0),
                value,
            )
        return value

    return render_value(deepcopy(template))


def select_character_template(
    pose_name: str,
    pose_cfg: dict[str, Any],
    anchor_exists: bool,
    pose_skeleton_exists: bool,
) -> str:
    if pose_cfg.get("use_ipadapter") and anchor_exists:
        return "ipadapter"
    if pose_skeleton_exists:
        return "openpose"
    return "txt2img"


_FILE_REF = re.compile(r",?\s*inspired by [^,]+", re.IGNORECASE)


def _sanitize_prompt(base: str) -> str:
    """Убирает ссылки на файлы-референсы — dreamshaper их не понимает."""
    return _FILE_REF.sub("", base).strip()


def extract_bible_prompt(character_bible: str) -> str:
    lines = [line.strip() for line in character_bible.splitlines() if line.strip()]
    prompt_lines = [line for line in lines if line.lower().startswith("промпт")]
    if prompt_lines:
        idx = lines.index(prompt_lines[0])
        base = " ".join(lines[idx + 1 :]).strip()
    else:
        base = " ".join(lines[2:6]) if len(lines) > 2 else character_bible
    return _sanitize_prompt(base)


def build_positive_prompt(character_bible: str, pose_prompt: str, character_kind: str | None = None) -> str:
    base = extract_bible_prompt(character_bible)

    if character_kind == "cat":
        base = f"single cat, feline, no humans, {base}"
    elif character_kind == "human":
        base = f"single woman, no animals, {base}"

    return (
        f"{base}, {pose_prompt}, single character, clean background, "
        "centered composition, illustration, cartoon, not photorealistic"
    )


def build_scene_prompt(
    scene_action: str,
    scene_title: str,
    guinness_bible: str,
    marija_bible: str,
) -> str:
    cat = extract_bible_prompt(guinness_bible)
    woman = extract_bible_prompt(marija_bible)
    action = scene_action or scene_title
    return (
        f"2D cartoon scene, soft lines, pastel colors, cozy home interior, not photorealistic. "
        f"Two characters in the same art style: "
        f"(1) Burmese cat — {cat}. "
        f"(2) Young woman — {woman}. "
        f"Scene action: {action}. "
        f"Wide shot, both characters visible, consistent character design."
    )
