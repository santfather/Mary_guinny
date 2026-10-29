from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT, Settings
from app.db import build_engine
from app.models import Episode, Project, PromptRevision, ReferenceAsset, Shot
from app.models import Scene as SceneRow
from app.series_import import asset_names
from app.series_manifest import (
    DEFAULT_TIMELINE_FPS,
    ManifestError,
    SeriesManifest,
    cross_check_queue,
    load_manifest,
    load_queue_csv,
    snap_frame_count,
)
from app.storage import BlobStore, sha256_file

OK = "ok"
WARN = "warn"
FAIL = "fail"

# Целевые разрешения по аспекту: 9:16 — вертикаль для соцсетей.
TARGET_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}
# Статические границы LTX2MLXGenerate: (min, max, step).
NODE_LIMITS: dict[str, tuple[int, int, int]] = {
    "width": (64, 3840, 8),
    "height": (64, 2160, 8),
    "num_frames": (9, 257, 8),
    "frame_rate": (1, 60, 1),
}
REQUIRED_GENERATE_INPUTS = (
    "prompt",
    "image",
    "seed",
    "width",
    "height",
    "num_frames",
    "frame_rate",
    "filename_prefix",
)
MIN_FREE_BYTES = 5 * 1024**3


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


@dataclass
class PreflightReport:
    checks: list[Check] = field(default_factory=list)
    shots: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str) -> None:
        self.checks.append(Check(name, status, detail))

    @property
    def status(self) -> str:
        if any(check.status == FAIL for check in self.checks):
            return FAIL
        if any(check.status == WARN for check in self.checks):
            return WARN
        return OK

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "checks": [
                {"name": check.name, "status": check.status, "detail": check.detail}
                for check in self.checks
            ],
            "shots": self.shots,
            "warnings": list(self.warnings),
        }

    def render_text(self) -> str:
        marks = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL"}
        lines = [f"Preflight: {self.status.upper()}", ""]
        for check in self.checks:
            lines.append(f"[{marks.get(check.status, check.status)}] {check.name}: {check.detail}")
        if self.warnings:
            lines += ["", "Предупреждения:"]
            lines += [f"  - {item}" for item in self.warnings]
        return "\n".join(lines)


def _find_scene(
    session: Session, project: Project, manifest: SeriesManifest
) -> SceneRow | None:
    episode = session.scalar(
        select(Episode)
        .where(Episode.project_id == project.id, Episode.title == manifest.episode_title)
        .order_by(Episode.sequence_no)
    )
    statement = select(SceneRow).where(
        SceneRow.project_id == project.id,
        SceneRow.title == manifest.episode_title,
    )
    if episode is not None:
        statement = statement.where(SceneRow.episode_id == episode.id)
    return session.scalar(statement.order_by(SceneRow.sequence_no))


def _resolve_references(
    session: Session, store: BlobStore, project: Project, manifest: SeriesManifest
) -> tuple[dict[str, ReferenceAsset], list[str], list[str]]:
    """Разрешение имён: проект + файл в storage + совпадение sha256."""

    index: dict[str, list[ReferenceAsset]] = {}
    for asset in session.scalars(
        select(ReferenceAsset)
        .where(ReferenceAsset.project_id == project.id)
        .order_by(ReferenceAsset.created_at)
    ):
        for name in asset_names(asset):
            index.setdefault(name, []).append(asset)

    resolved: dict[str, ReferenceAsset] = {}
    problems: list[str] = []
    warnings: list[str] = []
    for name in manifest.reference_names:
        candidates = index.get(name, [])
        if not candidates:
            problems.append(f"{name}: нет референса с таким именем в проекте")
            continue
        verified: list[ReferenceAsset] = []
        for asset in candidates:
            if asset.project_id != project.id:
                warnings.append(f"{name}: референс из другого проекта — пропущен")
                continue
            try:
                path = store.resolve(asset.storage_key)
            except Exception:
                warnings.append(f"{name}: некорректный storage_key у {asset.id}")
                continue
            if not path.is_file():
                warnings.append(f"{name}: файла нет в storage ({asset.storage_key})")
                continue
            if sha256_file(path) != asset.sha256:
                warnings.append(f"{name}: sha256 файла не совпадает с записью {asset.id}")
                continue
            verified.append(asset)
        if len(verified) == 1:
            resolved[name] = verified[0]
        elif not verified:
            problems.append(f"{name}: совпадения по имени не прошли проверку файла")
        else:
            problems.append(
                f"{name}: неоднозначно, подходят {', '.join(str(item.id) for item in verified)}"
            )
    return resolved, problems, warnings


def _load_workflow(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("workflow должен быть JSON-объектом")
    return data


def _nodes_by_class(workflow: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type")
        if isinstance(class_type, str):
            result.setdefault(class_type, []).append(str(node_id))
    return result


def run_preflight(
    session: Session,
    store: BlobStore,
    manifest: SeriesManifest,
    *,
    project: Project | None = None,
    project_title: str | None = None,
    queue_rows: list[dict[str, str]] | None = None,
    workflow_path: Path | None = None,
    fps: int = DEFAULT_TIMELINE_FPS,
    object_info: dict[str, Any] | None = None,
) -> PreflightReport:
    report = PreflightReport()
    effective_fps = manifest.effective_fps(fps)
    expected = len(manifest.shots)

    report.add(
        "manifest",
        OK,
        f"{expected} шотов, {len(manifest.reference_names)} уникальных референсов, "
        f"{len(manifest.blocked_shots)} сюжетных без стартового кадра, "
        f"аспект {manifest.target_aspect_ratio}, fps={effective_fps}",
    )

    if queue_rows is None:
        report.add("queue_csv", WARN, "CSV не передан — сверка с очередью не выполнялась")
    else:
        mismatches = cross_check_queue(manifest, queue_rows)
        if mismatches:
            report.add("queue_csv", FAIL, "; ".join(mismatches[:5]))
            report.warnings.extend(mismatches[5:])
        else:
            report.add("queue_csv", OK, f"{len(queue_rows)} строк совпадают с манифестом")

    title = project_title or manifest.project_title
    if project is None:
        project = session.scalar(select(Project).where(Project.title == title))
    if project is None:
        report.add("project", FAIL, f"проект «{title}» не найден: сначала выполните импорт")
        return report
    report.add("project", OK, f"«{project.title}» id={project.id}")

    scene = _find_scene(session, project, manifest)
    if scene is None:
        report.add("import", FAIL, "сцена плана не найдена: сначала выполните импорт")
        return report

    shots = list(
        session.scalars(
            select(Shot).where(Shot.scene_id == scene.id).order_by(Shot.sequence_no)
        )
    )
    by_order = {shot.sequence_no: shot for shot in shots}
    missing = [str(item.order) for item in manifest.shots if item.order not in by_order]
    if missing:
        report.add("shots", FAIL, f"в БД нет шотов с порядком: {', '.join(missing)}")
    elif len(shots) != expected:
        report.add(
            "shots", WARN, f"в сцене {len(shots)} шотов при {expected} в манифесте"
        )
    else:
        report.add("shots", OK, f"{len(shots)} шотов, порядок 1..{expected}")

    prompt_mismatch: list[str] = []
    for item in manifest.shots:
        shot = by_order.get(item.order)
        if shot is None:
            continue
        latest = session.scalar(
            select(PromptRevision)
            .where(
                PromptRevision.shot_id == shot.id,
                PromptRevision.prompt_type == "motion",
            )
            .order_by(PromptRevision.version.desc())
        )
        if latest is None or latest.prompt != item.prompt_original:
            prompt_mismatch.append(item.shot_key)
    if prompt_mismatch:
        report.add(
            "prompts", FAIL, f"промпт расходится с манифестом: {', '.join(prompt_mismatch[:5])}"
        )
    else:
        report.add("prompts", OK, "исходный текст каждого промпта сохранён без изменений")

    resolved, problems, ref_warnings = _resolve_references(
        session, store, project, manifest
    )
    report.warnings.extend(ref_warnings)
    approved = [item for item in resolved.values() if item.status == "approved"]
    missing_reference_shots = [
        item.shot_key
        for item in manifest.shots
        if item.reference_filename and item.reference_filename not in resolved
    ]
    if problems:
        detail = (
            f"разрешено {len(resolved)} из {len(manifest.reference_names)}; "
            + "; ".join(problems[:4])
        )
        if missing_reference_shots:
            detail += f"; блокированы: {', '.join(missing_reference_shots)}"
        report.add("references", FAIL, detail)
    elif len(approved) != len(resolved):
        report.add(
            "references",
            WARN,
            f"разрешено {len(resolved)} из {len(manifest.reference_names)}, "
            f"утверждено {len(approved)} — остальные нужно утвердить вручную",
        )
    else:
        report.add(
            "references",
            OK,
            f"все {len(resolved)} референсов разрешены, файлы и sha256 совпадают, "
            "статус approved",
        )

    start_ready = 0
    blocked: list[str] = []
    for item in manifest.shots:
        shot = by_order.get(item.order)
        ready = bool(shot and shot.start_keyframe_artifact_id)
        if ready:
            start_ready += 1
        elif item.requires_start_frame():
            blocked.append(item.shot_key)
        reference_ok = (
            item.reference_filename is None or item.reference_filename in resolved
        )
        # Блокировка выводится из данных, а не из enum статусов Shot (схема не меняется).
        reason = None
        if not reference_ok:
            reason = "missing_reference"
        elif not ready:
            reason = "missing_start_frame"
        report.shots.append(
            {
                "order": item.order,
                "shot_key": item.shot_key,
                "category": item.category,
                "frames": item.frames(effective_fps),
                "start_frame_ready": ready,
                "requires_start_frame": item.requires_start_frame(),
                "reference_resolved": reference_ok,
                "blocked": reason,
                "output_name_prefix": item.output_name_prefix,
            }
        )
    if start_ready == expected:
        report.add("start_frames", OK, f"{start_ready} из {expected} утверждены")
    else:
        report.add(
            "start_frames",
            WARN,
            f"утверждено {start_ready} из {expected}; сюжетных без исходного кадра: "
            f"{len(blocked)} ({', '.join(blocked) or '—'}) — их кадры утверждает человек",
        )

    path = Path(workflow_path) if workflow_path else (
        REPO_ROOT / "comfyui-workflows" / "ltx23_mlx_q4_i2v.api.json"
    )
    if not path.is_file():
        report.add("workflow", FAIL, f"workflow не найден: {path}")
    else:
        try:
            workflow = _load_workflow(path)
        except (json.JSONDecodeError, ValueError) as error:
            report.add("workflow", FAIL, f"{path.name}: {error}")
        else:
            by_class = _nodes_by_class(workflow)
            generate = by_class.get("LTX2MLXGenerate", [])
            load_image = by_class.get("LoadImage", [])
            loader = by_class.get("LTX2MLXModelLoader", [])
            problems = []
            if not generate:
                problems.append("нет ноды LTX2MLXGenerate")
            if not load_image:
                problems.append("нет ноды LoadImage")
            if not loader:
                problems.append("нет ноды LTX2MLXModelLoader")
            if generate:
                inputs = (workflow.get(generate[0]) or {}).get("inputs") or {}
                absent = [name for name in REQUIRED_GENERATE_INPUTS if name not in inputs]
                if absent:
                    problems.append(f"нет входов: {', '.join(absent)}")
                if "image" in inputs and not (
                    isinstance(inputs["image"], list)
                    and str(inputs["image"][0]) in load_image
                ):
                    problems.append("image не связан с LoadImage")
            if problems:
                report.add("workflow", FAIL, "; ".join(problems))
            else:
                report.add(
                    "workflow",
                    OK,
                    f"nodes: LoadImage={', '.join(load_image)}, "
                    f"loader={', '.join(loader)}, generate={', '.join(generate)}; "
                    f"входы {', '.join(REQUIRED_GENERATE_INPUTS)} на месте",
                )

    width, height = TARGET_RESOLUTIONS.get(manifest.target_aspect_ratio, (0, 0))
    frames = snap_frame_count(
        max(item.duration_seconds[1] for item in manifest.shots), effective_fps
    )
    limits = dict(NODE_LIMITS)
    if object_info is not None:
        live = (object_info.get("LTX2MLXGenerate") or {}).get("input", {}).get("required", {})
        for name in ("width", "height", "num_frames", "frame_rate"):
            spec = live.get(name)
            if isinstance(spec, list) and spec and isinstance(spec[0], list):
                values = [item for item in spec[0] if isinstance(item, int)]
                if len(values) >= 2:
                    step = values[2] if len(values) > 2 and isinstance(values[2], int) else 1
                    limits[name] = (values[0], values[1], step)
    problems = []
    if width == 0:
        problems.append(f"нет целевого разрешения для {manifest.target_aspect_ratio}")
    for name, value in (("width", width), ("height", height), ("num_frames", frames)):
        if name in ("width", "height") and value == 0:
            continue
        low, high, step = limits[name]
        # num_frames у LTX2MLX — это 8k+1, разрешение — просто кратное шагу.
        offset = 1 if name == "num_frames" else 0
        if not low <= value <= high:
            problems.append(f"{name}={value} вне {low}..{high}")
        elif (value - offset) % step:
            shape = "8k+1" if offset else f"кратности {step}"
            problems.append(f"{name}={value} не соответствует {shape}")
    if problems:
        report.add("video_params", FAIL, "; ".join(problems))
    else:
        report.add(
            "video_params",
            WARN,
            f"{width}x{height}, {frames} кадров @ {effective_fps} fps "
            f"({frames / effective_fps:.2f} с) укладываются в границы ноды "
            f"({limits['height'][1]}p, {limits['num_frames'][1]} кадров), "
            "но реальная совместимость не подтверждена рендером",
        )
    if object_info is None:
        report.warnings.append(
            "object_info ComfyUI не запрошен: границы взяты из статических констант"
        )

    try:
        usage = shutil.disk_usage(store.root)
    except OSError as error:
        report.add("disk", FAIL, f"не удалось получить свободное место: {error}")
    else:
        free_gib = usage.free / 1024**3
        report.add(
            "disk",
            OK if usage.free >= MIN_FREE_BYTES else FAIL,
            f"свободно {free_gib:.1f} ГиБ в {store.root} "
            f"(минимум {MIN_FREE_BYTES / 1024**3:.0f} ГиБ)",
        )

    duplicates = len({item.output_name_prefix for item in manifest.shots}) != expected
    report.add(
        "outputs",
        FAIL if duplicates else OK,
        "префиксы вывода уникальны: nlb/<NLB_XX>/<attempt_id>"
        if not duplicates
        else "обнаружены повторяющиеся output_name_prefix",
    )

    return report


def _fetch_object_info(url: str, node: str, timeout: float = 2.0) -> dict[str, Any] | None:
    import urllib.parse
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"{url.rstrip('/')}/object_info/{urllib.parse.quote(node)}", timeout=timeout
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preflight производственного плана: шоты, референсы, кадры, workflow."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--queue-csv", type=Path)
    parser.add_argument("--project-title", help="по умолчанию — project из манифеста")
    parser.add_argument("--project-id", type=uuid.UUID)
    parser.add_argument("--comfy-url", help="например http://127.0.0.1:8188")
    parser.add_argument("--json", action="store_true", help="вывести отчёт JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = Settings()
    store = BlobStore(settings.storage_root)
    try:
        manifest = load_manifest(args.manifest)
        queue_rows = load_queue_csv(args.queue_csv) if args.queue_csv else None
    except (ManifestError, OSError) as error:
        print(f"manifest: {error}", file=sys.stderr)
        return 2

    object_info = (
        _fetch_object_info(args.comfy_url, "LTX2MLXGenerate") if args.comfy_url else None
    )
    engine = build_engine(settings)
    try:
        with Session(engine) as session:
            project = (
                session.get(Project, args.project_id) if args.project_id else None
            )
            report = run_preflight(
                session,
                store,
                manifest,
                project=project,
                project_title=args.project_title,
                queue_rows=queue_rows,
                object_info=object_info,
            )
    finally:
        engine.dispose()

    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.render_text())
    return 0 if report.status != FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
