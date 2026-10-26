from __future__ import annotations

from pipeline.models import EpisodeContext, PipelineStage, StageResult
from pipeline.stages.base import BaseStage


class MusicStage(BaseStage):
    name = PipelineStage.MUSIC.value

    async def run(self, ctx: EpisodeContext) -> StageResult:
        self._ensure_episode_dirs(ctx)

        bg_music = ctx.audio_dir / "bg_music.mp3"
        if bg_music.exists():
            return StageResult(
                stage=PipelineStage.MUSIC,
                success=True,
                message="Фоновая музыка уже есть",
                artifacts=[bg_music],
            )

        return StageResult(
            stage=PipelineStage.MUSIC,
            success=False,
            message=(
                "bg_music.mp3 не найден. Сгенерируйте трек в Suno или Mubert "
                "и сохраните в episodes/{episode}/audio/bg_music.mp3"
            ).format(episode=ctx.episode_id),
            metadata={"output": str(bg_music)},
        )
