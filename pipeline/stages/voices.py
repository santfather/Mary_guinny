from __future__ import annotations

from pipeline.models import EpisodeContext, PipelineStage, StageResult
from pipeline.stages.base import BaseStage
from pipeline.utils import parse_script


class VoicesStage(BaseStage):
    name = PipelineStage.VOICES.value

    async def run(self, ctx: EpisodeContext) -> StageResult:
        self._ensure_episode_dirs(ctx)

        if not self.settings.elevenlabs_api_key:
            return StageResult(
                stage=PipelineStage.VOICES,
                success=False,
                message="Не задан ELEVENLABS_API_KEY в .env",
            )

        script_path = ctx.episode_dir / "script.txt"
        if not script_path.exists():
            return StageResult(
                stage=PipelineStage.VOICES,
                success=False,
                message="Сценарий не найден.",
            )

        scenes = parse_script(script_path.read_text(encoding="utf-8"))
        pending_lines: list[dict] = []
        ready = []

        for scene in scenes:
            if scene.guinness_line:
                path = ctx.audio_dir / f"guinness_line_{scene.number:02d}.mp3"
                if path.exists():
                    ready.append(path)
                else:
                    pending_lines.append(
                        {"character": "guinness", "scene": scene.number, "text": scene.guinness_line}
                    )

            if scene.marija_line:
                path = ctx.audio_dir / f"marija_line_{scene.number:02d}.mp3"
                if path.exists():
                    ready.append(path)
                else:
                    pending_lines.append(
                        {"character": "marija", "scene": scene.number, "text": scene.marija_line}
                    )

        if pending_lines:
            return StageResult(
                stage=PipelineStage.VOICES,
                success=False,
                message=(
                    f"{len(pending_lines)} реплик ожидают синтеза в ElevenLabs. "
                    "См. prompts/elevenlabs_voice_notes.txt"
                ),
                artifacts=ready,
                metadata={"pending_lines": pending_lines},
            )

        return StageResult(
            stage=PipelineStage.VOICES,
            success=True,
            message=f"Все аудиореплики готовы ({len(ready)} файлов)",
            artifacts=ready,
        )
