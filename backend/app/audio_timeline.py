"""Таймлайн песни: FFmpeg + чистый Python (WP-M3).

Никаких новых зависимостей: ffmpeg декодирует аудио в моно-огибающую 100 Гц,
дальше BPM, биты и секции считаются чистой арифметикой. Это эвристика, а не
разметка песни: каждый параметр отдаётся с `confidence`, а границы секций
подтверждаются человеком в UI.
"""

from __future__ import annotations

import array
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ENVELOPE_RATE_HZ = 100
ANALYSIS_RATE_HZ = 4000
FRAME_SIZE = ANALYSIS_RATE_HZ // ENVELOPE_RATE_HZ
MIN_BPM = 60.0
MAX_BPM = 200.0
BEATS_PER_BAR = 4
MAX_SECTIONS = 12
FFPROBE_TIMEOUT_S = 60.0
FFMPEG_TIMEOUT_S = 300.0


class AudioTimelineError(Exception):
    """Ошибка анализа аудио с машинным кодом."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _binary(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise AudioTimelineError("ffmpeg_missing", f"{name} не найден в PATH")
    return path


def probe_audio(path: Path) -> tuple[float, bool]:
    """Возвращает (длительность, есть ли аудиодорожка)."""

    ffprobe = _binary("ffprobe")
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-show_entries",
                "stream=codec_type",
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
        raise AudioTimelineError("ffprobe_failed", f"ffprobe: {error}") from error
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AudioTimelineError("ffprobe_failed", "ffprobe вернул не JSON") from error

    streams = payload.get("streams") or []
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    raw_duration = (payload.get("format") or {}).get("duration")
    try:
        duration = float(raw_duration)
    except (TypeError, ValueError) as error:
        raise AudioTimelineError("ffprobe_failed", "длительность аудио неизвестна") from error
    if duration <= 0:
        raise AudioTimelineError("invalid_audio", "длительность аудио равна нулю")
    return duration, has_audio


def _decode_envelope(path: Path) -> list[float]:
    """Моно-огибающая RMS с частотой `ENVELOPE_RATE_HZ` (0…1)."""

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
        raise AudioTimelineError("ffmpeg_failed", f"ffmpeg: {error}") from error

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

    peak = max(frames, default=0.0)
    if peak <= 0:
        return [0.0] * len(frames)
    return [value / peak for value in frames]


def _onset_strength(envelope: list[float]) -> list[float]:
    strength = [0.0] * len(envelope)
    for index in range(1, len(envelope)):
        strength[index] = max(0.0, envelope[index] - envelope[index - 1])
    return strength


def _estimate_period(onset: list[float]) -> tuple[float | None, float]:
    """Период бита в кадрах огибающей и уверенность (0…1)."""

    min_lag = max(2, int(ENVELOPE_RATE_HZ * 60.0 / MAX_BPM))
    max_lag = min(len(onset) // 2, int(ENVELOPE_RATE_HZ * 60.0 / MIN_BPM))
    if max_lag <= min_lag:
        return None, 0.0

    energy = sum(value * value for value in onset)
    if energy <= 1e-9:
        return None, 0.0

    def autocorrelation(lag: int) -> float:
        total = 0.0
        for index in range(lag, len(onset)):
            total += onset[index] * onset[index - lag]
        return total / (len(onset) - lag)

    scores = {lag: autocorrelation(lag) for lag in range(min_lag, max_lag + 1)}
    best_lag = max(scores, key=lambda lag: scores[lag])
    best = scores[best_lag]
    if best <= 1e-12:
        return None, 0.0

    # Половина периода может давать тот же пик: предпочитаем более быстрый темп.
    half = best_lag // 2
    if half >= min_lag and scores.get(half, 0.0) >= 0.9 * best:
        best_lag = half
        best = scores[half]

    average = sum(scores.values()) / len(scores)
    confidence = 0.0 if average <= 0 else max(0.0, min(1.0, 1.0 - average / best))
    return float(best_lag), confidence


def _beats(onset: list[float], period: float, duration_s: float) -> list[float]:
    """Фаза сетки битов подбирается максимизацией силы онсетов на битах."""

    period_frames = max(1, int(round(period)))
    best_offset, best_score = 0, -1.0
    for offset in range(period_frames):
        score = 0.0
        position = offset
        while position < len(onset):
            score += onset[position]
            position += period_frames
        if score > best_score:
            best_offset, best_score = offset, score

    step_s = period_frames / ENVELOPE_RATE_HZ
    offset_s = best_offset / ENVELOPE_RATE_HZ
    beats: list[float] = []
    index = 0
    while True:
        value = offset_s + index * step_s
        if value > duration_s:
            break
        beats.append(round(value, 3))
        index += 1
    return beats


def _sections(
    envelope: list[float], beats: list[float], duration_s: float
) -> list[dict[str, Any]]:
    """Грубые секции по энергии тактов: без музыкальных ярлыков (intro/chorus)."""

    if len(beats) < BEATS_PER_BAR * 2:
        mean = sum(envelope) / len(envelope) if envelope else 0.0
        return [
            {
                "start_s": 0.0,
                "end_s": round(duration_s, 3),
                "rms": round(mean, 4),
                "energy_tier": "mid",
            }
        ]

    bar_energies: list[tuple[float, float, float]] = []
    for index in range(0, len(beats), BEATS_PER_BAR):
        start = beats[index]
        end = beats[index + BEATS_PER_BAR] if index + BEATS_PER_BAR < len(beats) else duration_s
        if end <= start:
            continue
        first = int(start * ENVELOPE_RATE_HZ)
        last = min(len(envelope), int(end * ENVELOPE_RATE_HZ))
        if last <= first:
            continue
        mean = sum(envelope[first:last]) / (last - first)
        bar_energies.append((start, end, mean))

    if not bar_energies:
        return [{"start_s": 0.0, "end_s": round(duration_s, 3), "rms": 0.0, "energy_tier": "mid"}]

    groups: list[list[tuple[float, float, float]]] = [[bar_energies[0]]]
    for bar in bar_energies[1:]:
        previous = groups[-1][-1][2]
        current = bar[2]
        ratio = (current + 1e-6) / (previous + 1e-6)
        if 0.75 <= ratio <= 1.34:
            groups[-1].append(bar)
        else:
            groups.append([bar])

    while len(groups) > MAX_SECTIONS:
        merged: list[list[tuple[float, float, float]]] = []
        index = 0
        while index < len(groups):
            if index + 1 < len(groups):
                merged.append(groups[index] + groups[index + 1])
                index += 2
            else:
                merged.append(groups[index])
                index += 1
        groups = merged

    means = [
        sum(bar[2] for bar in group) / len(group)
        for group in groups
    ]
    peak = max(means) if means else 0.0

    sections: list[dict[str, Any]] = []
    for group, mean in zip(groups, means):
        if peak <= 0 or mean <= 0.25 * peak:
            tier = "low"
        elif mean >= 0.6 * peak:
            tier = "high"
        else:
            tier = "mid"
        sections.append(
            {
                "start_s": round(group[0][0], 3),
                "end_s": round(group[-1][1], 3),
                "rms": round(mean, 4),
                "energy_tier": tier,
            }
        )
    return sections


def analyze_audio(path: Path) -> dict[str, Any]:
    """Строит таймлайн: длительность, BPM, биты, доли и энергетические секции."""

    duration, has_audio = probe_audio(path)
    if not has_audio:
        raise AudioTimelineError("missing_audio_stream", "в файле нет аудиодорожки")

    envelope = _decode_envelope(path)
    onset = _onset_strength(envelope)
    warnings: list[dict[str, str]] = []

    period, confidence = _estimate_period(onset)
    bpm: float | None = None
    beats: list[float] = []
    downbeats: list[float] = []
    if period is None:
        warnings.append(
            {
                "code": "beats_not_detected",
                "message": "Ритм не определён: таймлайн содержит только секции.",
            }
        )
    else:
        bpm = round(60.0 * ENVELOPE_RATE_HZ / period, 1)
        beats = _beats(onset, period, duration)
        downbeats = [beat for index, beat in enumerate(beats) if index % BEATS_PER_BAR == 0]
        if confidence < 0.35:
            warnings.append(
                {
                    "code": "low_bpm_confidence",
                    "message": "BPM определён неуверенно; проверьте сетку битов вручную.",
                }
            )

    return {
        "duration_s": round(duration, 3),
        "bpm": bpm,
        "bpm_confidence": round(confidence, 2),
        "meter": "4/4 (assumed)",
        "beats": beats[:6000],
        "downbeats": downbeats[:1500],
        "sections": _sections(envelope, beats, duration),
        "analysis_rate_hz": ENVELOPE_RATE_HZ,
        "method": "ffmpeg_envelope_v1",
        "warnings": warnings,
    }
