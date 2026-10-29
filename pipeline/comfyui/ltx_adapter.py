"""Адаптер LTX-2.3 MLX I2V: API-шаблон ComfyUI → payload конкретного шота.

Модуль намеренно чистый: никакой сети, БД и записи файлов. Он только связывает
подготовленный шаблон `comfyui-workflows/ltx23_mlx_q4_i2v.api.json` с данными
шота. Отправку в ComfyUI делает worker.

ID нод ищутся по `class_type`, а не хардкодятся: шаблон может измениться, и
адаптер должен падать с внятной ошибкой, а не отправлять мусор.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GENERATE_NODE = "LTX2MLXGenerate"
LOAD_IMAGE_NODE = "LoadImage"
MODEL_LOADER_NODE = "LTX2MLXModelLoader"

# Входы, без которых рендер шота бессмысленен.
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

# Ограничения LTX2MLXGenerate: размеры кратны 8, число кадров — 8k+1.
SIZE_LIMITS = {"width": (64, 3840), "height": (64, 2160)}
SIZE_STEP = 8
FRAMES_MIN, FRAMES_MAX, FRAMES_STEP = 9, 257, 8
FRAME_RATE_LIMITS = (1, 60)
DEFAULT_LONG_SIDE = 1920
DEFAULT_CFG_SCALE = 3.0
WORKFLOW_VERSION_PREFIX = "ltx23-mlx-q4-i2v"


class BindingError(ValueError):
    """Шаблон или параметры не подходят для запрошенного шота."""


@dataclass(frozen=True)
class ShotBinding:
    """Всё, что подставляется в шаблон для одного шота."""

    shot_key: str
    prompt: str
    image_name: str
    seed: int
    width: int
    height: int
    num_frames: int
    frame_rate: float
    cfg_scale: float
    output_prefix: str

    def as_parameters(self) -> dict[str, Any]:
        """Происхождение рендера для `render_attempts.parameters`."""

        return {
            "shot_key": self.shot_key,
            "image": self.image_name,
            "seed": self.seed,
            "width": self.width,
            "height": self.height,
            "num_frames": self.num_frames,
            "frame_rate": self.frame_rate,
            "cfg_scale": self.cfg_scale,
            "filename_prefix": self.output_prefix,
        }


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def workflow_version(template: dict[str, Any]) -> str:
    """Версия адаптации = префикс + хвост sha256 канонического шаблона."""

    return f"{WORKFLOW_VERSION_PREFIX}/{canonical_sha256(template)[:12]}"


def load_template(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def model_id(template: dict[str, Any]) -> str:
    """Идентификатор модели из `LTX2MLXModelLoader` — provenance рендера."""

    node_id = _single_node(template, MODEL_LOADER_NODE)
    value = template[node_id]["inputs"].get("model_dir")
    return str(value) if value else "unknown"


def snap_frames(seconds: float, fps: int) -> int:
    """Кадры для LTX2MLX: 8k+1 в диапазоне 9..257."""

    if seconds <= 0:
        raise BindingError(f"длительность должна быть положительной: {seconds}")
    if fps <= 0:
        raise BindingError(f"fps должен быть положительным: {fps}")
    raw = int(round(seconds * fps))
    snapped = int(round((raw - 1) / FRAMES_STEP)) * FRAMES_STEP + 1
    return max(FRAMES_MIN, min(FRAMES_MAX, snapped))


def resolve_size(aspect_ratio: str, long_side: int = DEFAULT_LONG_SIDE) -> tuple[int, int]:
    """Портрет 9:16 при длинной стороне 1920 → 1080×1920 (обе кратны 8)."""

    try:
        raw_width, raw_height = (int(part) for part in aspect_ratio.split(":", 1))
    except ValueError as error:
        raise BindingError(f"некорректное соотношение сторон: {aspect_ratio!r}") from error
    if raw_width <= 0 or raw_height <= 0:
        raise BindingError(f"некорректное соотношение сторон: {aspect_ratio!r}")
    if raw_width >= raw_height:
        width, height = long_side, round(long_side * raw_height / raw_width)
    else:
        width, height = round(long_side * raw_width / raw_height), long_side
    width = max(SIZE_STEP, width - width % SIZE_STEP)
    height = max(SIZE_STEP, height - height % SIZE_STEP)
    return width, height


def build_shot_binding(
    *,
    shot_key: str,
    prompt: str,
    image_name: str,
    seed: int,
    attempt_id: str,
    aspect_ratio: str,
    seconds: float,
    fps: int,
    cfg_scale: float = DEFAULT_CFG_SCALE,
    long_side: int = DEFAULT_LONG_SIDE,
) -> ShotBinding:
    """Собирает параметры шота; всё спорное — ошибка, а не молчаливая подстановка."""

    if not shot_key.strip():
        raise BindingError("не задан shot_key")
    if not prompt.strip():
        raise BindingError("пустой prompt шота")
    if not image_name.strip():
        raise BindingError("не задан утверждённый стартовый кадр")
    if seed < 0:
        raise BindingError(f"seed должен быть неотрицательным: {seed}")
    if not attempt_id.strip():
        raise BindingError("не задан attempt_id для уникального output prefix")
    if not FRAME_RATE_LIMITS[0] <= fps <= FRAME_RATE_LIMITS[1]:
        raise BindingError(f"fps={fps} вне {FRAME_RATE_LIMITS[0]}..{FRAME_RATE_LIMITS[1]}")

    width, height = resolve_size(aspect_ratio, long_side)
    _require_size("width", width)
    _require_size("height", height)

    return ShotBinding(
        shot_key=shot_key,
        prompt=prompt,
        image_name=image_name,
        seed=seed,
        width=width,
        height=height,
        num_frames=snap_frames(seconds, fps),
        frame_rate=float(fps),
        cfg_scale=cfg_scale,
        output_prefix=_output_prefix(shot_key, attempt_id),
    )


def bind_workflow(template: dict[str, Any], binding: ShotBinding) -> dict[str, Any]:
    """Копия шаблона с подставленными значениями шота. Шаблон не мутируется."""

    workflow = deepcopy(template)
    generate_id = _single_node(workflow, GENERATE_NODE)
    image_id = _single_node(workflow, LOAD_IMAGE_NODE)
    _single_node(workflow, MODEL_LOADER_NODE)

    generate = workflow[generate_id]["inputs"]
    missing = [name for name in REQUIRED_GENERATE_INPUTS if name not in generate]
    if missing:
        raise BindingError(f"{GENERATE_NODE}: нет входов {', '.join(missing)}")

    link = generate["image"]
    if not (
        isinstance(link, list)
        and len(link) == 2
        and str(link[0]) == image_id
        and link[1] == 0
    ):
        raise BindingError(f"{GENERATE_NODE}.image не связан с {LOAD_IMAGE_NODE}")

    workflow[image_id]["inputs"]["image"] = binding.image_name
    generate["prompt"] = binding.prompt
    generate["seed"] = binding.seed
    generate["width"] = binding.width
    generate["height"] = binding.height
    generate["num_frames"] = binding.num_frames
    generate["frame_rate"] = binding.frame_rate
    generate["cfg_scale"] = binding.cfg_scale
    generate["filename_prefix"] = binding.output_prefix
    return workflow


def describe(template: dict[str, Any], binding: ShotBinding) -> dict[str, Any]:
    """Краткая сводка для отчётов: что и куда подставлено.

    `render_verified=False` до фактического рендера: адаптер не подтверждает,
    что 9:16 и 7–8 секунд поддерживаются этим workflow.
    """

    workflow = bind_workflow(template, binding)
    generate_id = _single_node(workflow, GENERATE_NODE)
    return {
        "workflow_version": workflow_version(template),
        "render_verified": False,
        "nodes": {
            GENERATE_NODE: generate_id,
            LOAD_IMAGE_NODE: _single_node(workflow, LOAD_IMAGE_NODE),
            MODEL_LOADER_NODE: _single_node(workflow, MODEL_LOADER_NODE),
        },
        "inputs": workflow[generate_id]["inputs"],
    }


def _single_node(workflow: dict[str, Any], class_type: str) -> str:
    node_ids = [
        node_id
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == class_type
    ]
    if not node_ids:
        raise BindingError(f"в шаблоне нет ноды {class_type}")
    if len(node_ids) > 1:
        raise BindingError(f"в шаблоне несколько нод {class_type}: {node_ids}")
    return node_ids[0]


def _require_size(name: str, value: int) -> None:
    low, high = SIZE_LIMITS[name]
    if not low <= value <= high or value % SIZE_STEP:
        raise BindingError(
            f"{name}={value}: нужна кратность {SIZE_STEP} в диапазоне {low}..{high}"
        )


def _output_prefix(shot_key: str, attempt_id: str) -> str:
    safe_key = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in shot_key
    )
    safe_attempt = "".join(
        char if char.isalnum() or char in "-_" else "_" for char in attempt_id
    )
    return f"nlb/{safe_key}/{safe_attempt}"
