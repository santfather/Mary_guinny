"""Data-fix: motion-промпты сюжетных шотов NLB-21…27 (версии 2).

Эндпоинта для prompt_revisions нет, поэтому новая ревизия создаётся этим CLI.
Ничего, кроме `prompt_revisions`, не меняется: шоты, референсы, артефакты и
попытки остаются прежними. Прошлые ревизии не перезаписываются (S10).
"""

from __future__ import annotations

from dataclasses import dataclass

import argparse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import build_engine
from app.models import Project, PromptRevision, Scene, Shot

DEFAULT_PROJECT_TITLE = "The Nine Lives Band"
DEFAULT_SCENE_TITLE = "Ночной тыгыдык"

# Тексты задания: дословно, без добавок.
PROMPTS: dict[int, str] = {
    21: "The sable Burmese cat slowly turns its head toward the sleeping people. "
    "Gentle breathing, subtle ear movement, soft moonlight. Fixed camera, "
    "one continuous realistic cinematic shot.",
    22: "The Burmese cat gently taps a small candy wrapper once with one front paw. "
    "The wrapper slides a short distance across the floor. Stable camera, "
    "natural feline anatomy, continuous motion.",
    23: "The Burmese cat runs forward on all four paws through the dim nighttime "
    "corridor. Natural feline running gait, stable body proportions, low fixed "
    "camera, continuous realistic motion.",
    24: "The Burmese cat slowly extends one front paw and gently nudges the ceramic "
    "cup a short distance toward the table edge. The cup remains upright and does "
    "not fall. Fixed camera, realistic feline movement.",
    25: "The Burmese cat stretches gently on the sofa, slowly lifts its head and "
    "looks toward the camera. Natural breathing, subtle tail movement, stable "
    "framing, realistic continuous motion.",
    26: "The Burmese cat sits beside the moonlit window and slowly raises its head. "
    "Subtle ear and whisker movement, gentle breathing, fixed cinematic camera, "
    "realistic continuous motion.",
    27: "The Burmese cat looks down at the empty food bowl, slowly raises its head "
    "and opens its mouth in a short natural meow. Fixed camera, stable anatomy, "
    "realistic continuous motion.",
}

PROMPT_SOURCE = "human_prompt_override"


@dataclass(frozen=True)
class PromptChange:
    sequence_no: int
    before_version: int | None
    after_version: int


def set_shot_prompts(
    session: Session,
    project_title: str,
    scene_title: str,
    prompts: dict[int, str],
    *,
    apply: bool,
) -> tuple[list[PromptChange], list[str]]:
    """Создаёт новую motion-ревизию, если текст отличается от последней."""

    project = session.scalar(select(Project).where(Project.title == project_title))
    if project is None:
        raise LookupError(f"project not found: {project_title}")

    scenes = list(
        session.scalars(
            select(Scene).where(
                Scene.project_id == project.id, Scene.title == scene_title
            )
        )
    )
    if not scenes:
        raise LookupError(f"scene not found: {scene_title}")
    if len(scenes) > 1:
        raise LookupError(f"scene title is ambiguous: {scene_title}")

    changes: list[PromptChange] = []
    skipped: list[str] = []
    for sequence_no, prompt in sorted(prompts.items()):
        label = f"NLB-{sequence_no:02d}"
        shot = session.scalar(
            select(Shot).where(
                Shot.scene_id == scenes[0].id, Shot.sequence_no == sequence_no
            )
        )
        if shot is None:
            skipped.append(f"{label}: shot not found")
            continue

        latest = session.scalar(
            select(PromptRevision)
            .where(
                PromptRevision.shot_id == shot.id,
                PromptRevision.prompt_type == "motion",
            )
            .order_by(PromptRevision.version.desc())
            .limit(1)
        )
        if latest is not None and latest.prompt == prompt:
            skipped.append(f"{label}: already motion v{latest.version}")
            continue

        parameters = (latest.parameters_json or {}) if latest is not None else {}
        shot_key = parameters.get("shot_key")
        version = (latest.version + 1) if latest is not None else 1
        revision = PromptRevision(
            shot_id=shot.id,
            prompt_type="motion",
            version=version,
            prompt=prompt,
            parameters_json={
                "source": PROMPT_SOURCE,
                "shot_key": shot_key if isinstance(shot_key, str) else label,
                "previous_version": latest.version if latest is not None else None,
            },
        )
        session.add(revision)
        changes.append(
            PromptChange(
                sequence_no=sequence_no,
                before_version=latest.version if latest is not None else None,
                after_version=version,
            )
        )

    if apply:
        session.commit()
    else:
        session.rollback()
    return changes, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Motion-промпты сюжетных шотов NLB-21…27 (новая ревизия)"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--project-title", default=DEFAULT_PROJECT_TITLE)
    parser.add_argument("--scene-title", default=DEFAULT_SCENE_TITLE)
    args = parser.parse_args(argv)

    engine = build_engine(Settings())
    try:
        with Session(engine) as session:
            try:
                changes, skipped = set_shot_prompts(
                    session,
                    args.project_title,
                    args.scene_title,
                    PROMPTS,
                    apply=args.apply,
                )
            except LookupError as error:
                print(f"error: {error}")
                return 1
    finally:
        engine.dispose()

    print(f"mode={'apply' if args.apply else 'dry-run'} changes={len(changes)}")
    for change in changes:
        print(
            f"NLB-{change.sequence_no:02d}: motion v{change.before_version}"
            f" -> v{change.after_version}"
        )
    for reason in skipped:
        print(f"skip {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
