from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import build_engine
from app.models import CHARACTER_KINDS, Character, Project

DEFAULT_PROJECT_TITLE = "Mary Studio"
DEFAULT_KINDS: dict[str, str] = {"guinness": "cat", "marija": "human"}


@dataclass(frozen=True)
class KindChange:
    slug: str
    before: str
    after: str


def set_character_kinds(
    session: Session,
    project_title: str,
    mapping: dict[str, str],
    *,
    apply: bool,
) -> tuple[list[KindChange], list[str]]:
    """Правит только characters.kind; файлы, storage и metadata не затрагиваются."""

    unknown = sorted(set(mapping.values()) - set(CHARACTER_KINDS))
    if unknown:
        raise LookupError(f"unsupported character kinds: {', '.join(unknown)}")

    project = session.scalar(select(Project).where(Project.title == project_title))
    if project is None:
        raise LookupError(f"project not found: {project_title}")

    changes: list[KindChange] = []
    skipped: list[str] = []
    for slug, target in mapping.items():
        character = session.scalar(
            select(Character).where(
                Character.project_id == project.id,
                Character.slug == slug,
            )
        )
        if character is None:
            skipped.append(f"{slug}: not found")
            continue
        if character.kind == target:
            skipped.append(f"{slug}: already {target}")
            continue
        if character.kind != "other":
            skipped.append(f"{slug}: kind={character.kind}, manual review required")
            continue
        changes.append(KindChange(slug=slug, before=character.kind, after=target))
        character.kind = target

    if apply:
        session.commit()
    else:
        session.rollback()
    return changes, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Корректировка characters.kind для импортированных персонажей"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--project-title", default=DEFAULT_PROJECT_TITLE)
    args = parser.parse_args(argv)

    engine = build_engine(Settings())
    try:
        with Session(engine) as session:
            try:
                changes, skipped = set_character_kinds(
                    session,
                    args.project_title,
                    DEFAULT_KINDS,
                    apply=args.apply,
                )
            except LookupError as error:
                print(f"error: {error}")
                return 1
    finally:
        engine.dispose()

    print(f"mode={'apply' if args.apply else 'dry-run'} changes={len(changes)}")
    for change in changes:
        print(f"{change.slug}: {change.before} -> {change.after}")
    for reason in skipped:
        print(f"skip {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
