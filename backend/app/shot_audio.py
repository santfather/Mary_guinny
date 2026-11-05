"""Подготовка аудио шота (WP-VOICE-02, DECISIONS §4.19).

Оригинал не меняется: он кладётся в content-addressed storage как есть, а рядом
создаётся рабочий PCM WAV 48 кГц mono. Из рабочей копии считается огибающая RMS
(50 Гц), по ней — речевые участки и паузы. Никаких новых зависимостей: только
ffmpeg/ffprobe и чистый Python.
"""

from __future__ import annotations

import array
import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SHOT_AUDIO_ROLE = "shot_audio"
WORK_SAMPLE_RATE = 48000
WORK_CHANNELS = 1
ENVELOPE_RATE_HZ = 50
ANALYSIS_RATE_HZ = 4000
FRAME_SIZE = ANALYSIS_RATE_HZ // ENVELOPE_RATE_HZ
# Порог открытия рта: доля от пика RMS. Ниже порога — тишина, рот закрыт.
SILENCE_RELATIVE_GATE = 0.06
# Паузы короче этого значения не разрывают речевой участок.
MIN_SILENCE_S = 0.12
FFPROBE_TIMEOUT_S = 60.0
FFMPEG_TIMEOUT_S = 300.0


class ShotAudioError(Exception):
    """Ошибка подготовки аудио с машинным кодом."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AudioDetails:
    duration_s: float
    sample_rate: int | None
    channels: int | None
    codec: str | None
    format_name: str | None


def _binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise ShotAudioError("ffmpeg_missing", f"{name} не найден в PATH")
    return path


def probe_audio_details(path: Path) -> AudioDetails:
    """Реальный формат файла по ffprobe (не по расширению и не по Content-Type)."""

    ffprobe = _binary("ffprobe")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels,codec_type",
                "-show_entries",
                "format=duration,format_name",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_S,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ShotAudioError("ffprobe_failed", f"ffprobe: {error}") from error

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ShotAudioError("ffprobe_failed", "ffprobe вернул не JSON") from error

    streams = payload.get("streams") or []
    stream = streams[0] if streams else {}
    if stream.get("codec_type") != "audio":
        raise ShotAudioError("missing_audio_stream", "в файле нет аудиодорожки")

    raw_duration = (payload.get("format") or {}).get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as error:
        raise ShotAudioError(
            "invalid_audio", "длительность аудио неизвестна"
        ) from error
    if duration <= 0:
        raise ShotAudioError("invalid_audio", "длительность аудио равна нулю")

    def _int(value: object) -> int | None:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    return AudioDetails(
        duration_s=round(duration, 3),
        sample_rate=_int(stream.get("sample_rate")),
        channels=_int(stream.get("channels")),
        codec=stream.get("codec_name"),
        format_name=(payload.get("format") or {}).get("format_name"),
    )


def write_work_wav(source: Path, target: Path) -> None:
    """Рабочая копия: PCM 16 бит, 48 кГц, моно. Оригинал только читается."""

    ffmpeg = _binary("ffmpeg")
    try:
        subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                str(WORK_CHANNELS),
                "-ar",
                str(WORK_SAMPLE_RATE),
                "-acodec",
                "pcm_s16le",
                "-f",
                "wav",
                str(target),
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_S,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ShotAudioError("ffmpeg_failed", f"ffmpeg: {error}") from error
    if not target.is_file() or target.stat().st_size == 0:
        raise ShotAudioError("ffmpeg_failed", "ffmpeg не создал рабочий WAV")


def decode_envelope(path: Path) -> list[float]:
    """Абсолютная RMS-огибающая 50 Гц (0…1) по рабочему WAV."""

    ffmpeg = _binary("ffmpeg")
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(ANALYSIS_RATE_HZ),
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=FFMPEG_TIMEOUT_S,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ShotAudioError("ffmpeg_failed", f"ffmpeg: {error}") from error

    samples = array.array("h")
    samples.frombytes(result.stdout[: len(result.stdout) - len(result.stdout) % 2])
    if sys.byteorder != "little":
        samples.byteswap()

    frames: list[float] = []
    for index in range(len(samples) // FRAME_SIZE):
        start = index * FRAME_SIZE
        chunk = samples[start : start + FRAME_SIZE]
        energy = sum(value * value for value in chunk) / FRAME_SIZE
        frames.append(math.sqrt(energy) / 32768.0)
    return frames


def _segments(
    values: list[float], active: list[bool], *, min_gap_frames: int
) -> list[dict[str, float]]:
    """Склеивает соседние активные кадры в интервалы, гася короткие разрывы."""

    segments: list[dict[str, float]] = []
    start: int | None = None
    last_active: int | None = None
    for index, flag in enumerate(active):
        if flag:
            if start is None:
                start = index
            elif last_active is not None and index - last_active > min_gap_frames:
                segments.append(
                    {
                        "start_s": round(start / ENVELOPE_RATE_HZ, 3),
                        "end_s": round((last_active + 1) / ENVELOPE_RATE_HZ, 3),
                    }
                )
                start = index
            last_active = index
    if start is not None and last_active is not None:
        segments.append(
            {
                "start_s": round(start / ENVELOPE_RATE_HZ, 3),
                "end_s": round((last_active + 1) / ENVELOPE_RATE_HZ, 3),
            }
        )
    return [segment for segment in segments if segment["end_s"] > segment["start_s"]]


def speech_and_silence(
    envelope: list[float], gate: float
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    """Речевые участки и паузы по порогу; короткие провалы не считаются паузой."""

    if not envelope:
        return [], []
    active = [value >= gate for value in envelope]
    speech = _segments(
        envelope, active, min_gap_frames=int(MIN_SILENCE_S * ENVELOPE_RATE_HZ)
    )
    silence: list[dict[str, float]] = []
    cursor = 0.0
    total = round(len(envelope) / ENVELOPE_RATE_HZ, 3)
    for segment in speech:
        if segment["start_s"] - cursor >= MIN_SILENCE_S:
            silence.append({"start_s": cursor, "end_s": segment["start_s"]})
        cursor = segment["end_s"]
    if total - cursor >= MIN_SILENCE_S:
        silence.append({"start_s": cursor, "end_s": total})
    return speech, silence


def analyse_envelope(envelope: list[float]) -> dict[str, Any]:
    """Огибающая + порог + речевые участки/паузы для metadata актива."""

    peak = max(envelope, default=0.0)
    # 6 знаков: минимальный порог 1e-6 не должен округляться до нуля на тишине.
    gate = round(max(peak * SILENCE_RELATIVE_GATE, 1e-6), 6)
    speech, silence = speech_and_silence(envelope, gate)
    return {
        "envelope_rate_hz": ENVELOPE_RATE_HZ,
        "envelope": [round(value, 4) for value in envelope],
        "peak_rms": round(peak, 5),
        "gate": gate,
        "speech_segments": speech,
        "silence_segments": silence,
        "speech_ratio": round(
            sum(segment["end_s"] - segment["start_s"] for segment in speech)
            / max(len(envelope) / ENVELOPE_RATE_HZ, 1e-6),
            3,
        ),
    }


def waveform_peaks(envelope: list[float], buckets: int) -> list[float]:
    """Ровно `buckets` максимумов огибающей для waveform в UI."""

    if not envelope or buckets <= 0:
        return []
    total = len(envelope)
    peaks: list[float] = []
    for index in range(buckets):
        start = (index * total) // buckets
        end = max(start + 1, ((index + 1) * total) // buckets)
        peaks.append(round(max(envelope[start:end]), 4))
    return peaks
