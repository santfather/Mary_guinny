from __future__ import annotations

import re
from pathlib import Path

from pipeline.models import Scene


_SCENE_HEADER = re.compile(
    r"^СЦЕНА\s*(\d+)\s*:?\s*(.*)$",
    re.MULTILINE | re.IGNORECASE,
)
_GUINNESS_LINE = re.compile(r"^ГИННЕСС\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_MARIJA_LINE = re.compile(r"^МАРИЯ\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_ACTION_LINE = re.compile(r"^ДЕЙСТВИЕ\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)


def parse_script(text: str | None) -> list[Scene]:
    if text is None or not text.strip():
        return []

    blocks = re.split(r"(?=^СЦЕНА\s*\d+)", text.strip(), flags=re.MULTILINE | re.IGNORECASE)
    scenes: list[Scene] = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        header = _SCENE_HEADER.search(block)
        if not header:
            continue

        number = int(header.group(1))
        title = header.group(2).strip()
        guinness = _extract_line(_GUINNESS_LINE, block)
        marija = _extract_line(_MARIJA_LINE, block)
        action = _extract_line(_ACTION_LINE, block)

        scenes.append(
            Scene(
                number=number,
                title=title,
                guinness_line=guinness,
                marija_line=marija,
                action=action,
                raw_block=block,
            )
        )

    return scenes


def _extract_line(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def load_character_bible(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def build_grok_prompt(template_path: Path, character_bible: str, scene_action: str) -> str:
    template = template_path.read_text(encoding="utf-8")
    return template.format(
        character_description=character_bible,
        scene_action=scene_action,
    )
