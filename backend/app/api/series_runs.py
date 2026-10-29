"""Управляемый последовательный прогон серии (WP-N4).

Прогон — это намерение человека и прогресс по шотам; тяжёлые рендеры по-прежнему
выполняются одной job за раз через существующий worker-протокол. Следующая job
создаётся только после завершения текущей, поэтому `concurrency = 1` соблюдается
без отдельной очереди.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_session, require_project
from app.api.worker import require_worker_token
from app.models import (
    ACTIVE_JOB_STATUSES,
    Event,
    Job,
    PromptRevision,
    Scene,
    SeriesItem,
    SeriesRun,
    Shot,
    ShotReference,
)
from app.notify import notify

project_router = APIRouter(prefix="/api/projects", tags=["series"])
run_router = APIRouter(prefix="/api/series", tags=["series"])
worker_router = APIRouter(
    prefix="/api/worker", tags=["worker"], dependencies=[Depends(require_worker_token)]
)

TERMINAL_RUN_STATUSES = ("completed", "cancelled", "failed")
ITEM_STATUSES = ("pending", "running", "completed", "failed", "skipped")


class SeriesRunCreate(BaseModel):
    """Параметры прогона: подмножество шотов (для ворот «2 шота») и политика ошибок."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    shot_orders: list[int] | None = Field(default=None, min_length=1)
    stop_on_error: bool = True
    manifest_sha256: str | None = Field(default=None, max_length=64)


class SeriesNextRequest(BaseModel):
    """Запрос воркера на следующую job серии."""

    worker_name: str = Field(min_length=1, max_length=100)
    run_id: uuid.UUID | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _motion_revision(session: Session, shot_id: uuid.UUID) -> PromptRevision | None:
    return session.scalar(
        select(PromptRevision)
        .where(
            PromptRevision.shot_id == shot_id,
            PromptRevision.prompt_type == "motion",
        )
        .order_by(PromptRevision.version.desc())
        .limit(1)
    )


def _has_reference(session: Session, shot_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(ShotReference.id).where(ShotReference.shot_id == shot_id).limit(1)
        )
        is not None
    )


def blocked_reason(session: Session, shot: Shot) -> str | None:
    """Причина, по которой шот нельзя запускать; `None` — готов.

    Блокировки выводятся из данных, а не из enum `Shot.status` (схема не меняется).
    """

    if shot.start_keyframe_artifact_id is None:
        return "missing_start_frame"
    revision = _motion_revision(session, shot.id)
    if revision is None or not revision.prompt.strip():
        return "missing_prompt"
    parameters = revision.parameters_json or {}
    if parameters.get("reference_filename") and not _has_reference(session, shot.id):
        return "missing_reference"
    return None


def _project_shots(session: Session, project_id: uuid.UUID) -> list[Shot]:
    return list(
        session.scalars(
            select(Shot)
            .join(Scene, Scene.id == Shot.scene_id)
            .where(Scene.project_id == project_id)
            .order_by(Shot.sequence_no, Shot.id)
        )
    )


def _require_run(session: Session, run_id: uuid.UUID) -> SeriesRun:
    run = session.get(SeriesRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="series run not found")
    return run


def _require_status(run: SeriesRun, allowed: tuple[str, ...], action: str) -> None:
    if run.status not in allowed:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_state",
                "action": action,
                "status": run.status,
                "allowed": list(allowed),
            },
        )


def _counts(items: list[SeriesItem]) -> dict[str, int]:
    counts = {name: 0 for name in ITEM_STATUSES}
    for item in items:
        counts[item.status] += 1
    return counts


def _job_progress(session: Session, job_id: uuid.UUID | None) -> float | None:
    if job_id is None:
        return None
    value: Decimal | None = session.scalar(
        select(Event.progress)
        .where(Event.job_id == job_id, Event.progress.is_not(None))
        .order_by(Event.sequence.desc())
        .limit(1)
    )
    return float(value) if value is not None else None


def _run_out(session: Session, run: SeriesRun) -> dict[str, Any]:
    rows = session.execute(
        select(SeriesItem, Shot.sequence_no, Job.status)
        .join(Shot, Shot.id == SeriesItem.shot_id)
        .outerjoin(Job, Job.id == SeriesItem.job_id)
        .where(SeriesItem.run_id == run.id)
        .order_by(SeriesItem.order)
    ).all()
    items = [row[0] for row in rows]
    return {
        "run_id": str(run.id),
        "project_id": str(run.project_id),
        "title": run.title,
        "status": run.status,
        "stop_on_error": run.stop_on_error,
        "manifest_sha256": run.manifest_sha256,
        "total_items": run.total_items,
        "counts": _counts(items),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "items": [
            {
                "order": item.order,
                "shot_id": str(item.shot_id),
                "shot_sequence_no": sequence_no,
                "status": item.status,
                "job_id": str(item.job_id) if item.job_id else None,
                "job_status": job_status,
                "progress": _job_progress(session, item.job_id)
                if job_status in ("leased", "running")
                else None,
                "error_code": item.error_code,
                "started_at": _iso(item.started_at),
                "finished_at": _iso(item.finished_at),
            }
            for item, sequence_no, job_status in rows
        ],
    }


@project_router.post(
    "/{project_id}/series/runs", status_code=status.HTTP_201_CREATED
)
def create_series_run(
    project_id: uuid.UUID,
    request: SeriesRunCreate,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Создаёт прогон: готовые шоты — `pending`, неготовые — `skipped` с причиной."""

    require_project(session, project_id)
    shots = _project_shots(session, project_id)
    if not shots:
        raise HTTPException(status_code=409, detail="project has no shots")
    if request.shot_orders is not None:
        by_sequence = {shot.sequence_no: shot for shot in shots}
        unknown = [order for order in request.shot_orders if order not in by_sequence]
        if unknown:
            raise HTTPException(
                status_code=422, detail={"unknown_shot_orders": unknown}
            )
        selected = [by_sequence[order] for order in request.shot_orders]
    else:
        selected = shots

    run = SeriesRun(
        project_id=project_id,
        title=request.title,
        manifest_sha256=request.manifest_sha256,
        status="draft",
        stop_on_error=request.stop_on_error,
        total_items=len(selected),
    )
    session.add(run)
    session.flush()
    for index, shot in enumerate(selected, start=1):
        reason = blocked_reason(session, shot)
        session.add(
            SeriesItem(
                run_id=run.id,
                shot_id=shot.id,
                order=index,
                status="skipped" if reason else "pending",
                error_code=reason,
            )
        )
    session.commit()
    session.refresh(run)
    return _run_out(session, run)


@project_router.get("/{project_id}/series/runs")
def list_series_runs(
    project_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
    require_project(session, project_id)
    runs = session.scalars(
        select(SeriesRun)
        .where(SeriesRun.project_id == project_id)
        .order_by(SeriesRun.created_at.desc())
    ).all()
    return [
        {
            "run_id": str(run.id),
            "title": run.title,
            "status": run.status,
            "total_items": run.total_items,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "created_at": _iso(run.created_at),
        }
        for run in runs
    ]


@run_router.get("/{run_id}")
def get_series_run(
    run_id: uuid.UUID, session: Session = Depends(get_session)
) -> dict[str, Any]:
    return _run_out(session, _require_run(session, run_id))


@run_router.post("/{run_id}/start")
def start_series_run(
    run_id: uuid.UUID, session: Session = Depends(get_session)
) -> dict[str, Any]:
    run = _require_run(session, run_id)
    _require_status(run, ("draft", "paused"), "start")
    pending = session.scalar(
        select(SeriesItem.id)
        .where(SeriesItem.run_id == run.id, SeriesItem.status == "pending")
        .limit(1)
    )
    if pending is None:
        raise HTTPException(status_code=409, detail="no ready items in this run")
    run.status = "running"
    if run.started_at is None:
        run.started_at = _now()
    session.commit()
    notify("Mary Studio: серия запущена", f"Готово к запуску шотов: {run.total_items}")
    return _run_out(session, run)


@run_router.post("/{run_id}/pause")
def pause_series_run(
    run_id: uuid.UUID, session: Session = Depends(get_session)
) -> dict[str, Any]:
    run = _require_run(session, run_id)
    _require_status(run, ("running",), "pause")
    run.status = "paused"
    session.commit()
    return _run_out(session, run)


@run_router.post("/{run_id}/resume")
def resume_series_run(
    run_id: uuid.UUID, session: Session = Depends(get_session)
) -> dict[str, Any]:
    run = _require_run(session, run_id)
    _require_status(run, ("paused",), "resume")
    run.status = "running"
    session.commit()
    return _run_out(session, run)


@run_router.post("/{run_id}/stop-after-current")
def stop_after_current(
    run_id: uuid.UUID, session: Session = Depends(get_session)
) -> dict[str, Any]:
    run = _require_run(session, run_id)
    _require_status(run, ("running",), "stop-after-current")
    run.status = "stopping"
    session.commit()
    return _run_out(session, run)


@run_router.post("/{run_id}/cancel")
def cancel_series_run(
    run_id: uuid.UUID, session: Session = Depends(get_session)
) -> dict[str, Any]:
    run = _require_run(session, run_id)
    _require_status(run, ("draft", "running", "paused", "stopping"), "cancel")
    run.status = "cancelled"
    run.finished_at = _now()
    for item in session.scalars(
        select(SeriesItem).where(SeriesItem.run_id == run.id, SeriesItem.status == "pending")
    ):
        item.status = "skipped"
        item.error_code = "cancelled"
    session.commit()
    return _run_out(session, run)


def _active_run(session: Session, run_id: uuid.UUID | None) -> SeriesRun | None:
    statement = select(SeriesRun)
    if run_id is not None:
        return session.scalar(statement.where(SeriesRun.id == run_id).with_for_update())
    return session.scalar(
        statement.where(SeriesRun.status == "running")
        .order_by(SeriesRun.started_at, SeriesRun.created_at)
        .limit(1)
        .with_for_update()
    )


def _running_item(session: Session, run: SeriesRun) -> SeriesItem | None:
    return session.scalar(
        select(SeriesItem).where(
            SeriesItem.run_id == run.id, SeriesItem.status == "running"
        )
    )


def _job_for(session: Session, item: SeriesItem) -> Job | None:
    return session.get(Job, item.job_id) if item.job_id is not None else None


def _finish_run(session: Session, run: SeriesRun, status: str) -> None:
    run.status = status
    run.finished_at = _now()


@worker_router.post("/series/next")
def series_next(
    request: SeriesNextRequest, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Воркер просит следующую job серии: одна тяжёлая job за раз.

    Вызов продвигает прогон: закрывает завершившийся item, создаёт job на
    следующий готовый шот либо останавливает прогон по `stop_on_error`.
    """

    run = _active_run(session, request.run_id)
    if run is None:
        return {"status": "idle", "job_id": None}
    # `stopping` — это ещё активный прогон: текущий шот досчитывается,
    # после его завершения прогон уйдёт в `paused`.
    if run.status not in ("running", "stopping"):
        return {"status": run.status, "job_id": None}

    active = _running_item(session, run)
    if active is not None:
        job = _job_for(session, active)
        if job is not None and job.status == "completed":
            active.status = "completed"
            active.finished_at = _now()
        elif job is None or job.status in ("failed", "cancelled", "lease_expired"):
            active.status = "failed"
            active.error_code = "job_failed" if job is not None else "job_missing"
            active.finished_at = _now()
            if run.stop_on_error:
                _finish_run(session, run, "paused")
                run.finished_at = None
                session.commit()
                notify(
                    "Mary Studio: серия приостановлена",
                    f"Шот {active.order} завершился ошибкой ({active.error_code})",
                )
                return {
                    "status": "paused",
                    "reason": active.error_code,
                    "order": active.order,
                    "job_id": None,
                }
        else:
            session.commit()
            return {
                "status": "running",
                "order": active.order,
                "job_id": str(job.id),
                "job_status": job.status,
            }

    if run.status == "stopping":
        run.status = "paused"
        session.commit()
        return {"status": "paused", "reason": "stop_after_current", "job_id": None}

    item = session.scalar(
        select(SeriesItem)
        .where(SeriesItem.run_id == run.id, SeriesItem.status == "pending")
        .order_by(SeriesItem.order)
        .limit(1)
    )
    if item is None:
        _finish_run(session, run, "completed")
        counts = _counts(
            list(session.scalars(select(SeriesItem).where(SeriesItem.run_id == run.id)))
        )
        session.commit()
        notify(
            "Mary Studio: серия завершена",
            f"completed {counts['completed']}, failed {counts['failed']},"
            f" skipped {counts['skipped']}",
        )
        return {"status": "completed", "job_id": None, "counts": counts}

    shot = session.get(Shot, item.shot_id)
    reason = blocked_reason(session, shot) if shot is not None else "missing_shot"
    if reason is not None:
        item.status = "skipped"
        item.error_code = reason
        session.commit()
        return {
            "status": "skipped",
            "order": item.order,
            "job_id": None,
            "reason": reason,
        }

    active_job = session.scalar(
        select(Job).where(
            Job.shot_id == shot.id,
            Job.kind == "render_video",
            Job.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    if active_job is not None:
        session.commit()
        return {
            "status": "busy",
            "order": item.order,
            "job_id": str(active_job.id),
            "job_status": active_job.status,
        }

    key = f"series:{run.id}:{item.order}"
    job = session.scalar(select(Job).where(Job.idempotency_key == key))
    if job is None:
        job = Job(
            kind="render_video",
            shot_id=shot.id,
            status="pending",
            idempotency_key=key,
            payload={
                "shot_id": str(shot.id),
                "start_keyframe_artifact_id": str(shot.start_keyframe_artifact_id),
                "series_run_id": str(run.id),
                "series_order": item.order,
                "queued_at": _now().isoformat(),
            },
        )
        session.add(job)
        session.flush()
    item.status = "running"
    item.job_id = job.id
    item.started_at = _now()
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(status_code=409, detail="series job conflict") from error
    return {
        "status": "queued",
        "order": item.order,
        "job_id": str(job.id),
        "shot_id": str(shot.id),
    }
