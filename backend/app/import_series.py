from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import build_engine
from app.series_import import (
    CATEGORY_LABELS,
    CREATE,
    ERROR,
    EXISTS,
    SKIP,
    ImportOptions,
    import_series,
    render_report,
)
from app.series_manifest import ManifestError, load_manifest, load_queue_csv, cross_check_queue
from app.storage import BlobStore


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Импорт производственного плана (JSON-манифест) в Mary Studio (WP-N1)."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--queue-csv", type=Path, help="сверка с CSV-очередью")
    parser.add_argument("--project-title", help="по умолчанию — project из манифеста")
    parser.add_argument(
        "--create-project", action="store_true", help="создать проект, если его нет"
    )
    parser.add_argument(
        "--references-dir",
        type=Path,
        action="append",
        default=[],
        help="каталог с файлами референсов (можно повторять)",
    )
    parser.add_argument("--fps", type=int, default=24, help="если в манифесте target_fps=null")
    parser.add_argument("--report", type=Path, help="путь markdown-отчёта при --apply")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="показать план без записи")
    mode.add_argument("--apply", action="store_true", help="импортировать и сохранить")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        queue_rows = load_queue_csv(args.queue_csv) if args.queue_csv else None
    except (ManifestError, OSError) as error:
        print(f"manifest: {error}", file=sys.stderr)
        return 2

    if queue_rows is not None:
        mismatches = cross_check_queue(manifest, queue_rows)
        if mismatches:
            print("CSV расходится с манифестом:", file=sys.stderr)
            for item in mismatches:
                print(f"  - {item}", file=sys.stderr)
            return 2

    settings = Settings()
    store = BlobStore(settings.storage_root)
    options = ImportOptions(
        project_title=args.project_title,
        create_project=args.create_project,
        reference_dirs=tuple(Path(item).expanduser() for item in args.references_dir),
        fps=args.fps,
    )
    engine = build_engine(settings)
    try:
        with Session(engine) as session:
            report = import_series(session, store, manifest, options, apply=args.apply)
            if args.apply:
                session.commit()
            else:
                session.rollback()
    finally:
        engine.dispose()

    markdown = render_report(report)
    if args.apply and args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown, encoding="utf-8")
        print(f"report: {args.report}")
    else:
        print(markdown)

    print(f"mode={report.mode} shots_created={report.shots_created} "
          f"shots_existing={report.shots_existing}")
    for category, bucket in report.counts().items():
        print(
            f"  {CATEGORY_LABELS.get(category, category)}: "
            f"create={bucket[CREATE]} exists={bucket[EXISTS]} "
            f"skip={bucket[SKIP]} error={bucket[ERROR]}"
        )
    if report.warnings:
        print(f"warnings={len(report.warnings)}")
    if report.errors:
        print(f"errors={len(report.errors)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
