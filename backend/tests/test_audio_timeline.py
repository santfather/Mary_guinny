"""WP-M3: таймлайн песни (FFmpeg + чистый Python)."""

from __future__ import annotations

import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from app.audio_timeline import AudioTimelineError, analyze_audio, probe_audio

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="нужны ffmpeg и ffprobe")

SAMPLE_RATE = 8000


def _write_wav(path: Path, samples: list[int]) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def _click_track(path: Path, *, duration_s: float = 8.0, interval_s: float = 0.5) -> Path:
    """Клики каждые `interval_s` секунд: 120 BPM при 0.5 с."""

    frames = int(SAMPLE_RATE * duration_s)
    samples = [0] * frames
    click = int(SAMPLE_RATE * 0.05)
    moment = 0.0
    while moment < duration_s:
        start = int(moment * SAMPLE_RATE)
        for offset in range(click):
            if start + offset >= frames:
                break
            envelope = 1 - offset / click
            samples[start + offset] = int(
                12000 * envelope * math.sin(2 * math.pi * 1000 * offset / SAMPLE_RATE)
            )
        moment += interval_s
    return _write_wav(path, samples)


@needs_ffmpeg
def test_analyze_detects_bpm_beats_and_sections(tmp_path: Path) -> None:
    path = _click_track(tmp_path / "click.wav")

    duration, has_audio = probe_audio(path)
    assert has_audio is True
    assert duration == pytest.approx(8.0, abs=0.05)

    timeline = analyze_audio(path)
    assert timeline["method"] == "ffmpeg_envelope_v1"
    assert timeline["meter"] == "4/4 (assumed)"
    assert timeline["bpm"] == pytest.approx(120.0, abs=3.0)
    assert len(timeline["beats"]) >= 12
    assert timeline["downbeats"] == timeline["beats"][::4]
    assert timeline["sections"]
    first = timeline["sections"][0]
    assert first["start_s"] == pytest.approx(0.0, abs=0.05)
    assert timeline["sections"][-1]["end_s"] == pytest.approx(8.0, abs=0.05)
    assert all(section["energy_tier"] in {"low", "mid", "high"} for section in timeline["sections"])


@needs_ffmpeg
def test_analyze_silence_reports_missing_beats(tmp_path: Path) -> None:
    path = _write_wav(tmp_path / "silence.wav", [0] * (SAMPLE_RATE * 4))

    timeline = analyze_audio(path)
    assert timeline["bpm"] is None
    assert timeline["beats"] == []
    assert len(timeline["sections"]) == 1
    assert [warning["code"] for warning in timeline["warnings"]] == ["beats_not_detected"]


@needs_ffmpeg
def test_probe_rejects_file_without_audio(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("not audio", encoding="utf-8")

    with pytest.raises(AudioTimelineError) as error:
        probe_audio(path)
    assert error.value.code in {"ffprobe_failed", "invalid_audio"}
