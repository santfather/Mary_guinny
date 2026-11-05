"""Набор viseme-кадров и проверка совместимости (WP-VOICE-06).

Набор — пять обычных `reference_assets` с ролью `viseme_<state>`, привязанных к
шоту. Миграций не требуется. Здесь только чистые функции над пикселями: импорт и
БД живут в `app/api/viseme_set.py`.

Проверка статистическая и детерминированная (PIL, без numpy): разрешение, сдвиг
головы, изменения вне области морды, совпадение `closed` с источником, наличие
артикуляции и риск мерцания между вариантами.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageStat, UnidentifiedImageError

from app.mouth_animation import MouthRegion

VISEME_STATES = (
    "closed",
    "small_open",
    "medium_open",
    "wide_open",
    "rounded",
)
VISEME_LABELS = {
    "closed": "closed",
    "small_open": "small_open",
    "medium_open": "medium_open",
    "wide_open": "wide_open",
    "rounded": "rounded",
}
ROLE_PREFIX = "viseme_"

# Порог яркости, ниже которого различие пикселей считается шумом сжатия.
PIXEL_DELTA = 12
# Максимальный оцениваемый сдвиг головы между вариантами.
MAX_SHIFT_PX = 8
# Запас вокруг области морды: правки края губ не считаются «вне морды».
MARGIN_RATIO = 0.04
# Допуски по умолчанию.
OUTSIDE_MAX_RATIO = 0.01
CLOSED_MAX_INSIDE_RATIO = 0.01
MIN_ARTICULATION_RATIO = 0.005
# Ширина уменьшенной копии для поиска сдвига: дешевле без потери точности.
SHIFT_SEARCH_WIDTH = 320
# Минимальное улучшение (средняя разница 0…255), чтобы признать сдвиг реальным:
# на однородном фоне все сдвиги дают одинаковый ноль, и побеждать должен (0, 0).
SHIFT_MIN_GAIN = 0.5


class VisemeError(ValueError):
    """Ошибка с машинным кодом для API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def role_for(state: str) -> str:
    return f"{ROLE_PREFIX}{state}"


def state_from_role(role: str | None) -> str | None:
    if role is None or not role.startswith(ROLE_PREFIX):
        return None
    state = role[len(ROLE_PREFIX) :]
    return state if state in VISEME_STATES else None


@dataclass(frozen=True)
class VariantInfo:
    """Метаданные одного варианта набора (для API и провенанса)."""

    state: str
    reference_asset_id: str
    status: str
    width: int | None
    height: int | None
    sha256: str
    content_url: str


@dataclass
class CompatibilityReport:
    ready: bool
    missing: list[str] = field(default_factory=list)
    blockers: list[dict[str, str]] = field(default_factory=list)
    variants: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "missing": list(self.missing),
            "blockers": list(self.blockers),
            "variants": list(self.variants),
            "metrics": dict(self.metrics),
        }


def decode_image(data: bytes, *, code: str = "viseme_image_invalid") -> Image.Image:
    if not data:
        raise VisemeError(code, "пустой файл изображения")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            return opened.convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise VisemeError(code, "файл не декодируется как изображение") from error


def _region_box(
    region: MouthRegion, size: tuple[int, int], margin_ratio: float = MARGIN_RATIO
) -> tuple[int, int, int, int]:
    width, height = size
    margin = max(2, round(min(width, height) * margin_ratio))
    left = max(0, round(region.x * width) - margin)
    top = max(0, round(region.y * height) - margin)
    right = min(width, round((region.x + region.width) * width) + margin)
    bottom = min(height, round((region.y + region.height) * height) + margin)
    return left, top, max(left + 1, right), max(top + 1, bottom)


def _inside_mask(size: tuple[int, int], box: tuple[int, int, int, int]) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    return mask


def _invert(mask: Image.Image) -> Image.Image:
    return mask.point(lambda value: 255 - value)


def _align_crop(
    source: Image.Image, variant: Image.Image, dx: int, dy: int
) -> tuple[Image.Image, Image.Image, tuple[int, int]]:
    """Сдвигает вариант на (dx, dy) и обрезает оба до общей области."""

    width, height = source.size
    left, top = max(0, dx), max(0, dy)
    right, bottom = width + min(0, dx), height + min(0, dy)
    source_crop = source.crop((left, top, right, bottom))
    variant_crop = variant.crop((left - dx, top - dy, right - dx, bottom - dy))
    return source_crop, variant_crop, (left, top)


def _mean_difference(
    source: Image.Image, variant: Image.Image, mask: Image.Image, dx: int, dy: int
) -> float:
    source_crop, variant_crop, _ = _align_crop(source, variant, dx, dy)
    mask_crop, _, _ = _align_crop(mask, mask, dx, dy)
    difference = ImageChops.difference(source_crop, variant_crop).convert("L")
    return float(ImageStat.Stat(difference, mask=mask_crop).mean[0])


def find_head_shift(
    source: Image.Image, variant: Image.Image, mask: Image.Image
) -> tuple[int, int]:
    """Ищет сдвиг варианта, при котором вне области морды различия минимальны."""

    width, height = source.size
    scale = min(1.0, SHIFT_SEARCH_WIDTH / max(1, width))
    small_size = (max(8, round(width * scale)), max(8, round(height * scale)))
    source_small = ImageOps.grayscale(source).resize(small_size, Image.Resampling.BILINEAR)
    variant_small = ImageOps.grayscale(variant).resize(small_size, Image.Resampling.BILINEAR)
    mask_small = mask.resize(small_size, Image.Resampling.NEAREST)

    limit = max(1, round(MAX_SHIFT_PX * small_size[0] / max(1, width)))
    # Ноль — базовая гипотеза: сдвиг принимается только при заметном улучшении.
    best = (0, 0)
    best_score = _mean_difference(source_small, variant_small, mask_small, 0, 0)
    baseline = best_score
    for dy in range(-limit, limit + 1):
        for dx in range(-limit, limit + 1):
            if dx == 0 and dy == 0:
                continue
            score = _mean_difference(source_small, variant_small, mask_small, dx, dy)
            if score < best_score - 1e-9:
                best_score = score
                best = (dx, dy)

    if best_score > baseline - SHIFT_MIN_GAIN:
        return (0, 0)
    if scale >= 1.0:
        return best
    return (
        round(best[0] / scale),
        round(best[1] / scale),
    )


def _changed_ratio(
    source: Image.Image, variant: Image.Image, mask: Image.Image, dx: int, dy: int
) -> tuple[float, int]:
    """Доля пикселей с заметным различием внутри маски и максимальная дельта."""

    source_crop, variant_crop, _ = _align_crop(source, variant, dx, dy)
    mask_crop, _, _ = _align_crop(mask, mask, dx, dy)
    difference = ImageChops.difference(source_crop, variant_crop).convert("L")
    changed = difference.point(lambda value: 255 if value > PIXEL_DELTA else 0)
    changed_pixels = ImageStat.Stat(changed, mask=mask_crop).sum[0] / 255.0
    total_pixels = ImageStat.Stat(mask_crop).sum[0] / 255.0
    ratio = changed_pixels / total_pixels if total_pixels > 0 else 0.0
    return ratio, int(ImageStat.Stat(difference).extrema[0][1])


def check_compatibility(
    source_image: bytes,
    variants: dict[str, bytes],
    region: MouthRegion,
    *,
    outside_max_ratio: float = OUTSIDE_MAX_RATIO,
    closed_max_inside_ratio: float = CLOSED_MAX_INSIDE_RATIO,
    min_articulation_ratio: float = MIN_ARTICULATION_RATIO,
    max_shift_px: int = MAX_SHIFT_PX,
    statuses: dict[str, str] | None = None,
    metadata: dict[str, VariantInfo] | None = None,
) -> CompatibilityReport:
    """Полный отчёт: готовность набора, блокеры и метрики по каждому варианту."""

    source = decode_image(source_image, code="source_image_invalid")
    report = CompatibilityReport(ready=False)
    report.missing = [state for state in VISEME_STATES if state not in variants]

    boxes: dict[str, tuple[int, int, int, int]] = {}
    decoded: dict[str, Image.Image] = {}
    for state, data in variants.items():
        if state not in VISEME_STATES:
            continue
        decoded[state] = decode_image(data)
        boxes[state] = _region_box(region, source.size)

    inside = _inside_mask(source.size, boxes.get("closed") or _region_box(region, source.size))
    outside = _invert(inside)

    outside_ratios: list[float] = []
    inside_ratios: dict[str, float] = {}

    for state in VISEME_STATES:
        if state not in decoded:
            continue
        variant = decoded[state]
        info = (metadata or {}).get(state)
        status = (statuses or {}).get(state, "draft")
        entry: dict[str, Any] = {
            "state": state,
            "status": status,
            "reference_asset_id": info.reference_asset_id if info else None,
            "content_url": info.content_url if info else None,
            "sha256": info.sha256 if info else None,
            "width": variant.width,
            "height": variant.height,
        }
        report.variants.append(entry)

        if variant.size != source.size:
            report.blockers.append(
                {
                    "code": "viseme_resolution_mismatch",
                    "state": state,
                    "message": (
                        f"{state}: {variant.width}×{variant.height} против "
                        f"{source.width}×{source.height} у источника"
                    ),
                }
            )
            continue

        # Маска считается по области морды этого варианта: набор может прислать
        # разные рамки, но отклонение всё равно должно быть внутри области.
        box = boxes[state]
        variant_inside = _inside_mask(source.size, box)
        variant_outside = _invert(variant_inside)

        dx, dy = find_head_shift(source, variant, variant_outside)
        entry["head_shift"] = {"dx": dx, "dy": dy}
        if abs(dx) > max_shift_px or abs(dy) > max_shift_px:
            report.blockers.append(
                {
                    "code": "viseme_head_shift",
                    "state": state,
                    "message": f"{state}: голова сдвинута на {dx}×{dy} px",
                }
            )

        outside_ratio, max_delta = _changed_ratio(
            source, variant, variant_outside, dx, dy
        )
        inside_ratio, _ = _changed_ratio(source, variant, variant_inside, dx, dy)
        entry["outside_ratio"] = round(outside_ratio, 6)
        entry["inside_ratio"] = round(inside_ratio, 6)
        entry["max_delta"] = max_delta
        outside_ratios.append(outside_ratio)
        inside_ratios[state] = inside_ratio

        if outside_ratio > outside_max_ratio:
            report.blockers.append(
                {
                    "code": "viseme_outside_mouth_changes",
                    "state": state,
                    "message": (
                        f"{state}: изменено {outside_ratio:.2%} пикселей вне морды "
                        f"(допуск {outside_max_ratio:.2%})"
                    ),
                }
            )

        if state == "closed":
            if inside_ratio > closed_max_inside_ratio:
                report.blockers.append(
                    {
                        "code": "viseme_closed_mismatch",
                        "state": state,
                        "message": (
                            f"closed: область рта отличается от источника на "
                            f"{inside_ratio:.2%}"
                        ),
                    }
                )
        elif inside_ratio < min_articulation_ratio:
            report.blockers.append(
                {
                    "code": "viseme_no_articulation",
                    "state": state,
                    "message": (
                        f"{state}: в области морды нет заметных изменений — "
                        "форма рта не отличается"
                    ),
                }
            )

        if status != "approved":
            report.blockers.append(
                {
                    "code": "viseme_set_not_approved",
                    "state": state,
                    "message": f"{state}: кадр ещё не утверждён человеком",
                }
            )

    if report.missing:
        report.blockers.append(
            {
                "code": "viseme_set_incomplete",
                "state": "",
                "message": "нет кадров: " + ", ".join(report.missing),
            }
        )

    # Мерцание: варианты не должны отличаться друг от друга вне области морды.
    named = [
        state
        for state in VISEME_STATES
        if state in decoded and decoded[state].size == source.size
    ]
    pair_ratios: list[float] = []
    for left in named:
        for right in named:
            if left >= right:
                continue
            ratio, _ = _changed_ratio(decoded[left], decoded[right], outside, 0, 0)
            pair_ratios.append(ratio)
    flicker = max(pair_ratios, default=0.0)
    if flicker > outside_max_ratio:
        report.blockers.append(
            {
                "code": "viseme_flicker_risk",
                "state": "",
                "message": (
                    f"варианты отличаются вне области морды на {flicker:.2%}: "
                    "при переключении будет мерцание"
                ),
            }
        )

    report.metrics = {
        "outside_ratio_max": round(max(outside_ratios, default=0.0), 6),
        "inside_ratio": {state: round(value, 6) for state, value in inside_ratios.items()},
        "flicker_ratio": round(flicker, 6),
        "thresholds": {
            "outside_max_ratio": outside_max_ratio,
            "closed_max_inside_ratio": closed_max_inside_ratio,
            "min_articulation_ratio": min_articulation_ratio,
            "max_shift_px": max_shift_px,
            "pixel_delta": PIXEL_DELTA,
            "margin_ratio": MARGIN_RATIO,
        },
    }
    report.ready = not report.blockers
    return report


def _font(size: int = 16) -> ImageFont.ImageFont:
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def comparison_sheet(
    source_image: bytes,
    variants: dict[str, bytes],
    region: MouthRegion,
    *,
    tile_height: int = 320,
    gap: int = 8,
) -> bytes:
    """PNG-лист: источник и пять вариантов в одном масштабе с рамкой морды."""

    source = decode_image(source_image, code="source_image_invalid")
    tiles: list[tuple[str, Image.Image | None]] = [("source", source)]
    for state in VISEME_STATES:
        data = variants.get(state)
        tiles.append((state, decode_image(data) if data is not None else None))

    scaled: list[tuple[str, Image.Image | None]] = []
    for label, image in tiles:
        if image is None:
            scaled.append((label, None))
            continue
        ratio = tile_height / image.height
        width = max(2, round(image.width * ratio))
        scaled.append((label, image.resize((width, tile_height), Image.Resampling.LANCZOS)))

    widths = [
        tile.width if tile is not None else round(tile_height * 0.75)
        for _, tile in scaled
    ]
    header = 28
    canvas_width = sum(widths) + gap * (len(scaled) + 1)
    canvas = Image.new("RGB", (canvas_width, tile_height + header + gap), (24, 24, 26))
    draw = ImageDraw.Draw(canvas)
    font = _font(15)

    x = gap
    for (label, tile), width in zip(scaled, widths):
        draw.text((x + 4, 6), VISEME_LABELS.get(label, label), fill=(230, 230, 230), font=font)
        if tile is None:
            draw.rectangle(
                (x, header, x + width, header + tile_height), outline=(120, 60, 60), width=2
            )
            draw.text((x + 8, header + 12), "missing", fill=(200, 120, 120), font=font)
        else:
            canvas.paste(tile, (x, header))
            scale = tile.width / max(1, source.width)
            left = x + round(region.x * source.width * scale)
            top = header + round(region.y * source.height * scale)
            right = x + round((region.x + region.width) * source.width * scale)
            bottom = header + round((region.y + region.height) * source.height * scale)
            draw.rectangle((left, top, right, bottom), outline=(255, 210, 40), width=2)
        x += width + gap

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()
