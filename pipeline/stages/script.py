from __future__ import annotations

import httpx

from pipeline.models import EpisodeContext, PipelineStage, StageResult
from pipeline.stages.base import BaseStage
from pipeline.utils import parse_script


class ScriptStage(BaseStage):
    name = PipelineStage.SCRIPT.value

    async def run(self, ctx: EpisodeContext) -> StageResult:
        self._ensure_episode_dirs(ctx)

        if not ctx.prompt:
            return StageResult(
                stage=PipelineStage.SCRIPT,
                success=False,
                message="Промпт не задан. Передайте --prompt для генерации сценария.",
            )

        script_text = await self._generate_script(ctx.prompt)
        script_path = ctx.episode_dir / "script.txt"
        script_path.write_text(script_text, encoding="utf-8")

        ctx.script_path = script_path
        ctx.scenes = parse_script(script_text)

        return StageResult(
            stage=PipelineStage.SCRIPT,
            success=True,
            message=f"Сценарий сохранён: {len(ctx.scenes)} сцен",
            artifacts=[script_path],
            metadata={"scene_count": len(ctx.scenes)},
        )

    async def _generate_script(self, prompt: str) -> str:
        url = f"{self.settings.ollama_base_url}/api/generate"
        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        text = data.get("response") or ""
        if not text.strip():
            raise ValueError("Ollama вернул пустой ответ")
        return text.strip()
