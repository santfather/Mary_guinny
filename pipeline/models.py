from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class PipelineStage(str, Enum):
    SCRIPT = "script"
    CHARACTER_REFS = "character_refs"
    SCENE_DRAFT = "scene_draft"
    FINAL_VIDEO = "final_video"
    VOICES = "voices"
    LIPSYNC = "lipsync"
    MUSIC = "music"
    ASSEMBLY = "assembly"


class PipelinePhase(str, Enum):
    """Фазы разработки: сначала локально, облако — в конце."""

    LOCAL = "local"
    CLOUD = "cloud"
    FULL = "full"


# Полный пайплайн (документация scenario.md)
PIPELINE_ORDER: list[PipelineStage] = list(PipelineStage)

# Фаза 1 — локально: персонажи + сценарий + черновик (Ollama + ComfyUI)
LOCAL_PIPELINE_ORDER: list[PipelineStage] = [
    PipelineStage.CHARACTER_REFS,
    PipelineStage.SCRIPT,
    PipelineStage.SCENE_DRAFT,
]

# Фаза 2 — облако: финал, голоса, lip sync, музыка, сборка
CLOUD_PIPELINE_ORDER: list[PipelineStage] = [
    PipelineStage.FINAL_VIDEO,
    PipelineStage.VOICES,
    PipelineStage.LIPSYNC,
    PipelineStage.MUSIC,
    PipelineStage.ASSEMBLY,
]

PHASE_ORDERS: dict[PipelinePhase, list[PipelineStage]] = {
    PipelinePhase.LOCAL: LOCAL_PIPELINE_ORDER,
    PipelinePhase.CLOUD: CLOUD_PIPELINE_ORDER,
    PipelinePhase.FULL: PIPELINE_ORDER,
}


@dataclass
class Scene:
    number: int
    title: str
    guinness_line: str | None = None
    marija_line: str | None = None
    action: str | None = None
    raw_block: str = ""


@dataclass
class StageResult:
    stage: PipelineStage
    success: bool
    message: str
    artifacts: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EpisodeContext:
    episode_id: str
    root: Path
    prompt: str | None = None
    script_path: Path | None = None
    scenes: list[Scene] = field(default_factory=list)

    @property
    def episode_dir(self) -> Path:
        return self.root / "episodes" / self.episode_id

    @property
    def scenes_dir(self) -> Path:
        return self.episode_dir / "scenes"

    @property
    def audio_dir(self) -> Path:
        return self.episode_dir / "audio"
