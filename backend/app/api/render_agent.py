"""Read-only статус render-agent (WP-THERMAL-02, Q-29).

Воркер пишет `~/.mary-studio/thermal-state.json` и `thermal-events.jsonl`;
сервер и воркер работают на одной машине, поэтому эндпоинт только читает файлы
и очередь из БД. Управлять очередью через него нельзя, схема БД не меняется.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.models import Job, SeriesRun

router = APIRouter(prefix="/api/render-agent", tags=["render-agent"])

ACTIVE_RENDER_STATUSES = ("leased", "running")
PENDING_RENDER_STATUSES = ("pending", "retry_wait")
ACTIVE_RUN_STATUSES = ("running", "paused", "stopping")
TAIL_EVENTS = 10


class ThermalOut(BaseModel):
    state: str
    source: str


class PowerOut(BaseModel):
    source: str | None = None
    battery_percent: float | None = None
    # WP-THERMAL-03 (T-06): только чтение `pmset -g`; `None` = Unknown,
    # воркер не выдумывает выключенный режим.
    low_power_mode: bool | None = None


class MemoryOut(BaseModel):
    pressure: str | None = None
    pressure_level: int | None = None
    available_mb: int | None = None


class AdmissionOut(BaseModel):
    allowed: bool | None = None
    reason: str | None = None
    wait_seconds: float | None = None


class CooldownOut(BaseModel):
    next_allowed_at: str | None = None
    remaining_seconds: float | None = None


class PauseOut(BaseModel):
    active: bool = False
    reason: str | None = None
    since: str | None = None
    waited_seconds: float | None = None


class BatchOut(BaseModel):
    index: int | None = None
    size: int | None = None


class QueueOut(BaseModel):
    active_render_jobs: int
    pending_render_jobs: int
    current_run_id: str | None = None
    current_run_status: str | None = None


class EventOut(BaseModel):
    ts: str | None = None
    event: str | None = None
    reason: str | None = None
    thermal: str | None = None
    job_id: str | None = None


class RenderAgentStatusOut(BaseModel):
    worker_online: bool
    stale: bool
    updated_at: str | None = None
    age_seconds: float | None = None
    worker: str | None = None
    profile: str | None = None
    rendering: bool = False
    current_job_id: str | None = None
    thermal: ThermalOut
    power: PowerOut
    memory: MemoryOut
    admission: AdmissionOut
    cooldown: CooldownOut
    pause: PauseOut
    batch: BatchOut
    queue: QueueOut
    last_events: list[EventOut]


def _read_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _tail_events(path: Path, limit: int = TAIL_EVENTS) -> list[dict[str, Any]]:
    try:
        lines = path.read_text("utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _age_seconds(value: object, now: datetime) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - parsed).total_seconds())


def _queue(session: Session) -> QueueOut:
    active = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.kind == "render_video", Job.status.in_(ACTIVE_RENDER_STATUSES))
    )
    pending = session.scalar(
        select(func.count())
        .select_from(Job)
        .where(Job.kind == "render_video", Job.status.in_(PENDING_RENDER_STATUSES))
    )
    run = session.scalar(
        select(SeriesRun)
        .where(SeriesRun.status.in_(ACTIVE_RUN_STATUSES))
        .order_by(SeriesRun.created_at.desc())
        .limit(1)
    )
    return QueueOut(
        active_render_jobs=int(active or 0),
        pending_render_jobs=int(pending or 0),
        current_run_id=str(run.id) if run is not None else None,
        current_run_status=run.status if run is not None else None,
    )


@router.get("/status", response_model=RenderAgentStatusOut)
def get_render_agent_status(
    request: Request, session: Session = Depends(get_session)
) -> RenderAgentStatusOut:
    settings = request.app.state.settings
    state = _read_state(settings.render_agent_state_path)
    now = datetime.now(timezone.utc)
    age = _age_seconds(state.get("updated_at"), now)
    stale = age is None or age > settings.render_agent_stale_seconds

    thermal = state.get("thermal") if isinstance(state.get("thermal"), dict) else {}
    power = state.get("power") if isinstance(state.get("power"), dict) else {}
    low_power_mode = state.get("low_power_mode")
    if not isinstance(low_power_mode, bool):
        low_power_mode = None
    memory = state.get("memory") if isinstance(state.get("memory"), dict) else {}
    available_bytes = memory.get("available_bytes")
    pause = state.get("pause") if isinstance(state.get("pause"), dict) else {}
    batch = state.get("batch") if isinstance(state.get("batch"), dict) else {}
    admission = (
        state.get("admission") if isinstance(state.get("admission"), dict) else {}
    )
    cooldown = (
        state.get("cooldown") if isinstance(state.get("cooldown"), dict) else {}
    )

    return RenderAgentStatusOut(
        worker_online=bool(state) and not stale,
        stale=stale,
        updated_at=state.get("updated_at"),
        age_seconds=None if age is None else round(age, 1),
        worker=state.get("worker"),
        profile=state.get("profile"),
        rendering=bool(state.get("rendering", False)),
        current_job_id=state.get("current_job_id"),
        thermal=ThermalOut(
            state=str(thermal.get("state") or "unknown"),
            source=str(thermal.get("source") or "none"),
        ),
        power=PowerOut(
            source=power.get("source"),
            battery_percent=power.get("battery_percent"),
            low_power_mode=low_power_mode,
        ),
        memory=MemoryOut(
            pressure=memory.get("pressure"),
            pressure_level=memory.get("pressure_level"),
            available_mb=(
                int(available_bytes) // (1024 * 1024)
                if isinstance(available_bytes, int)
                else None
            ),
        ),
        admission=AdmissionOut(
            allowed=admission.get("allowed"),
            reason=admission.get("reason"),
            wait_seconds=admission.get("wait_seconds"),
        ),
        cooldown=CooldownOut(
            next_allowed_at=cooldown.get("next_allowed_at"),
            remaining_seconds=cooldown.get("remaining_seconds"),
        ),
        pause=PauseOut(
            active=bool(pause.get("active", False)),
            reason=pause.get("reason"),
            since=pause.get("since"),
            waited_seconds=pause.get("waited_seconds"),
        ),
        batch=BatchOut(index=batch.get("index"), size=batch.get("size")),
        queue=_queue(session),
        last_events=[
            EventOut(
                ts=record.get("ts"),
                event=record.get("event"),
                reason=record.get("reason"),
                thermal=record.get("thermal"),
                job_id=record.get("job_id"),
            )
            for record in _tail_events(settings.render_agent_events_path)
        ],
    )
