from __future__ import annotations

from pipeline.models import EpisodeContext, PipelineStage, StageResult
from pipeline.stages.base import BaseStage
from pipeline.utils import build_grok_prompt, load_character_bible, parse_script


class FinalVideoStage(BaseStage):
    name = PipelineStage.FINAL_VIDEO.value

    async def run(self, ctx: EpisodeContext) -> StageResult:
        self._ensure_episode_dirs(ctx)

        if not self.settings.grok_api_key and not self.settings.kling_api_key:
            return StageResult(
                stage=PipelineStage.FINAL_VIDEO,
                success=False,
                message="Не задан GROK_API_KEY или KLING_API_KEY в .env",
            )

        script_path = ctx.episode_dir / "script.txt"
        if not script_path.exists():
            return StageResult(
                stage=PipelineStage.FINAL_VIDEO,
                success=False,
                message="Сценарий не найден.",
            )

        scenes = parse_script(script_path.read_text(encoding="utf-8"))
        if not scenes:
            return StageResult(
                stage=PipelineStage.FINAL_VIDEO,
                success=False,
                message="Нет сцен для финальной генерации.",
            )

        template_path = self.settings.prompts_dir() / "grok_video_template.txt"
        guinness_bible = load_character_bible(
            self.settings.character_dir("guinness") / "character_bible.txt"
        )

        pending: list[dict] = []
        ready = []

        for scene in scenes:
            output = ctx.scenes_dir / f"scene_{scene.number:02d}_final.mp4"
            if output.exists():
                ready.append(output)
                continue

            action = scene.action or scene.title
            prompt = build_grok_prompt(template_path, guinness_bible, action)
            pending.append({"scene": scene.number, "output": str(output), "prompt": prompt})

        if pending:
            provider = "Grok" if self.settings.grok_api_key else "Kling"
            return StageResult(
                stage=PipelineStage.FINAL_VIDEO,
                success=False,
                message=(
                    f"{len(pending)} финальных клипов ожидают генерации через {provider}. "
                    "API-интеграция будет добавлена; пока используйте промпты из metadata."
                ),
                artifacts=ready,
                metadata={"pending_clips": pending, "provider": provider},
            )

        return StageResult(
            stage=PipelineStage.FINAL_VIDEO,
            success=True,
            message=f"Все финальные клипы готовы ({len(ready)} файлов)",
            artifacts=ready,
        )
