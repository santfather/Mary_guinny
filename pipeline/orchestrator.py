from __future__ import annotations

from pipeline.config import Settings
from pipeline.models import (
    PHASE_ORDERS,
    EpisodeContext,
    PipelinePhase,
    PipelineStage,
    StageResult,
)
from pipeline.stages.assembly import AssemblyStage
from pipeline.stages.base import BaseStage
from pipeline.stages.character_refs import CharacterRefsStage
from pipeline.stages.final_video import FinalVideoStage
from pipeline.stages.lipsync import LipsyncStage
from pipeline.stages.music import MusicStage
from pipeline.stages.scene_draft import SceneDraftStage
from pipeline.stages.script import ScriptStage
from pipeline.stages.voices import VoicesStage


class Orchestrator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings.from_env()
        self._stages: dict[PipelineStage, BaseStage] = {
            PipelineStage.SCRIPT: ScriptStage(self.settings),
            PipelineStage.CHARACTER_REFS: CharacterRefsStage(self.settings),
            PipelineStage.SCENE_DRAFT: SceneDraftStage(self.settings),
            PipelineStage.FINAL_VIDEO: FinalVideoStage(self.settings),
            PipelineStage.VOICES: VoicesStage(self.settings),
            PipelineStage.LIPSYNC: LipsyncStage(self.settings),
            PipelineStage.MUSIC: MusicStage(self.settings),
            PipelineStage.ASSEMBLY: AssemblyStage(self.settings),
        }

    def resolve_stages(
        self,
        phase: PipelinePhase = PipelinePhase.LOCAL,
        stage: PipelineStage | None = None,
        from_stage: PipelineStage | None = None,
        to_stage: PipelineStage | None = None,
    ) -> list[PipelineStage]:
        if stage:
            return [stage]

        order = PHASE_ORDERS[phase]
        start = from_stage or order[0]
        end = to_stage or order[-1]

        if start not in order or end not in order:
            raise ValueError(
                f"Этап {start.value} или {end.value} не входит в фазу {phase.value}. "
                f"Доступны: {', '.join(s.value for s in order)}"
            )

        start_idx = order.index(start)
        end_idx = order.index(end)
        if start_idx > end_idx:
            raise ValueError(f"from_stage ({start}) не может быть позже to_stage ({end})")

        return order[start_idx : end_idx + 1]

    async def run(
        self,
        episode_id: str,
        prompt: str | None = None,
        phase: PipelinePhase = PipelinePhase.LOCAL,
        stage: PipelineStage | None = None,
        from_stage: PipelineStage | None = None,
        to_stage: PipelineStage | None = None,
        stop_on_error: bool = True,
    ) -> list[StageResult]:
        ctx = EpisodeContext(
            episode_id=episode_id,
            root=self.settings.project_root,
            prompt=prompt,
        )
        stages = self.resolve_stages(
            phase=phase,
            stage=stage,
            from_stage=from_stage,
            to_stage=to_stage,
        )
        results: list[StageResult] = []

        for stage_name in stages:
            handler = self._stages[stage_name]
            result = await handler.run(ctx)
            results.append(result)

            if not result.success and stop_on_error:
                break

        return results

    async def status(
        self,
        episode_id: str,
        phase: PipelinePhase = PipelinePhase.LOCAL,
    ) -> list[StageResult]:
        return await self.run(episode_id=episode_id, phase=phase, stop_on_error=False)

    def init_project_dirs(self) -> list[str]:
        created: list[str] = []
        dirs = [
            self.settings.project_root / "characters" / "guinness",
            self.settings.project_root / "characters" / "marija",
            self.settings.project_root / "episodes" / "ep01" / "scenes",
            self.settings.project_root / "episodes" / "ep01" / "audio",
            self.settings.project_root / "comfyui-input" / "poses",
            self.settings.project_root / "comfyui-workflows",
            self.settings.project_root / "prompts",
            self.settings.project_root / "exports",
        ]
        for path in dirs:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                created.append(str(path.relative_to(self.settings.project_root)))
        return created
