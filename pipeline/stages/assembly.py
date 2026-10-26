from __future__ import annotations

from pipeline.models import EpisodeContext, PipelineStage, StageResult
from pipeline.stages.base import BaseStage
from pipeline.utils import parse_script


class AssemblyStage(BaseStage):
    name = PipelineStage.ASSEMBLY.value

    async def run(self, ctx: EpisodeContext) -> StageResult:
        self._ensure_episode_dirs(ctx)

        script_path = ctx.episode_dir / "script.txt"
        if not script_path.exists():
            return StageResult(
                stage=PipelineStage.ASSEMBLY,
                success=False,
                message="Сценарий не найден.",
            )

        scenes = parse_script(script_path.read_text(encoding="utf-8"))
        if not scenes:
            return StageResult(
                stage=PipelineStage.ASSEMBLY,
                success=False,
                message="Нет сцен для сборки.",
            )

        missing_clips: list[str] = []
        clips = []

        for scene in scenes:
            lipsync = ctx.scenes_dir / f"scene_{scene.number:02d}_lipsync.mp4"
            final = ctx.scenes_dir / f"scene_{scene.number:02d}_final.mp4"
            draft = ctx.scenes_dir / f"scene_{scene.number:02d}_draft.mp4"

            if lipsync.exists():
                clips.append(lipsync)
            elif final.exists():
                clips.append(final)
            elif draft.exists():
                clips.append(draft)
            else:
                missing_clips.append(f"scene_{scene.number:02d}")

        output = ctx.episode_dir / f"{ctx.episode_id}_final.mp4"
        if output.exists():
            return StageResult(
                stage=PipelineStage.ASSEMBLY,
                success=True,
                message="Финальный эпизод уже собран",
                artifacts=[output],
            )

        if missing_clips:
            return StageResult(
                stage=PipelineStage.ASSEMBLY,
                success=False,
                message=f"Не хватает клипов для сцен: {', '.join(missing_clips)}",
                metadata={"available_clips": [str(c) for c in clips]},
            )

        return StageResult(
            stage=PipelineStage.ASSEMBLY,
            success=False,
            message=(
                f"Все {len(clips)} клипов готовы. "
                f"Соберите эпизод в DaVinci Resolve → {output.name}"
            ),
            artifacts=clips,
            metadata={"output": str(output), "clip_count": len(clips)},
        )
