"""Пресеты рендера под оборудование (WP-M7).

Принцип: в таблицу попадают только **измеренные** режимы. Для 576×1024 и 1024×576
есть реальные прогоны серии «Ночной тыгыдык», для 512×512 — прогон WP-00A. Пресеты
без замеров не добавляются, пока человек не проведёт рендер и не зафиксирует время.

Детект железа — только stdlib и системные утилиты macOS (`sysctl`, `vm_stat`),
без новых зависимостей. CUDA/NVML не используются: на Apple Silicon их нет.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass

GIB = 1024**3
MIN_APPLE_SILICON_GIB = 16.0


@dataclass(frozen=True)
class Hardware:
    system: str
    machine: str
    model: str | None
    chip: str | None
    cpu_count: int | None
    total_memory_bytes: int | None
    available_memory_bytes: int | None
    apple_silicon: bool
    control_plane_only: bool


@dataclass(frozen=True)
class Preset:
    name: str
    label: str
    aspect_ratio: str
    long_side: int
    width: int
    height: int
    cfg_scale: float
    measured: bool
    measured_runs: int
    avg_render_seconds: float | None
    note: str


# Только измеренные режимы: каждое число ниже подтверждено реальным прогоном.
PRESETS: tuple[Preset, ...] = (
    Preset(
        name="safe",
        label="Safe",
        aspect_ratio="9:16",
        long_side=1024,
        width=576,
        height=1024,
        cfg_scale=3.0,
        measured=True,
        measured_runs=24,
        avg_render_seconds=1062.5,
        note="прогон «NLB-single»: 24 шота за 7 ч 05 мин (≈ 17,7 мин/шот)",
    ),
    Preset(
        name="wide",
        label="Wide",
        aspect_ratio="16:9",
        long_side=1024,
        width=1024,
        height=576,
        cfg_scale=3.0,
        measured=True,
        measured_runs=3,
        avg_render_seconds=None,
        note="прогон «NLB-single wide (28-30)»: 3 шота, 1024×576",
    ),
    Preset(
        name="legacy_512",
        label="Legacy 512",
        aspect_ratio="1:1",
        long_side=512,
        width=512,
        height=512,
        cfg_scale=3.0,
        measured=True,
        measured_runs=1,
        avg_render_seconds=None,
        note="WP-00A: один прогон 512×512, 73 кадра, 24 fps, экспериментальный",
    ),
)

_PAGE_SIZE = re.compile(r"page size of (\d+) bytes")
_PAGE_COUNTERS = ("Pages free", "Pages inactive", "Pages speculative")


def _run(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=3, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _sysctl(name: str) -> str | None:
    return _run(["sysctl", "-n", name])


def _sysctl_int(name: str) -> int | None:
    raw = _sysctl(name)
    if raw is None or not raw.strip().isdigit():
        return None
    return int(raw.strip())


def parse_vm_stat(text: str) -> int | None:
    """Доступная память по `vm_stat`: free + inactive + speculative страницы."""

    page = _PAGE_SIZE.search(text)
    if page is None:
        return None
    pages = 0
    for counter in _PAGE_COUNTERS:
        match = re.search(rf"{counter}:\s+(\d+)\.", text)
        if match is None:
            return None
        pages += int(match.group(1))
    return pages * int(page.group(1))


def detect_hardware() -> Hardware:
    system = platform.system()
    machine = platform.machine()
    is_macos = system == "Darwin"
    apple_silicon = is_macos and machine == "arm64"
    total_memory_bytes = _sysctl_int("hw.memsize") if is_macos else None
    available_memory_bytes = None
    if is_macos:
        vm_stat = _run(["vm_stat"])
        available_memory_bytes = parse_vm_stat(vm_stat) if vm_stat is not None else None
    return Hardware(
        system=system,
        machine=machine,
        model=_sysctl("hw.model") if is_macos else None,
        chip=_sysctl("machdep.cpu.brand_string") if is_macos else None,
        cpu_count=os.cpu_count(),
        total_memory_bytes=total_memory_bytes,
        available_memory_bytes=available_memory_bytes,
        apple_silicon=apple_silicon,
        control_plane_only=not apple_silicon,
    )


def get_preset(name: str) -> Preset | None:
    return next((preset for preset in PRESETS if preset.name == name), None)


def recommend(hardware: Hardware) -> tuple[str | None, str]:
    """Рекомендация — только измеренный пресет; без Apple Silicon её нет."""

    if not hardware.apple_silicon:
        return None, (
            "видеорендер не рекомендуется: нужен Apple Silicon (эта машина — control plane)"
        )
    if hardware.total_memory_bytes is None:
        return None, "не удалось определить объём памяти"
    total_gib = hardware.total_memory_bytes / GIB
    if total_gib < MIN_APPLE_SILICON_GIB:
        return None, (
            f"недостаточно памяти: {total_gib:.1f} ГиБ < {MIN_APPLE_SILICON_GIB:.0f} ГиБ"
        )
    return "safe", "рекомендован измеренный пресет safe (576×1024)"
