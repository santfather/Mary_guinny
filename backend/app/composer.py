"""Синхронный композитор PNG (WP-05, D2).

Собирает RGBA-холст из слоёв `shot_composition_layers`:
`x`/`y` — верхний левый угол трансформированного слоя, затем `scale`,
затем `rotation` по часовой стрелке, `opacity` умножает альфу.
Исходные blob'ы только читаются и никогда не перезаписываются.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.image_probe import ImageInfo, ImageProbeError, probe_image_bytes
from app.storage import BlobStore, StorageError


class CompositionError(ValueError):
    """Некорректные параметры композиции (422)."""

    status_code = 422


class CompositionLimitError(CompositionError):
    """Композиция превышает настроенные лимиты (413)."""

    status_code = 413


class CompositionSourceError(CompositionError):
    """Исходный слой отсутствует или недоступен в storage (409)."""

    status_code = 409


@dataclass(frozen=True)
class CompositionLayer:
    reference_asset_id: uuid.UUID
    kind: str
    storage_key: str
    z_index: int
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0


@dataclass(frozen=True)
class CompositionWarning:
    code: str
    message: str
    z_index: int
    reference_asset_id: uuid.UUID


@dataclass(frozen=True)
class CompositionResult:
    png: bytes
    width: int
    height: int
    warnings: tuple[CompositionWarning, ...]


def compose(
    layers: list[CompositionLayer],
    *,
    width: int,
    height: int,
    store: BlobStore,
    max_pixels: int,
    max_layers: int,
) -> CompositionResult:
    """Возвращает PNG с сохранённым альфа-каналом и список предупреждений."""

    _validate_canvas(width, height, max_pixels)
    if not layers:
        raise CompositionError("composition needs at least one layer")
    if len(layers) > max_layers:
        raise CompositionLimitError(f"composition exceeds {max_layers} layers")

    ordered = sorted(layers, key=lambda layer: layer.z_index)
    z_indexes = [layer.z_index for layer in ordered]
    if len(set(z_indexes)) != len(z_indexes):
        raise CompositionError("layer z_index values must be unique")

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    warnings: list[CompositionWarning] = []

    for layer in ordered:
        info, image = _load_layer(layer, store, max_pixels)
        if not info.has_alpha:
            warnings.append(_opaque_warning(layer))
        transformed = _transform(image, layer)
        _composite(canvas, transformed, round(layer.x), round(layer.y))

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return CompositionResult(
        png=buffer.getvalue(),
        width=width,
        height=height,
        warnings=tuple(warnings),
    )


def _validate_canvas(width: int, height: int, max_pixels: int) -> None:
    if width <= 0 or height <= 0:
        raise CompositionError("canvas width and height must be positive")
    if width * height > max_pixels:
        raise CompositionLimitError(f"canvas exceeds {max_pixels} pixels")


def _load_layer(
    layer: CompositionLayer, store: BlobStore, max_pixels: int
) -> tuple[ImageInfo, Image.Image]:
    _validate_layer(layer)
    try:
        data = store.read_bytes(layer.storage_key)
    except (StorageError, FileNotFoundError, OSError) as error:
        raise CompositionSourceError(
            f"layer z={layer.z_index} content is unavailable"
        ) from error

    try:
        info = probe_image_bytes(data)
    except ImageProbeError as error:
        raise CompositionError(f"layer z={layer.z_index} is not a supported image") from error
    if info.width * info.height > max_pixels:
        raise CompositionLimitError(f"layer z={layer.z_index} is too large")

    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = opened.convert("RGBA")
    except (UnidentifiedImageError, OSError) as error:
        raise CompositionError(f"layer z={layer.z_index} cannot be decoded") from error
    return info, image


def _validate_layer(layer: CompositionLayer) -> None:
    if layer.z_index < 0:
        raise CompositionError("layer z_index must be non-negative")
    if layer.scale <= 0:
        raise CompositionError("layer scale must be positive")
    if not 0 <= layer.opacity <= 1:
        raise CompositionError("layer opacity must be within 0..1")


def _transform(image: Image.Image, layer: CompositionLayer) -> Image.Image:
    if layer.scale != 1:
        size = (
            max(1, round(image.width * layer.scale)),
            max(1, round(image.height * layer.scale)),
        )
        image = image.resize(size, Image.Resampling.LANCZOS)
    if layer.rotation % 360 != 0:
        # Pillow вращает против часовой стрелки, поэтому знак инвертируется.
        image = image.rotate(
            -layer.rotation, resample=Image.Resampling.BICUBIC, expand=True
        )
    if layer.opacity < 1:
        alpha = image.getchannel("A").point(lambda value: round(value * layer.opacity))
        image.putalpha(alpha)
    return image


def _composite(
    canvas: Image.Image, layer: Image.Image, x: int, y: int
) -> None:
    left = max(0, x)
    top = max(0, y)
    right = min(canvas.width, x + layer.width)
    bottom = min(canvas.height, y + layer.height)
    if right <= left or bottom <= top:
        return
    cropped = layer.crop((left - x, top - y, right - x, bottom - y))
    canvas.alpha_composite(cropped, dest=(left, top))


def _opaque_warning(layer: CompositionLayer) -> CompositionWarning:
    if layer.kind == "character_reference":
        return CompositionWarning(
            code="opaque_character_reference",
            message=(
                "Референс персонажа полностью непрозрачен: фон перекроет нижние слои."
            ),
            z_index=layer.z_index,
            reference_asset_id=layer.reference_asset_id,
        )
    return CompositionWarning(
        code="layer_without_alpha",
        message="У слоя нет альфа-канала: он перекроет нижние слои прямоугольником.",
        z_index=layer.z_index,
        reference_asset_id=layer.reference_asset_id,
    )
