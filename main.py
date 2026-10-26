#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys

from pipeline.config import CHARACTERS
from pipeline.comfyui.generator import CharacterReferenceGenerator, ComfyUISetupChecker
from pipeline.models import (
    CLOUD_PIPELINE_ORDER,
    LOCAL_PIPELINE_ORDER,
    PIPELINE_ORDER,
    PipelinePhase,
    PipelineStage,
)
from pipeline.orchestrator import Orchestrator


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mary_Guiness — оркестратор AI-видео пайплайна",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Создать структуру папок проекта")
    init_parser.set_defaults(func=_cmd_init)

    run_parser = subparsers.add_parser("run", help="Запустить этап(ы) пайплайна")
    run_parser.add_argument("--episode", default="ep01", help="ID эпизода (default: ep01)")
    run_parser.add_argument(
        "--phase",
        choices=[p.value for p in PipelinePhase],
        default=PipelinePhase.LOCAL.value,
        help="Фаза пайплайна: local (по умолчанию), cloud, full",
    )
    run_parser.add_argument("--prompt", help="Промпт для генерации сценария (stage: script)")
    run_parser.add_argument(
        "--stage",
        choices=[s.value for s in PipelineStage],
        help="Запустить один конкретный этап",
    )
    run_parser.add_argument(
        "--from",
        dest="from_stage",
        choices=[s.value for s in PipelineStage],
        help="Начальный этап диапазона",
    )
    run_parser.add_argument(
        "--to",
        dest="to_stage",
        choices=[s.value for s in PipelineStage],
        help="Конечный этап диапазона",
    )
    run_parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Не останавливаться при ошибке этапа",
    )
    run_parser.set_defaults(func=_cmd_run)

    status_parser = subparsers.add_parser("status", help="Проверить статус этапов")
    status_parser.add_argument("--episode", default="ep01", help="ID эпизода")
    status_parser.add_argument(
        "--phase",
        choices=[p.value for p in PipelinePhase],
        default=PipelinePhase.LOCAL.value,
        help="Фаза для проверки: local (по умолчанию), cloud, full",
    )
    status_parser.set_defaults(func=_cmd_status)

    stages_parser = subparsers.add_parser("stages", help="Список этапов пайплайна")
    stages_parser.set_defaults(func=_cmd_stages)

    comfy_parser = subparsers.add_parser("comfy", help="ComfyUI: проверка и генерация референсов")
    comfy_sub = comfy_parser.add_subparsers(dest="comfy_command", required=True)

    comfy_check = comfy_sub.add_parser("check", help="Проверить ComfyUI, ноды и модели")
    comfy_check.set_defaults(func=_cmd_comfy_check)

    comfy_gen = comfy_sub.add_parser("generate-ref", help="Сгенерировать одну позу персонажа")
    comfy_gen.add_argument("--character", required=True, choices=list(CHARACTERS))
    comfy_gen.add_argument("--pose", required=True, help="Имя позы, напр. reference_front")
    comfy_gen.add_argument("--force", action="store_true", help="Перегенерировать даже если файл есть")
    comfy_gen.set_defaults(func=_cmd_comfy_generate_ref)

    comfy_all = comfy_sub.add_parser("generate-all", help="Сгенерировать все 7 поз персонажа")
    comfy_all.add_argument("--character", required=True, choices=list(CHARACTERS))
    comfy_all.add_argument("--force", action="store_true")
    comfy_all.add_argument(
        "--skip-front",
        action="store_true",
        help="Не трогать reference_front.png — только 6 остальных поз через IP-Adapter",
    )
    comfy_all.set_defaults(func=_cmd_comfy_generate_all)

    return parser


def _phase_from_value(value: str) -> PipelinePhase:
    return PipelinePhase(value)


def _stage_from_value(value: str | None) -> PipelineStage | None:
    return PipelineStage(value) if value else None


async def _cmd_init(_: argparse.Namespace) -> int:
    orchestrator = Orchestrator()
    created = orchestrator.init_project_dirs()
    if created:
        print("Созданы папки:")
        for path in created:
            print(f"  + {path}")
    else:
        print("Структура проекта уже существует")
    return 0


async def _cmd_run(args: argparse.Namespace) -> int:
    orchestrator = Orchestrator()
    results = await orchestrator.run(
        episode_id=args.episode,
        prompt=args.prompt,
        phase=_phase_from_value(args.phase),
        stage=_stage_from_value(args.stage),
        from_stage=_stage_from_value(args.from_stage),
        to_stage=_stage_from_value(args.to_stage),
        stop_on_error=not args.continue_on_error,
    )
    return _print_results(results)


async def _cmd_status(args: argparse.Namespace) -> int:
    orchestrator = Orchestrator()
    results = await orchestrator.status(
        episode_id=args.episode,
        phase=_phase_from_value(args.phase),
    )
    return _print_results(results)


async def _cmd_stages(_: argparse.Namespace) -> int:
    print("Фаза 1 — локально (Ollama + ComfyUI):")
    for i, stage in enumerate(LOCAL_PIPELINE_ORDER, 1):
        print(f"  {i}. {stage.value}")

    print("\nФаза 2 — облако (после готовых персонажей и черновика):")
    for i, stage in enumerate(CLOUD_PIPELINE_ORDER, 1):
        print(f"  {i}. {stage.value}")

    print(f"\nПолный пайплайн: {len(PIPELINE_ORDER)} этапов (--phase full)")
    return 0


async def _cmd_comfy_check(_: argparse.Namespace) -> int:
    checker = ComfyUISetupChecker(Orchestrator().settings)
    report = await checker.check()

    print(f"ComfyUI: {'доступен' if report.comfyui_available else 'недоступен'}")
    if report.missing_nodes:
        print("\nНе хватает custom nodes:")
        for node in report.missing_nodes:
            print(f"  - {node}")
    else:
        print("\nCustom nodes: OK")

    if report.missing_models:
        print("\nНе хватает моделей:")
        for model in report.missing_models:
            print(f"  - {model}")
    else:
        print("Модели: OK")

    for note in report.notes:
        print(f"\n→ {note}")

    return 0 if report.comfyui_available else 1


async def _cmd_comfy_generate_ref(args: argparse.Namespace) -> int:
    generator = CharacterReferenceGenerator(Orchestrator().settings)
    result = await generator.generate_pose(args.character, args.pose, force=args.force)
    icon = "✓" if result.success else "✗"
    print(f"{icon} {args.character}/{args.pose} [{result.template}] — {result.message}")
    if result.output_path:
        print(f"    → {result.output_path}")
    return 0 if result.success else 1


async def _cmd_comfy_generate_all(args: argparse.Namespace) -> int:
    generator = CharacterReferenceGenerator(Orchestrator().settings)
    results = await generator.generate_all(
        args.character,
        force=args.force,
        skip_front=args.skip_front,
    )
    exit_code = 0
    for result in results:
        icon = "✓" if result.success else "✗"
        print(f"{icon} {result.character}/{result.pose} [{result.template}] — {result.message}")
        if result.output_path:
            print(f"    → {result.output_path}")
        if not result.success:
            exit_code = 1
    return exit_code


def _print_results(results: list) -> int:
    has_error = False
    for result in results:
        icon = "✓" if result.success else "✗"
        print(f"{icon} [{result.stage.value}] {result.message}")
        for artifact in result.artifacts:
            print(f"    → {artifact}")
        if not result.success:
            has_error = True
    return 1 if has_error else 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    exit_code = asyncio.run(args.func(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
