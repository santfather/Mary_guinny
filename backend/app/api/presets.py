"""Эндпоинт рекомендации пресетов рендера (WP-M7). Только чтение."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter
from pydantic import BaseModel

from app import presets

router = APIRouter(prefix="/api", tags=["presets"])


class HardwareOut(BaseModel):
    system: str
    machine: str
    model: str | None
    chip: str | None
    cpu_count: int | None
    total_memory_bytes: int | None
    available_memory_bytes: int | None
    apple_silicon: bool
    control_plane_only: bool


class PresetOut(BaseModel):
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


class PresetsOut(BaseModel):
    hardware: HardwareOut
    presets: list[PresetOut]
    recommended: str | None
    reason: str


@router.get("/presets", response_model=PresetsOut)
def get_presets() -> PresetsOut:
    hardware = presets.detect_hardware()
    recommended, reason = presets.recommend(hardware)
    return PresetsOut(
        hardware=HardwareOut(**asdict(hardware)),
        presets=[PresetOut(**asdict(preset)) for preset in presets.PRESETS],
        recommended=recommended,
        reason=reason,
    )
