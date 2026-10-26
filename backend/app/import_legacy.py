from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import build_engine
from app.legacy_import import (
    CATEGORY_LABELS,
    CREATE,
    EXISTS,
    SKIP,
    ImportOptions,
    render_report,
    run_import,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Импорт legacy-файлов characters/ и episodes/ в Mary Studio (WP-03)."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true", help="показать план без записи в БД и storage"
    )
    mode.add_argument("--apply", action="store_true", help="выполнить импорт и записать отчёт")
    parser.add_argument("--legacy-root", type=Path, help="корень legacy-дерева (по умолчанию MARY_LEGACY_ROOT)")
    parser.add_argument("--project-title", default="Mary Studio", help="название проекта в БД")
    parser.add_argument("--report", type=Path, help="путь отчёта (по умолчанию <legacy-root>/docs/MIGRATION-REPORT.md)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings()
    legacy_root = (args.legacy_root or settings.legacy_root).expanduser().resolve()
    if not legacy_root.is_dir():
        print(f"legacy root not found: {legacy_root}", file=sys.stderr)
        return 2

    options = ImportOptions(
        legacy_root=legacy_root,
        storage_root=settings.storage_root,
        project_title=args.project_title,
    )
    engine = build_engine(settings)
    try:
        with Session(engine) as session:
            report = run_import(session, options, apply=args.apply)
            if args.apply:
                session.commit()
            else:
                session.rollback()
    finally:
        engine.dispose()

    markdown = render_report(report)
    if args.apply:
        report_path = (args.report or legacy_root / "docs" / "MIGRATION-REPORT.md").expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown, encoding="utf-8")
        print(f"report: {report_path}")
    else:
        print(markdown)

    print(f"mode={report.mode} created={report.created}")
    for category, bucket in report.counts().items():
        print(
            f"  {CATEGORY_LABELS.get(category, category)}: "
            f"create={bucket[CREATE]} exists={bucket[EXISTS]} skip={bucket[SKIP]}"
        )
    if report.warnings:
        print(f"warnings={len(report.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
