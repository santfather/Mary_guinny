from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.config import Settings
from pipeline.models import PipelinePhase, PipelineStage
from pipeline.orchestrator import Orchestrator
from pipeline.utils import parse_script


SAMPLE_SCRIPT = """
СЦЕНА 1: Утро на диване
ГИННЕСС: Ещё пять минут.
МАРИЯ: Ты уже спал двенадцать часов!
ДЕЙСТВИЕ: Кот лежит на диване, Мария машет телефоном.

СЦЕНА 2: Попытка работать
ГИННЕСС: Работа — это иллюзия.
МАРИЯ: Мне нужно отправить отчёт!
ДЕЙСТВИЕ: Кот ложится на клавиатуру ноутбука.
"""


def test_parse_script_extracts_scenes():
    scenes = parse_script(SAMPLE_SCRIPT)
    assert len(scenes) == 2
    assert scenes[0].number == 1
    assert scenes[0].guinness_line == "Ещё пять минут."
    assert scenes[0].marija_line == "Ты уже спал двенадцать часов!"
    assert "диване" in (scenes[0].action or "")


def test_parse_script_empty():
    assert parse_script("") == []
    assert parse_script(None) == []  # type: ignore[arg-type]


def test_orchestrator_resolve_single_stage():
    orch = Orchestrator()
    stages = orch.resolve_stages(stage=PipelineStage.SCRIPT)
    assert stages == [PipelineStage.SCRIPT]


def test_orchestrator_resolve_local_phase_by_default():
    orch = Orchestrator()
    stages = orch.resolve_stages()
    assert stages == [
        PipelineStage.CHARACTER_REFS,
        PipelineStage.SCRIPT,
        PipelineStage.SCENE_DRAFT,
    ]


def test_orchestrator_resolve_cloud_phase():
    orch = Orchestrator()
    stages = orch.resolve_stages(phase=PipelinePhase.CLOUD)
    assert stages[0] == PipelineStage.FINAL_VIDEO
    assert stages[-1] == PipelineStage.ASSEMBLY


def test_orchestrator_resolve_range():
    orch = Orchestrator()
    stages = orch.resolve_stages(
        phase=PipelinePhase.FULL,
        from_stage=PipelineStage.SCENE_DRAFT,
        to_stage=PipelineStage.VOICES,
    )
    assert stages[0] == PipelineStage.SCENE_DRAFT
    assert stages[-1] == PipelineStage.VOICES
    assert PipelineStage.FINAL_VIDEO in stages


@pytest.mark.asyncio
async def test_script_stage_saves_file(tmp_path: Path):
    script_dir = tmp_path / "episodes" / "ep01"
    script_dir.mkdir(parents=True)

    orch = Orchestrator()
    orch.settings = type(orch.settings)(
        project_root=tmp_path,
        ollama_base_url="http://localhost:11434",
        ollama_model="catshow",
        comfyui_base_url="http://127.0.0.1:8188",
        comfyui_root=None,
        grok_api_key=None,
        kling_api_key=None,
        elevenlabs_api_key=None,
        hedra_api_key=None,
        suno_api_key=None,
        litellm_model="ollama/catshow",
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {"response": SAMPLE_SCRIPT}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.return_value = mock_response

    with patch("pipeline.stages.script.httpx.AsyncClient", return_value=mock_client):
        results = await orch.run(
            episode_id="ep01",
            prompt="Напиши эпизод про кота",
            stage=PipelineStage.SCRIPT,
        )

    assert results[0].success is True
    script_path = tmp_path / "episodes" / "ep01" / "script.txt"
    assert script_path.exists()
    assert "СЦЕНА 1" in script_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_character_refs_stage_reports_missing(tmp_path: Path):
    (tmp_path / "characters" / "guinness").mkdir(parents=True)
    (tmp_path / "characters" / "marija").mkdir(parents=True)
    (tmp_path / "characters" / "guinness" / "character_bible.txt").write_text("bible")

    settings = Settings(
        project_root=tmp_path,
        ollama_base_url="http://localhost:11434",
        ollama_model="catshow",
        comfyui_base_url="http://127.0.0.1:8188",
        comfyui_root=None,
        grok_api_key=None,
        kling_api_key=None,
        elevenlabs_api_key=None,
        hedra_api_key=None,
        suno_api_key=None,
        litellm_model="ollama/catshow",
    )
    orch = Orchestrator(settings=settings)

    results = await orch.run(episode_id="ep01", stage=PipelineStage.CHARACTER_REFS)
    assert results[0].success is False
    assert "missing" in results[0].metadata
