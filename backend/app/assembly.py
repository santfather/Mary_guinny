"""Сборка вертикального MP4 из видео-попыток (WP-M2).

FFmpeg вызывается списком аргументов (без shell). Исходные блобы только
читаются: результат всегда пишется в отдельный временный файл. Нормализация —
1080×1920, 24 fps, letterbox через `scale`+`pad` (без растяжения), звук клипов
сохраняется; клипы без аудио получают тишину (решение 2026-11-04, DECISIONS §4.8).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.video_probe import Mp4Info, VideoProbeError, probe_mp4

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FPS = 24
AUDIO_RATE = 48000
EXPORT_TIMEOUT_S = 600.0
_PROBE_TIMEOUT_S = 60.0


class AssemblyError(ValueError):
    """Ошибка подготовки или сборки; `code` уходит в ответ API."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ClipSource:
    path: Path
    has_audio: bool
    trim_start_s: float
    trim_end_s: float

    @property
    def trimmed_duration_s(self) -> float:
        return round(self.trim_end_s - self.trim_start_s, 3)


def _ffprobe(path: Path) -> tuple[float, bool]:
    """Длительность контейнера и наличие аудиодорожки."""

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_S
        )
    except subprocess.TimeoutExpired as error:
        raise AssemblyError("ffprobe_failed", "ffprobe не ответил вовремя") from error
    except OSError as error:
        raise AssemblyError("ffprobe_failed", str(error)) from error
    if result.returncode != 0:
        raise AssemblyError("ffprobe_failed", result.stderr.strip()[:500] or "ffprobe error")

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        raise AssemblyError("ffprobe_failed", "ffprobe вернул не JSON") from error
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError) as error:
        raise AssemblyError("ffprobe_failed", "ffprobe: некорректная длительность") from error
    if duration <= 0:
        raise AssemblyError("invalid_input", "не удалось определить длительность клипа")

    streams = payload.get("streams") or []
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    has_video = any(stream.get("codec_type") == "video" for stream in streams)
    if not has_video:
        raise AssemblyError("invalid_input", "в клипе нет видеодорожки")
    return duration, has_audio


def prepare_clip(
    path: Path,
    *,
    trim_start_s: float | None = None,
    trim_end_s: float | None = None,
) -> ClipSource:
    """Проверяет файл и границы тримма до запуска ffmpeg."""

    if not path.is_file():
        raise AssemblyError("missing_source", f"файл клипа не найден: {path.name}")
    duration, has_audio = _ffprobe(path)
    start = 0.0 if trim_start_s is None else float(trim_start_s)
    end = duration if trim_end_s is None else float(trim_end_s)
    if start < 0:
        raise AssemblyError("invalid_trim", "trim_start_s не может быть отрицательным")
    if end <= start:
        raise AssemblyError("invalid_trim", "trim_end_s должен быть больше trim_start_s")
    if end > duration + 0.05:
        raise AssemblyError(
            "trim_out_of_range",
            f"trim_end_s={end:.3f} больше длительности клипа {duration:.3f}",
        )
    return ClipSource(
        path=path,
        has_audio=has_audio,
        trim_start_s=round(start, 3),
        trim_end_s=round(min(end, duration), 3),
    )


def _video_filter(index: int, clip: ClipSource) -> str:
    return (
        f"[{index}:v]trim=start={clip.trim_start_s:.3f}:end={clip.trim_end_s:.3f},"
        "setpts=PTS-STARTPTS,"
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_WIDTH}:{TARGET_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={TARGET_FPS},format=yuv420p[v{index}]"
    )


def _audio_filter(index: int, clip: ClipSource) -> str:
    duration = clip.trimmed_duration_s
    if not clip.has_audio:
        return (
            f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE},"
            f"atrim=duration={duration:.3f},asetpts=PTS-STARTPTS[a{index}]"
        )
    return (
        f"[{index}:a]atrim=start={clip.trim_start_s:.3f}:end={clip.trim_end_s:.3f},"
        f"asetpts=PTS-STARTPTS,aresample={AUDIO_RATE},"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"apad=whole_dur={duration:.3f},atrim=duration={duration:.3f}[a{index}]"
    )


def build_command(
    clips: list[ClipSource], audio_path: Path | None, output_path: Path
) -> list[str]:
    """Команда ffmpeg: нормализация клипов, concat, опциональная замена звука."""

    command = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command += ["-i", str(clip.path)]
    if audio_path is not None:
        command += ["-i", str(audio_path)]

    filters: list[str] = []
    for index, clip in enumerate(clips):
        filters.append(_video_filter(index, clip))
        if audio_path is None:
            filters.append(_audio_filter(index, clip))
    if audio_path is None:
        inputs = "".join(f"[v{index}][a{index}]" for index in range(len(clips)))
        filters.append(f"{inputs}concat=n={len(clips)}:v=1:a=1[vcat][acat]")
    else:
        # Внешняя дорожка заменяет звук клипов: аудио из клипов не декодируется.
        inputs = "".join(f"[v{index}]" for index in range(len(clips)))
        filters.append(f"{inputs}concat=n={len(clips)}:v=1:a=0[vcat]")
        filters.append(
            f"[{len(clips)}:a]aresample={AUDIO_RATE},"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,apad[amusic]"
        )

    command += ["-filter_complex", ";".join(filters), "-map", "[vcat]"]
    command += ["-map", "[amusic]" if audio_path is not None else "[acat]"]
    command += [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
    ]
    if audio_path is not None:
        # `apad` делает дорожку бесконечной: -shortest останавливает её по видео.
        command += ["-shortest"]
    command += [str(output_path)]
    return command


def assemble_export(
    clips: list[ClipSource], audio_path: Path | None, output_path: Path
) -> Mp4Info:
    """Собирает MP4 и проверяет результат; исходники не изменяются."""

    if not clips:
        raise AssemblyError("no_clips", "список клипов пуст")
    if audio_path is not None and not audio_path.is_file():
        raise AssemblyError("missing_audio", "аудиофайл не найден")

    command = build_command(clips, audio_path, output_path)
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=EXPORT_TIMEOUT_S
        )
    except subprocess.TimeoutExpired as error:
        raise AssemblyError(
            "ffmpeg_timeout", f"сборка превысила {EXPORT_TIMEOUT_S:.0f} с"
        ) from error
    except OSError as error:
        raise AssemblyError("ffmpeg_missing", str(error)) from error
    if result.returncode != 0:
        raise AssemblyError(
            "ffmpeg_failed", result.stderr.strip()[-800:] or "ffmpeg завершился с ошибкой"
        )
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise AssemblyError("empty_output", "ffmpeg не создал выходной файл")

    try:
        info = probe_mp4(output_path.read_bytes())
    except VideoProbeError as error:
        raise AssemblyError("invalid_output", str(error)) from error
    return info


def ffmpeg_version() -> str:
    """Версия ffmpeg для провенанса; при ошибке — `unknown`."""

    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    parts = (result.stdout or "").split()
    return parts[2] if len(parts) >= 3 else "unknown"
