from __future__ import annotations

from pipeline.models import EpisodeContext, PipelineStage, StageResult
from pipeline.stages.base import BaseStage
from pipeline.comfyui.scene_draft import SceneDraftGenerator
from pipeline.utils import parse_script


class SceneDraftStage(BaseStage):
    name = PipelineStage.SCENE_DRAFT.value

    async def run(self, ctx: EpisodeContext) -> StageResult:
        self._ensure_episode_dirs(ctx)

        script_path = ctx.script_path or (ctx.episode_dir / "script.txt")
        if not script_path.exists():
            return StageResult(
                stage=PipelineStage.SCENE_DRAFT,
                success=False,
                message="Сценарий не найден. Сначала запустите stage: script.",
            )

        script_text = script_path.read_text(encoding="utf-8")
        ctx.scenes = parse_script(script_text)
        if not ctx.scenes:
            return StageResult(
                stage=PipelineStage.SCENE_DRAFT,
                success=False,
                message="Сценарий не содержит распознанных сцен (формат СЦЕНА N:).",
            )

        template = self.settings.workflows_dir() / "scene_draft_ipadapter.api.json"
        if not template.exists():
            return StageResult(
                stage=PipelineStage.SCENE_DRAFT,
                success=False,
                message="Workflow scene_draft_ipadapter.api.json не найден.",
                metadata={"scene_count": len(ctx.scenes)},
            )

        generator = SceneDraftGenerator(self.settings)
        results = await generator.generate_all(ctx.episode_id)

        artifacts = [r.output_path for r in results if r.output_path and r.success]
        failed = [r for r in results if not r.success]

        if failed:
            fail = failed[0]
            return StageResult(
                stage=PipelineStage.SCENE_DRAFT,
                success=False,
                message=f"Сцена {fail.scene_number}: {fail.message}",
                artifacts=[p for p in artifacts if p],
                metadata={
                    "completed": len(artifacts),
                    "total": len(ctx.scenes),
                    "failed_scene": fail.scene_number,
                },
            )

        return StageResult(
            stage=PipelineStage.SCENE_DRAFT,
            success=True,
            message=f"Все черновики сцен готовы ({len(artifacts)} mp4)",
            artifacts=[p for p in artifacts if p],
        )
