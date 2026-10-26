from __future__ import annotations

from pathlib import Path

from pipeline.config import CHARACTER_POSES, CHARACTERS
from pipeline.models import EpisodeContext, PipelineStage, StageResult
from pipeline.stages.base import BaseStage


class CharacterRefsStage(BaseStage):
    name = PipelineStage.CHARACTER_REFS.value

    async def run(self, ctx: EpisodeContext) -> StageResult:
        missing: list[str] = []
        existing: list[Path] = []

        for character in CHARACTERS:
            char_dir = self.settings.character_dir(character)
            char_dir.mkdir(parents=True, exist_ok=True)

            bible_path = char_dir / "character_bible.txt"
            if not bible_path.exists():
                missing.append(f"{character}/character_bible.txt")

            for pose in CHARACTER_POSES:
                ref_path = char_dir / f"{pose}.png"
                if ref_path.exists():
                    existing.append(ref_path)
                else:
                    missing.append(f"{character}/{pose}.png")

        workflows_dir = self.settings.workflows_dir()
        has_workflow = (workflows_dir / "character_pose_gen.json").exists() or (
            workflows_dir / "character_pose_gen.api.json"
        ).exists()
        if not has_workflow:
            missing.append("comfyui-workflows/character_pose_gen.json")

        if missing:
            return StageResult(
                stage=PipelineStage.CHARACTER_REFS,
                success=False,
                message=(
                    f"Не хватает {len(missing)} артефактов. "
                    "Запустите: python main.py comfy generate-all --character <name>"
                ),
                artifacts=existing,
                metadata={"missing": missing, "existing_count": len(existing)},
            )

        return StageResult(
            stage=PipelineStage.CHARACTER_REFS,
            success=True,
            message=f"Все референсы на месте ({len(existing)} изображений)",
            artifacts=existing,
            metadata={"existing_count": len(existing)},
        )
