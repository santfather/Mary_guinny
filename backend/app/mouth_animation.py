"""Движок приблизительной анимации рта `mouth_animation_mvp` (WP-VOICE-02, §4.18).

Это **не** phoneme-accurate lip sync: раскрытие рта считается только по RMS-
огибающей записи. Кадры детерминированы: одинаковые источник, калибровка и
огибающая дают одинаковую кривую и одинаковые кадры. В тишине раскрытие ровно 0,
случайных движений нет. Исходное изображение и аудио только читаются.
"""

from __future__ import annotations

import io
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, UnidentifiedImageError

from app.shot_audio import ENVELOPE_RATE_HZ, SILENCE_RELATIVE_GATE
from app.video_probe import VideoProbeError, probe_mp4

MODE = "mouth_animation_mvp"
WORKFLOW_VERSION = "mouth_animation_mvp_v2"
ENGINE = "pillow_mouth_v2"
RESULT_KIND = "talking_preview"
RESULT_MIME = "video/mp4"
DEFAULT_FPS = 24
MAX_OUTPUT_SIDE = 1080
# Ниже этого раскрытия (в долях от max_open) рот считается закрытым.
OPEN_DEADBAND = 0.03
# Непрерывная тишина дольше этого времени закрывает рот принудительно (WP-VOICE-04).
SILENCE_CLOSE_S = 0.08
CAVITY_COLOR = (26, 12, 16)
LIMITATION = (
    "Приблизительная анимация рта по громкости, не phoneme-accurate lip sync."
)
FFMPEG_TIMEOUT_S = 900.0


class MouthAnimationError(ValueError):
    """Ошибка генерации с машинным кодом для API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class MouthRegion:
    """Нормализованная область рта на кадре (0…1) и параметры чувствительности."""

    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0
    max_open: float = 0.8
    sensitivity: float = 1.0
    smoothing: float = 0.5

    def validate(self) -> None:
        if self.x < 0 or self.y < 0:
            raise MouthAnimationError("mouth_region_out_of_bounds", "x/y должны быть >= 0")
        if self.width <= 0 or self.height <= 0:
            raise MouthAnimationError(
                "mouth_region_out_of_bounds", "width/height должны быть > 0"
            )
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise MouthAnimationError(
                "mouth_region_out_of_bounds", "область рта выходит за кадр"
            )
        if not -180 <= self.rotation <= 180:
            raise MouthAnimationError("mouth_region_out_of_bounds", "rotation вне -180…180")
        if not 0 < self.max_open <= 1:
            raise MouthAnimationError("mouth_region_out_of_bounds", "max_open вне 0…1")
        if not 0 < self.sensitivity <= 5:
            raise MouthAnimationError("mouth_region_out_of_bounds", "sensitivity вне 0…5")
        if not 0 <= self.smoothing < 1:
            raise MouthAnimationError("mouth_region_out_of_bounds", "smoothing вне 0…1")

    def as_metadata(self) -> dict[str, float]:
        return {
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "width": round(self.width, 6),
            "height": round(self.height, 6),
            "rotation": round(self.rotation, 3),
            "max_open": round(self.max_open, 4),
            "sensitivity": round(self.sensitivity, 4),
            "smoothing": round(self.smoothing, 4),
        }


@dataclass(frozen=True)
class PreviewInfo:
    width: int
    height: int
    fps: int
    frames: int
    duration_s: float


def open_threshold(envelope: list[float]) -> float:
    """Порог открытия рта: доля от пика RMS (тишина ниже порога)."""

    peak = max(envelope, default=0.0)
    return max(peak * SILENCE_RELATIVE_GATE, 1e-6)


def openness_curve(
    envelope: list[float],
    *,
    fps: int,
    duration_s: float,
    sensitivity: float = 1.0,
    smoothing: float = 0.5,
    max_open: float = 0.8,
) -> list[float]:
    """Раскрытие рта на кадр (0…max_open) из RMS-огибающей 50 Гц.

    Шаги: окно кадра → порог тишины → масштаб чувствительности → однополюсный
    attack/release с разными коэффициентами → deadband. В тишине ровно 0.
    """

    frames = max(1, round(duration_s * fps))
    if not envelope:
        return [0.0] * frames

    gate = open_threshold(envelope)
    span = max(max(envelope) - gate, 1e-6)
    per_frame = ENVELOPE_RATE_HZ / fps

    levels: list[float] = []
    for index in range(frames):
        start = min(len(envelope) - 1, int(index * per_frame))
        end = max(start + 1, int(round((index + 1) * per_frame)))
        window = envelope[start:end] or envelope[-1:]
        raw = max(window)
        if raw <= gate:
            levels.append(0.0)
            continue
        level = min(1.0, (raw - gate) / span) * sensitivity
        levels.append(min(1.0, max(0.0, level)))

    base = max(0.05, 1.0 - 0.9 * smoothing)
    attack = base
    release = max(0.08, base * (1.0 - 0.35 * smoothing))
    close_after = max(1, math.ceil(SILENCE_CLOSE_S * fps))

    curve: list[float] = []
    value = 0.0
    silent_frames = 0
    for level in levels:
        silent_frames = silent_frames + 1 if level <= 0.0 else 0
        if silent_frames >= close_after:
            # Короткая пауза закрывает рот полностью, а не «дотягивает» release.
            value = 0.0
        else:
            coefficient = attack if level > value else release
            value += (level - value) * coefficient
            if value < OPEN_DEADBAND:
                value = 0.0
        curve.append(round(value * max_open, 4))
    return curve


def decode_source_image(data: bytes, *, max_side: int = MAX_OUTPUT_SIDE) -> Image.Image:
    """Декодирует approved-изображение в RGB и ограничивает длинную сторону."""

    if not data:
        raise MouthAnimationError("source_image_invalid", "пустое изображение")
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = opened.convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise MouthAnimationError(
            "source_image_invalid", "источник не декодируется как изображение"
        ) from error

    width, height = image.size
    longest = max(width, height)
    if longest > max_side:
        ratio = max_side / longest
        width = max(2, round(width * ratio))
        height = max(2, round(height * ratio))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    # yuv420p требует чётных сторон.
    width -= width % 2
    height -= height % 2
    if (width, height) != image.size:
        image = image.crop((0, 0, width, height))
    return image


def _mouth_mask(size: tuple[int, int], norm: float, rw: float, rh: float) -> Image.Image:
    """Маска рта: верх — ровная линия губ, раскрытие идёт вниз, край мягкий."""

    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    center_x = size[0] / 2
    mouth_line = size[1] / 2
    open_width = max(2.0, rw * 0.9)
    open_height = max(1.0, rh * (0.10 + 0.55 * norm))
    box = (
        center_x - open_width / 2,
        mouth_line,
        center_x + open_width / 2,
        mouth_line + open_height,
    )
    draw.rounded_rectangle(
        box, radius=min(open_height * 0.4, open_width * 0.4), fill=255
    )
    feather = max(1.0, open_height * 0.12)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=feather))
    alpha = min(1.0, 0.45 + 0.55 * norm)
    return mask.point(lambda value: round(value * alpha))


def render_frame(base: Image.Image, region: MouthRegion, openness: float) -> Image.Image:
    """Один кадр: закрытый рот возвращает точную копию источника."""

    if openness <= 0:
        return base.copy()

    width, height = base.size
    center_x = (region.x + region.width / 2) * width
    center_y = (region.y + region.height / 2) * height
    region_width = max(4, round(region.width * width))
    region_height = max(4, round(region.height * height))
    # Маска раскрывается вниз от линии рта; патч вмещает 2·rh плюс запас на feather.
    side = 2 * max(region_width, region_height) + 16
    left = round(center_x - side / 2)
    top = round(center_y - side / 2)

    patch = base.crop((left, top, left + side, top + side))
    if region.rotation:
        patch = patch.rotate(-region.rotation, resample=Image.Resampling.BICUBIC)

    norm = min(1.0, max(0.0, openness / region.max_open))
    dark = Image.blend(patch, Image.new("RGB", patch.size, CAVITY_COLOR), 0.85)
    mask = _mouth_mask(patch.size, norm, region_width, region_height)
    if region.rotation:
        dark = dark.rotate(region.rotation, resample=Image.Resampling.BICUBIC)
        mask = mask.rotate(region.rotation, resample=Image.Resampling.BICUBIC)

    frame = base.copy()
    frame.paste(dark, (left, top), mask)
    return frame


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise MouthAnimationError("ffmpeg_missing", "ffmpeg не найден в PATH")
    return path


def render_talking_preview(
    source_image: bytes,
    audio_path: Path,
    envelope: list[float],
    duration_s: float,
    region: MouthRegion,
    *,
    output_path: Path,
    fps: int = DEFAULT_FPS,
    max_side: int = MAX_OUTPUT_SIDE,
) -> PreviewInfo:
    """Рендерит Talking Preview: h264 + исходное аудио (aac) в одном MP4."""

    region.validate()
    base = decode_source_image(source_image, max_side=max_side)
    curve = openness_curve(
        envelope,
        fps=fps,
        duration_s=duration_s,
        sensitivity=region.sensitivity,
        smoothing=region.smoothing,
        max_open=region.max_open,
    )

    command = [
        _ffmpeg(),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{base.width}x{base.height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-i",
        str(audio_path),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-af",
        "apad",
        "-t",
        f"{len(curve) / fps:.6f}",
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
        "-flags:v",
        "+bitexact",
        "-flags:a",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None and process.stderr is not None
    try:
        for openness in curve:
            frame = render_frame(base, region, openness)
            process.stdin.write(frame.tobytes())
            if process.poll() is not None:
                raise BrokenPipeError("ffmpeg завершился до конца кадров")
        process.stdin.close()
        stderr = process.stderr.read()
        code = process.wait(timeout=FFMPEG_TIMEOUT_S)
    except (BrokenPipeError, OSError) as error:
        process.kill()
        stderr = process.stderr.read()
        raise MouthAnimationError(
            "ffmpeg_failed", stderr.decode("utf-8", errors="replace") or str(error)
        ) from error
    finally:
        if process.poll() is None:
            process.kill()

    if code != 0:
        raise MouthAnimationError(
            "ffmpeg_failed", stderr.decode("utf-8", errors="replace") or f"exit {code}"
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise MouthAnimationError("ffmpeg_failed", "ffmpeg не создал MP4")

    try:
        info = probe_mp4(output_path.read_bytes())
    except VideoProbeError as error:
        raise MouthAnimationError("invalid_preview", f"MP4 не прошёл проверку: {error}") from error
    if not info.has_audio:
        raise MouthAnimationError("invalid_preview", "в результате нет аудиодорожки")

    return PreviewInfo(
        width=base.width,
        height=base.height,
        fps=fps,
        # Фактически закодированные кадры, а не длина поданной кривой.
        frames=max(1, round(info.duration_s * fps)),
        duration_s=round(info.duration_s, 3),
    )


def preview_parameters(
    *,
    region: MouthRegion,
    info: PreviewInfo,
    audio_asset_id: str,
    audio_sha256: str,
    source: dict[str, Any],
    calibration_id: str | None,
    envelope_summary: dict[str, Any],
) -> dict[str, Any]:
    """Провенанс попытки: чем и как сделан Talking Preview."""

    return {
        "mode": MODE,
        "engine": ENGINE,
        "limitation": LIMITATION,
        "fps": info.fps,
        "frames": info.frames,
        "width": info.width,
        "height": info.height,
        "duration_s": info.duration_s,
        "audio_asset_id": audio_asset_id,
        "audio_sha256": audio_sha256,
        "calibration_id": calibration_id,
        "region": region.as_metadata(),
        "source": source,
        "envelope_rate_hz": ENVELOPE_RATE_HZ,
        "gate": envelope_summary.get("gate"),
        "peak_rms": envelope_summary.get("peak_rms"),
        "speech_ratio": envelope_summary.get("speech_ratio"),
        "speech_segments": envelope_summary.get("speech_segments"),
        "silence_segments": envelope_summary.get("silence_segments"),
    }
