from __future__ import annotations

from abc import ABC, abstractmethod

from pipeline.config import Settings
from pipeline.models import EpisodeContext, StageResult


class BaseStage(ABC):
    name: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    async def run(self, ctx: EpisodeContext) -> StageResult:
        raise NotImplementedError

    def _ensure_episode_dirs(self, ctx: EpisodeContext) -> None:
        for directory in (ctx.episode_dir, ctx.scenes_dir, ctx.audio_dir):
            directory.mkdir(parents=True, exist_ok=True)
