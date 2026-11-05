"""Движок `viseme_frame_blend_v1`: кадры из готовых изображений морды (WP-VOICE-06).

Вместо нарисованной маски рта кадр собирается из пяти согласованных изображений
(closed/small_open/medium_open/wide_open/rounded). Меняется только патч области
морды; остальные пиксели берутся из approved-источника без изменений.

Переходы плавные: веса виземов сглаживаются с постоянной времени `blend_ms`,
а слишком короткие виземы (< `min_hold_ms`) отбрасываются — артикуляция не
дрожит. В паузах записи рот принудительно закрыт.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from app.mouth_animation import (
    FFMPEG_TIMEOUT_S,
    MouthAnimationError,
    MouthRegion,
    PreviewInfo,
    decode_source_image,
)
from app.viseme_assets import VISEME_STATES, VisemeError, decode_image

MODE = "viseme_frame_blend_v1"
WORKFLOW_VERSION = "viseme_frame_blend_v1"
ENGINE = "viseme_frame_blend_v1"
RESULT_KIND = "talking_preview"
RESULT_MIME = "video/mp4"
DEFAULT_FPS = 24
MAX_OUTPUT_SIDE = 1080
DEFAULT_BLEND_MS = 60.0
DEFAULT_MIN_HOLD_MS = 60.0
# Запас вокруг области морды при переносе патча.
PATCH_MARGIN_RATIO = 0.04
LIMITATION = (
    "Анимация по пяти готовым кадрам морды (viseme frames), не генеративный "
    "pixel-level lip sync: артикуляция ограничена набором форм рта."
)


@dataclass(frozen=True)
class VisemeSpan:
    start: float
    end: float
    viseme: str

    def as_metadata(self) -> dict[str, Any]:
        return {
            "start": round(self.start, 4),
            "end": round(self.end, 4),
            "viseme": self.viseme,
        }


@dataclass(frozen=True)
class FrameMix:
    primary: str
    secondary: str | None
    mix: float


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_timings(raw: Any) -> list[VisemeSpan]:
    """Разбирает viseme timing JSON и приводит к списку `VisemeSpan`."""

    if isinstance(raw, dict):
        raw = raw.get("visemes", raw.get("cues"))
    if not isinstance(raw, list) or not raw:
        raise VisemeError(
            "viseme_timing_invalid", "нужен непустой список виземов: {start, end, viseme}"
        )

    spans: list[VisemeSpan] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise VisemeError("viseme_timing_invalid", f"элемент {index} не объект")
        start = _number(item.get("start", item.get("start_s")))
        end = _number(item.get("end", item.get("end_s")))
        viseme = item.get("viseme", item.get("state", item.get("value")))
        if start is None or end is None:
            raise VisemeError(
                "viseme_timing_invalid", f"элемент {index}: нужны числовые start и end"
            )
        if not isinstance(viseme, str) or viseme not in VISEME_STATES:
            raise VisemeError(
                "viseme_timing_invalid",
                f"элемент {index}: viseme должен быть одним из {', '.join(VISEME_STATES)}",
            )
        if start < 0 or end <= start:
            raise VisemeError(
                "viseme_timing_invalid", f"элемент {index}: нужно 0 ≤ start < end"
            )
        spans.append(VisemeSpan(start=start, end=end, viseme=viseme))

    spans.sort(key=lambda span: span.start)
    for previous, current in zip(spans, spans[1:]):
        if current.start < previous.end - 1e-6:
            raise VisemeError(
                "viseme_timing_invalid",
                f"виземы пересекаются: {previous.as_metadata()} и {current.as_metadata()}",
            )
    return spans


def check_timing_bounds(spans: Iterable[VisemeSpan], duration_s: float) -> None:
    """Тайминги не должны выходить за запись (допуск 0.5 с на хвост)."""

    for span in spans:
        if span.end > duration_s + 0.5:
            raise VisemeError(
                "viseme_timing_invalid",
                f"визем {span.as_metadata()} выходит за запись {duration_s:.2f} с",
            )


def _in_silence(t: float, silence_segments: Iterable[dict[str, Any]]) -> bool:
    for segment in silence_segments:
        start = _number(segment.get("start_s"))
        end = _number(segment.get("end_s"))
        if start is not None and end is not None and start <= t < end:
            return True
    return False


def frame_targets(
    spans: list[VisemeSpan],
    *,
    fps: int,
    duration_s: float,
    min_hold_ms: float = DEFAULT_MIN_HOLD_MS,
    silence_segments: Iterable[dict[str, Any]] = (),
    close_in_silence: bool = True,
) -> list[str]:
    """Состояние рта на кадр: визем, удержание и принудительное закрытие в паузах."""

    frames = max(1, round(duration_s * fps))
    kept = [
        span
        for span in spans
        if (span.end - span.start) * 1000.0 >= min_hold_ms
    ]
    if not kept and spans:
        # Короткая реплика целиком: не выбрасываем единственный визем.
        kept = [max(spans, key=lambda span: span.end - span.start)]

    silences = list(silence_segments)
    targets: list[str] = []
    for index in range(frames):
        t = (index + 0.5) / fps
        state = "closed"
        for span in kept:
            if span.start <= t < span.end:
                state = span.viseme
                break
        if close_in_silence and silences and _in_silence(t, silences):
            state = "closed"
        targets.append(state)
    return targets


def frame_mixes(
    targets: list[str],
    *,
    fps: int,
    blend_ms: float = DEFAULT_BLEND_MS,
) -> list[FrameMix]:
    """Сглаживает переключения виземов; на кадре не больше двух изображений."""

    if not targets:
        return []
    if blend_ms <= 0:
        return [FrameMix(primary=state, secondary=None, mix=0.0) for state in targets]

    # Постоянная времени сглаживания: за blend_ms вес проходит ~63 % пути.
    alpha = min(1.0, 1.0 / max(1e-6, blend_ms / 1000.0 * fps))
    weights: dict[str, float] = {state: 0.0 for state in VISEME_STATES}
    weights[targets[0]] = 1.0

    mixes: list[FrameMix] = []
    for state in targets:
        for key in weights:
            weights[key] *= 1.0 - alpha
        weights[state] += alpha
        ordered = sorted(
            VISEME_STATES, key=lambda key: (-weights[key], VISEME_STATES.index(key))
        )
        primary = ordered[0]
        secondary = ordered[1] if weights[ordered[1]] > 1e-4 else None
        total = weights[primary] + (weights[secondary] if secondary else 0.0)
        mix = (weights[secondary] / total) if secondary and total > 0 else 0.0
        mixes.append(
            FrameMix(primary=primary, secondary=secondary, mix=round(mix, 4))
        )
    return mixes


def _patch_box(
    region: MouthRegion, size: tuple[int, int]
) -> tuple[int, int, int, int]:
    width, height = size
    margin = max(2, round(min(width, height) * PATCH_MARGIN_RATIO))
    left = max(0, round(region.x * width) - margin)
    top = max(0, round(region.y * height) - margin)
    right = min(width, round((region.x + region.width) * width) + margin)
    bottom = min(height, round((region.y + region.height) * height) + margin)
    return left, top, max(left + 2, right), max(top + 2, bottom)


def render_blend_preview(
    source_image: bytes,
    variants: dict[str, bytes],
    timing: list[VisemeSpan],
    duration_s: float,
    audio_path: Path,
    region: MouthRegion,
    *,
    output_path: Path,
    fps: int = DEFAULT_FPS,
    max_side: int = MAX_OUTPUT_SIDE,
    blend_ms: float = DEFAULT_BLEND_MS,
    min_hold_ms: float = DEFAULT_MIN_HOLD_MS,
    silence_segments: Iterable[dict[str, Any]] = (),
    close_in_silence: bool = True,
) -> PreviewInfo:
    """Собирает MP4: h264 + исходная аудиодорожка (aac)."""

    region.validate()
    check_timing_bounds(timing, duration_s)
    missing = [state for state in VISEME_STATES if state not in variants]
    if missing:
        raise VisemeError(
            "viseme_set_incomplete", "нет кадров: " + ", ".join(missing)
        )

    base = decode_source_image(source_image, max_side=max_side)
    images: dict[str, Image.Image] = {}
    for state in VISEME_STATES:
        try:
            image = decode_source_image(variants[state], max_side=max_side)
        except MouthAnimationError as error:
            raise VisemeError(
                "viseme_image_invalid", f"{state}: {error.message}"
            ) from error
        if image.size != base.size:
            raise VisemeError(
                "viseme_resolution_mismatch",
                f"{state}: {image.width}×{image.height} против "
                f"{base.width}×{base.height} у источника",
            )
        images[state] = image

    targets = frame_targets(
        timing,
        fps=fps,
        duration_s=duration_s,
        min_hold_ms=min_hold_ms,
        silence_segments=silence_segments,
        close_in_silence=close_in_silence,
    )
    mixes = frame_mixes(targets, fps=fps, blend_ms=blend_ms)
    box = _patch_box(region, base.size)

    patches = {state: images[state].crop(box) for state in VISEME_STATES}
    frame = base.copy()
    ffmpeg = _ffmpeg()

    command = [
        ffmpeg,
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
        f"{len(mixes) / fps:.6f}",
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
        for mix in mixes:
            patch = patches[mix.primary]
            if mix.secondary is not None and mix.mix > 0:
                patch = Image.blend(patch, patches[mix.secondary], mix.mix)
            frame.paste(patch, (box[0], box[1]))
            process.stdin.write(frame.tobytes())
            if process.poll() is not None:
                raise BrokenPipeError("ffmpeg завершился до конца кадров")
        process.stdin.close()
        stderr = process.stderr.read()
        code = process.wait(timeout=FFMPEG_TIMEOUT_S)
    except (BrokenPipeError, OSError) as error:
        process.kill()
        stderr = process.stderr.read()
        raise VisemeError(
            "ffmpeg_failed", stderr.decode("utf-8", errors="replace") or str(error)
        ) from error
    finally:
        if process.poll() is None:
            process.kill()

    if code != 0:
        raise VisemeError(
            "ffmpeg_failed", stderr.decode("utf-8", errors="replace") or f"exit {code}"
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise VisemeError("ffmpeg_failed", "ffmpeg не создал MP4")

    from app.video_probe import VideoProbeError, probe_mp4

    try:
        info = probe_mp4(output_path.read_bytes())
    except VideoProbeError as error:
        raise VisemeError("invalid_preview", f"MP4 не прошёл проверку: {error}") from error
    if not info.has_audio:
        raise VisemeError("invalid_preview", "в результате нет аудиодорожки")

    return PreviewInfo(
        width=base.width,
        height=base.height,
        fps=fps,
        frames=max(1, round(info.duration_s * fps)),
        duration_s=round(info.duration_s, 3),
    )


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise VisemeError("ffmpeg_missing", "ffmpeg не найден в PATH")
    return path


def blend_parameters(
    *,
    region: MouthRegion,
    info: PreviewInfo,
    audio_asset_id: str,
    audio_sha256: str,
    source: dict[str, Any],
    calibration_id: str | None,
    variant_sha256: dict[str, str],
    timing: list[VisemeSpan],
    blend_ms: float,
    min_hold_ms: float,
    close_in_silence: bool,
    timing_source: str,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Провенанс попытки: набор кадров, тайминги и конфигурация смешивания."""

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
        "config": {
            "blend_ms": blend_ms,
            "min_hold_ms": min_hold_ms,
            "close_in_silence": close_in_silence,
        },
        "timing_source": timing_source,
        "timings": [span.as_metadata() for span in timing],
        "viseme_set": dict(variant_sha256),
        **(extras or {}),
    }
