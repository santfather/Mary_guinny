from __future__ import annotations

from pipeline.models import EpisodeContext, PipelineStage, StageResult
from pipeline.stages.base import BaseStage
from pipeline.utils import parse_script


class LipsyncStage(BaseStage):
    name = PipelineStage.LIPSYNC.value

    async def run(self, ctx: EpisodeContext) -> StageResult:
        self._ensure_episode_dirs(ctx)

        if not self.settings.hedra_api_key:
            return StageResult(
                stage=PipelineStage.LIPSYNC,
                success=False,
                message="Не задан HEDRA_API_KEY в .env",
            )

        script_path = ctx.episode_dir / "script.txt"
        if not script_path.exists():
            return StageResult(
                stage=PipelineStage.LIPSYNC,
                success=False,
                message="Сценарий не найден.",
            )

        scenes = parse_script(script_path.read_text(encoding="utf-8"))
        if not scenes:
            return StageResult(
                stage=PipelineStage.LIPSYNC,
                success=False,
                message="Нет сцен для lip sync.",
            )

        pending: list[dict] = []
        ready = []

        for scene in scenes:
            output = ctx.scenes_dir / f"scene_{scene.number:02d}_lipsync.mp4"
            video = ctx.scenes_dir / f"scene_{scene.number:02d}_final.mp4"
            audio_candidates = [
                ctx.audio_dir / f"guinness_line_{scene.number:02d}.mp3",
                ctx.audio_dir / f"marija_line_{scene.number:02d}.mp3",
            ]

            if output.exists():
                ready.append(output)
                continue

            pending.append(
                {
                    "scene": scene.number,
                    "video": str(video),
                    "audio": [str(p) for p in audio_candidates if p.exists()],
                    "output": str(output),
                }
            )

        if pending:
            return StageResult(
                stage=PipelineStage.LIPSYNC,
                success=False,
                message=f"{len(pending)} клипов ожидают обработки в Hedra.",
                artifacts=ready,
                metadata={"pending_clips": pending},
            )

        return StageResult(
            stage=PipelineStage.LIPSYNC,
            success=True,
            message=f"Все lip sync клипы готовы ({len(ready)} файлов)",
            artifacts=ready,
        )
