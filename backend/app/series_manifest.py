from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Контракт манифеста производственного плана (WP-N1). Модуль не работает с БД.
SUPPORTED_SCHEMA_VERSIONS = ("1.0",)
DEFAULT_TIMELINE_FPS = 24
# Границы, снятые с LTX2MLXGenerate (runtime/ComfyUI/custom_nodes/comfyui-ltx2-mlx).
FRAMES_MIN = 9
FRAMES_MAX = 257
FRAMES_STEP = 8

_ASPECT_RE = re.compile(r"^[1-9][0-9]*:[1-9][0-9]*$")
CSV_FIELDS = (
    "order",
    "shot_key",
    "title",
    "category",
    "reference_filename_from_plan",
    "start_frame_filename",
    "identity_reference_filename",
    "prompt_original",
    "status",
    "output_name_prefix",
)


class ManifestError(ValueError):
    """Манифест не соответствует контракту импорта."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = list(errors)


def canonical_sha256(data: dict[str, Any]) -> str:
    """Стабильный отпечаток манифеста: не зависит от форматирования файла."""

    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def snap_frame_count(seconds: float, fps: int) -> int:
    """Кадры для LTX2MLX: 8k+1 в диапазоне 9..257."""

    if fps <= 0:
        raise ValueError("fps must be positive")
    raw = int(round(seconds * fps))
    snapped = int(round((raw - 1) / FRAMES_STEP)) * FRAMES_STEP + 1
    return max(FRAMES_MIN, min(FRAMES_MAX, snapped))


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class ManifestShot:
    order: int
    shot_key: str
    title: str
    category: str
    reference_filename: str | None
    start_frame_filename: str | None
    identity_reference_filename: str | None
    prompt_original: str
    duration_seconds: tuple[int, int]
    status: str
    approved: bool
    seed: int | None
    workflow_version: str | None
    output_name_prefix: str

    def frames(self, fps: int) -> int:
        """Длительность берётся по верхней границе диапазона: подрезка — в монтаже."""

        return snap_frame_count(self.duration_seconds[1], fps)

    def reference_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for value in (
            self.reference_filename,
            self.start_frame_filename,
            self.identity_reference_filename,
        ):
            if value is not None and value not in names:
                names.append(value)
        return tuple(names)

    def requires_start_frame(self) -> bool:
        """Сюжетные шоты приходят без стартового кадра — его утверждает человек."""

        return self.start_frame_filename is None


@dataclass(frozen=True)
class SeriesManifest:
    schema_version: str
    project_title: str
    episode_title: str
    source_document: str | None
    source_version: str | None
    audio_master_duration_seconds: int | None
    target_aspect_ratio: str
    target_fps: int | None
    generator: str | None
    concurrency: int
    execution_policy: dict[str, Any]
    workflow_template: dict[str, Any]
    shots: tuple[ManifestShot, ...]
    sha256: str

    @property
    def reference_names(self) -> tuple[str, ...]:
        names: list[str] = []
        for shot in self.shots:
            for name in shot.reference_names():
                if name not in names:
                    names.append(name)
        return tuple(names)

    @property
    def blocked_shots(self) -> tuple[ManifestShot, ...]:
        return tuple(shot for shot in self.shots if shot.requires_start_frame())

    def effective_fps(self, fallback: int = DEFAULT_TIMELINE_FPS) -> int:
        return self.target_fps or fallback


def _parse_shot(index: int, raw: Any, errors: list[str]) -> ManifestShot | None:
    where = f"shots[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where}: ожидался объект")
        return None

    order = raw.get("order")
    if not isinstance(order, int) or isinstance(order, bool) or order < 1:
        errors.append(f"{where}: order должен быть целым >= 1")
        order = 0

    shot_key = _clean(raw.get("shot_key")) or ""
    if not shot_key:
        errors.append(f"{where}: пустой shot_key")

    title = _clean(raw.get("title")) or ""
    if not title:
        errors.append(f"{where}: пустой title")

    category = _clean(raw.get("category")) or ""
    if not category:
        errors.append(f"{where}: пустая category")

    prompt = raw.get("prompt_original")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append(f"{where}: пустой prompt_original")
        prompt = ""

    duration = raw.get("target_duration_seconds")
    if (
        not isinstance(duration, list)
        or len(duration) != 2
        or not all(isinstance(item, int) and not isinstance(item, bool) for item in duration)
        or duration[0] < 1
        or duration[0] > duration[1]
    ):
        errors.append(
            f"{where}: target_duration_seconds должен быть [низ, верх] целыми >= 1"
        )
        duration = [0, 0]

    seed = raw.get("seed")
    if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
        errors.append(f"{where}: seed должен быть целым или null")
        seed = None

    prefix = _clean(raw.get("output_name_prefix")) or ""
    if not prefix:
        errors.append(f"{where}: пустой output_name_prefix")

    return ManifestShot(
        order=order,
        shot_key=shot_key,
        title=title,
        category=category,
        reference_filename=_clean(raw.get("reference_filename_from_plan")),
        start_frame_filename=_clean(raw.get("start_frame_filename")),
        identity_reference_filename=_clean(raw.get("identity_reference_filename")),
        prompt_original=prompt,
        duration_seconds=(duration[0], duration[1]),
        status=_clean(raw.get("status")) or "unknown",
        approved=bool(raw.get("approved")),
        seed=seed,
        workflow_version=_clean(raw.get("workflow_version")),
        output_name_prefix=prefix,
    )


def parse_manifest(data: Any, *, sha256: str | None = None) -> SeriesManifest:
    """Разбирает и валидирует манифест; ошибки собираются все сразу."""

    if not isinstance(data, dict):
        raise ManifestError(["манифест должен быть JSON-объектом"])

    errors: list[str] = []
    schema_version = _clean(data.get("schema_version")) or ""
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            f"schema_version={schema_version!r} не поддерживается: "
            f"ожидалось {', '.join(SUPPORTED_SCHEMA_VERSIONS)}"
        )

    project_title = _clean(data.get("project")) or ""
    if not project_title:
        errors.append("пустой project")

    episode_title = _clean(data.get("episode")) or ""
    if not episode_title:
        errors.append("пустой episode")

    aspect = _clean(data.get("target_aspect_ratio")) or ""
    if not _ASPECT_RE.match(aspect):
        errors.append(f"target_aspect_ratio={aspect!r} не похож на '<w>:<h>'")

    target_fps = data.get("target_fps")
    if target_fps is not None and (
        not isinstance(target_fps, int) or isinstance(target_fps, bool) or target_fps <= 0
    ):
        errors.append("target_fps должен быть положительным целым или null")
        target_fps = None

    audio_duration = data.get("audio_master_duration_seconds")
    if audio_duration is not None and (
        not isinstance(audio_duration, int) or isinstance(audio_duration, bool)
    ):
        errors.append("audio_master_duration_seconds должен быть целым или null")
        audio_duration = None

    concurrency = data.get("concurrency", 1)
    if not isinstance(concurrency, int) or isinstance(concurrency, bool) or concurrency < 1:
        errors.append("concurrency должен быть целым >= 1")
        concurrency = 1

    raw_shots = data.get("shots")
    if not isinstance(raw_shots, list) or not raw_shots:
        errors.append("shots должен быть непустым массивом")
        raw_shots = []

    shots: list[ManifestShot] = []
    for index, raw in enumerate(raw_shots):
        shot = _parse_shot(index, raw, errors)
        if shot is not None:
            shots.append(shot)

    seen_order: dict[int, str] = {}
    seen_key: dict[str, int] = {}
    seen_prefix: dict[str, int] = {}
    for shot in shots:
        if shot.order in seen_order:
            errors.append(
                f"order={shot.order} повторяется: {seen_order[shot.order]} и {shot.shot_key}"
            )
        else:
            seen_order[shot.order] = shot.shot_key
        if shot.shot_key in seen_key:
            errors.append(f"shot_key={shot.shot_key} повторяется")
        else:
            seen_key[shot.shot_key] = shot.order
        if shot.output_name_prefix in seen_prefix:
            errors.append(f"output_name_prefix={shot.output_name_prefix} повторяется")
        else:
            seen_prefix[shot.output_name_prefix] = shot.order

    orders = sorted(seen_order)
    if orders and orders != list(range(1, len(orders) + 1)):
        errors.append(
            f"порядок shots не непрерывный от 1: {orders[:5]}…{orders[-3:]}"
            if len(orders) > 8
            else f"порядок shots не непрерывный от 1: {orders}"
        )

    workflow_template = data.get("workflow_template")
    if workflow_template is not None and not isinstance(workflow_template, dict):
        errors.append("workflow_template должен быть объектом")
        workflow_template = {}

    execution_policy = data.get("execution_policy")
    if execution_policy is not None and not isinstance(execution_policy, dict):
        errors.append("execution_policy должен быть объектом")
        execution_policy = {}

    if errors:
        raise ManifestError(errors)

    return SeriesManifest(
        schema_version=schema_version,
        project_title=project_title,
        episode_title=episode_title,
        source_document=_clean(data.get("source_document")),
        source_version=_clean(data.get("source_version")),
        audio_master_duration_seconds=audio_duration,
        target_aspect_ratio=aspect,
        target_fps=target_fps,
        generator=_clean(data.get("generator")),
        concurrency=concurrency,
        execution_policy=dict(execution_policy or {}),
        workflow_template=dict(workflow_template or {}),
        shots=tuple(sorted(shots, key=lambda item: item.order)),
        sha256=sha256 or canonical_sha256(data),
    )


def load_manifest(path: Path) -> SeriesManifest:
    raw = Path(path).read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise ManifestError([f"{path}: некорректный JSON: {error}"]) from error
    return parse_manifest(data, sha256=hashlib.sha256(raw).hexdigest())


def parse_queue_csv(text: str) -> list[dict[str, str]]:
    """Читает CSV-очередь; пустые значения остаются пустыми строками."""

    # BOM перед заголовком иначе превращает "order" в "\ufefforder".
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    missing = [field for field in CSV_FIELDS if field not in (reader.fieldnames or ())]
    if missing:
        raise ManifestError([f"в CSV нет колонок: {', '.join(missing)}"])
    return [dict(row) for row in reader]


def load_queue_csv(path: Path) -> list[dict[str, str]]:
    return parse_queue_csv(Path(path).read_text(encoding="utf-8-sig"))


def cross_check_queue(
    manifest: SeriesManifest, rows: list[dict[str, str]]
) -> list[str]:
    """Сверка CSV с манифестом. Расхождения — ошибки, а не предупреждения."""

    errors: list[str] = []
    if len(rows) != len(manifest.shots):
        errors.append(
            f"CSV содержит {len(rows)} строк, манифест — {len(manifest.shots)} шотов"
        )

    by_key = {shot.shot_key: shot for shot in manifest.shots}
    for index, row in enumerate(rows):
        key = (row.get("shot_key") or "").strip()
        shot = by_key.get(key)
        if shot is None:
            errors.append(f"CSV строка {index + 2}: неизвестный shot_key={key!r}")
            continue
        expected = {
            "order": str(shot.order),
            "title": shot.title,
            "category": shot.category,
            "reference_filename_from_plan": shot.reference_filename or "",
            "start_frame_filename": shot.start_frame_filename or "",
            "identity_reference_filename": shot.identity_reference_filename or "",
            "prompt_original": shot.prompt_original,
            "status": shot.status,
            "output_name_prefix": shot.output_name_prefix,
        }
        for field, want in expected.items():
            got = (row.get(field) or "").strip()
            if got != want.strip():
                errors.append(
                    f"CSV {key}: поле {field} расходится с манифестом "
                    f"(CSV={got[:60]!r}, манифест={want[:60]!r})"
                )
    return errors
