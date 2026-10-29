"""Worker API: pull-модель очереди с lease и heartbeat (WP-06).

Контракт: `docs/ARCHITECTURE.md` §5.1–5.3, §6.1, §13.3. Все эндпоинты требуют
токен воркера (D7). Источник истины о статусе job — таблица `jobs`, журнал
событий пишется в `events`.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.artifacts import ArtifactOut, read_body_with_limit
from app.api.deps import get_session
from app.api.worker_schemas import (
    WorkerClaimOut,
    WorkerClaimRequest,
    WorkerCompleteOut,
    WorkerCompleteRequest,
    WorkerFailOut,
    WorkerFailRequest,
    WorkerHeartbeatOut,
    WorkerHeartbeatRequest,
    WorkerResumeJobOut,
    WorkerResumeOut,
    WorkerResumeRequest,
)
from app.models import (
    Artifact,
    Event,
    Job,
    PromptRevision,
    RenderAttempt,
    Scene,
    Shot,
    Worker,
)
from app.storage import BlobStore
from app.video_probe import VideoProbeError, probe_mp4

# Статусы, в которых воркер ещё владеет job по lease.
ACTIVE_LEASE_STATUSES = ("leased", "running")
# Статусы, из которых job можно завершить или провалить.
FINALIZABLE_STATUSES = (*ACTIVE_LEASE_STATUSES, "lease_expired")

_ATTEMPT_KIND = {
    "render_video": "video",
    "postprocess": "postprocess",
    "tts": "postprocess",
}


def require_worker_token(
    request: Request,
    authorization: str | None = Header(default=None),
    x_worker_token: str | None = Header(default=None, alias="X-Worker-Token"),
) -> None:
    expected = request.app.state.settings.worker_token
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="worker API is disabled: MARY_WORKER_TOKEN is empty",
        )
    provided = x_worker_token
    if provided is None and authorization:
        scheme, separator, value = authorization.partition(" ")
        if separator and scheme.lower() == "bearer":
            provided = value.strip()
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid worker token",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(
    prefix="/api/worker",
    tags=["worker"],
    dependencies=[Depends(require_worker_token)],
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _append_event(
    session: Session,
    *,
    job_id: uuid.UUID,
    event: str,
    attempt_id: uuid.UUID | None = None,
    stage: str | None = None,
    progress: float | None = None,
    payload: dict[str, object] | None = None,
) -> Event:
    """Пишет событие с очередным `sequence`.

    Вызывается только при удержании блокировки строки job, поэтому вычисление
    `max(sequence) + 1` не создаёт гонок.
    """

    sequence = (
        session.scalar(
            select(func.coalesce(func.max(Event.sequence), 0)).where(
                Event.job_id == job_id
            )
        )
        + 1
    )
    row = Event(
        job_id=job_id,
        attempt_id=attempt_id,
        event=event,
        stage=stage,
        progress=Decimal(str(progress)) if progress is not None else None,
        sequence=sequence,
        payload=payload or {},
    )
    session.add(row)
    session.flush()
    return row


def _register_worker(session: Session, name: str) -> Worker:
    worker = session.scalar(select(Worker).where(Worker.name == name))
    if worker is None:
        worker = Worker(name=name, status="active", capabilities={})
        session.add(worker)
    else:
        worker.status = "active"
    worker.last_seen_at = _now()
    session.flush()
    return worker


def _expire_leases(session: Session) -> int:
    """Переводит просроченные lease в `lease_expired` без перезапуска job."""

    expired = list(
        session.scalars(
            select(Job)
            .where(
                Job.status.in_(ACTIVE_LEASE_STATUSES),
                Job.lease_until.is_not(None),
                Job.lease_until < func.now(),
            )
            .with_for_update(skip_locked=True)
        )
    )
    for job in expired:
        job.status = "lease_expired"
        job.lease_until = None
        _append_event(
            session,
            job_id=job.id,
            event="lease_expired",
            payload={"worker_name": job.lease_owner},
        )
    return len(expired)


def _lock_job(session: Session, job_id: uuid.UUID) -> Job:
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _require_lease(job: Job, worker_name: str) -> None:
    if job.lease_owner != worker_name:
        raise HTTPException(
            status_code=409,
            detail={"error": "lease_not_owned", "lease_owner": job.lease_owner},
        )


def _active_attempt(session: Session, job_id: uuid.UUID) -> RenderAttempt:
    attempt = session.scalar(
        select(RenderAttempt)
        .where(RenderAttempt.job_id == job_id, RenderAttempt.status == "running")
        .order_by(RenderAttempt.created_at.desc(), RenderAttempt.id.desc())
        .limit(1)
    )
    if attempt is None:
        raise HTTPException(status_code=409, detail="job has no running attempt")
    return attempt


def _lease_until(job: Job) -> datetime:
    if job.lease_until is None:
        raise HTTPException(status_code=409, detail="job has no lease")
    return job.lease_until


def _job_inputs(session: Session, job: Job) -> dict[str, object]:
    payload = job.payload or {}
    shot = session.get(Shot, job.shot_id) if job.shot_id is not None else None
    inputs: dict[str, object] = {
        "frames": payload.get(
            "frames", shot.target_duration_frames if shot is not None else None
        )
        or 73,
        "fps": payload.get(
            "fps", float(shot.timeline_fps) if shot is not None and shot.timeline_fps else None
        )
        or 24,
        "seed": payload.get("seed"),
    }
    if payload.get("prompt") is not None:
        inputs["prompt"] = payload["prompt"]
    elif job.shot_id is not None:
        # ARCHITECTURE §5.2: prompt входит в inputs. Shot-промпт хранится
        # ревизиями, актуальна последняя revision с типом `motion`.
        revision = session.scalar(
            select(PromptRevision)
            .where(
                PromptRevision.shot_id == job.shot_id,
                PromptRevision.prompt_type == "motion",
            )
            .order_by(PromptRevision.version.desc())
            .limit(1)
        )
        if revision is not None:
            inputs["prompt"] = revision.prompt
            shot_key = (revision.parameters_json or {}).get("shot_key")
            if isinstance(shot_key, str) and shot_key:
                inputs["shot_key"] = shot_key

    artifact_id = payload.get("start_keyframe_artifact_id")
    if artifact_id is not None:
        artifact = session.get(Artifact, uuid.UUID(str(artifact_id)))
        if artifact is None:
            raise HTTPException(
                status_code=409, detail="start keyframe artifact is missing"
            )
        inputs["start_image"] = {
            "artifact_id": str(artifact.id),
            "sha256": artifact.sha256,
            "content_url": f"/api/artifacts/{artifact.id}/content",
        }
    return inputs


def _output_prefix(session: Session, job: Job, attempt_id: uuid.UUID) -> str:
    if job.shot_id is not None:
        shot = session.get(Shot, job.shot_id)
        if shot is None:
            raise HTTPException(status_code=409, detail="job shot is missing")
        project_id = session.scalar(
            select(Scene.project_id).where(Scene.id == shot.scene_id)
        )
        if project_id is None:
            raise HTTPException(status_code=409, detail="shot scene is missing")
        return f"projects/{project_id}/shots/{shot.id}/attempts/{attempt_id}/"
    if job.scene_id is not None:
        scene = session.get(Scene, job.scene_id)
        if scene is None:
            raise HTTPException(status_code=409, detail="job scene is missing")
        return f"projects/{scene.project_id}/scenes/{scene.id}/attempts/{attempt_id}/"
    raise HTTPException(status_code=409, detail="job has no target")


_CLAIM_SQL = text(
    """
WITH next AS (
    SELECT j.id
    FROM jobs j
    WHERE j.status IN ('pending', 'retry_wait')
      AND (j.run_after IS NULL OR j.run_after <= now())
      AND j.kind = ANY(CAST(:kinds AS text[]))
      AND j.attempts < j.max_attempts
      AND NOT EXISTS (
          SELECT 1
          FROM job_dependencies d
          JOIN jobs p ON p.id = d.depends_on_job_id
          WHERE d.job_id = j.id AND p.status <> 'completed')
    ORDER BY j.priority DESC, j.created_at
    FOR UPDATE OF j SKIP LOCKED
    LIMIT 1)
UPDATE jobs
SET status = 'leased',
    lease_owner = :worker_name,
    lease_until = now() + make_interval(secs => CAST(:lease_seconds AS double precision)),
    heartbeat_at = now(),
    attempts = attempts + 1,
    updated_at = now()
FROM next
WHERE jobs.id = next.id
RETURNING jobs.id
"""
)


@router.post("/claim", response_model=WorkerClaimOut | None)
def claim(
    payload: WorkerClaimRequest, session: Session = Depends(get_session)
) -> WorkerClaimOut | None:
    """Забирает одну готовую job; при отсутствии задач возвращает `null`."""

    _expire_leases(session)
    worker = _register_worker(session, payload.worker_name)
    lease_seconds = payload.lease_seconds or 60

    job_id = session.scalar(
        _CLAIM_SQL,
        {
            "kinds": list(payload.kinds),
            "worker_name": payload.worker_name,
            "lease_seconds": lease_seconds,
        },
    )
    if job_id is None:
        session.commit()
        return None

    job = session.get(Job, job_id)
    if job is None:
        session.rollback()
        raise HTTPException(status_code=409, detail="claimed job disappeared")
    if job.shot_id is None:
        # WP-06 поддерживает только шотовые job; сценовые — отдельный пакет.
        job.status = "failed"
        job.error_code = "unsupported_job_target"
        job.lease_until = None
        _append_event(
            session,
            job_id=job.id,
            event="failed",
            payload={"error_code": "unsupported_job_target"},
        )
        session.commit()
        raise HTTPException(
            status_code=409, detail="only shot jobs are supported by the worker API"
        )

    attempt = RenderAttempt(
        shot_id=job.shot_id,
        job_id=job.id,
        kind=_ATTEMPT_KIND.get(job.kind, "video"),
        status="running",
        worker_id=worker.id,
        input_artifact_ids=(
            [str(job.payload["start_keyframe_artifact_id"])]
            if job.payload and job.payload.get("start_keyframe_artifact_id")
            else None
        ),
        parameters={"worker_name": payload.worker_name, "job_attempt": job.attempts},
    )
    session.add(attempt)
    session.flush()

    _append_event(
        session,
        job_id=job.id,
        attempt_id=attempt.id,
        event="claimed",
        payload={
            "worker_name": payload.worker_name,
            "attempt": job.attempts,
            "lease_seconds": lease_seconds,
        },
    )
    session.commit()
    session.refresh(job)

    return WorkerClaimOut(
        job_id=job.id,
        attempt_id=attempt.id,
        worker_id=worker.id,
        kind=job.kind,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        lease_until=_lease_until(job),
        workflow_id=(job.payload or {}).get("workflow_id", "fake_i2v_v1"),
        workflow_version=(job.payload or {}).get("workflow_version"),
        inputs=_job_inputs(session, job),
        output_prefix=_output_prefix(session, job, attempt.id),
    )


@router.post("/jobs/{job_id}/heartbeat", response_model=WorkerHeartbeatOut)
def heartbeat(
    job_id: uuid.UUID,
    payload: WorkerHeartbeatRequest,
    session: Session = Depends(get_session),
) -> WorkerHeartbeatOut:
    job = _lock_job(session, job_id)
    _require_lease(job, payload.worker_name)
    if job.status not in FINALIZABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={"error": "job_not_active", "status": job.status},
        )

    lease_seconds = payload.lease_seconds or 60
    job.status = "running"
    job.lease_until = _now() + timedelta(seconds=lease_seconds)
    job.heartbeat_at = _now()
    attempt = _active_attempt(session, job.id)
    event = _append_event(
        session,
        job_id=job.id,
        attempt_id=attempt.id,
        event="progress",
        stage=payload.stage,
        progress=payload.progress,
    )
    session.commit()
    session.refresh(job)
    return WorkerHeartbeatOut(
        job_id=job.id,
        status=job.status,
        sequence=event.sequence,
        lease_until=_lease_until(job),
    )


@router.post("/jobs/{job_id}/artifacts", response_model=ArtifactOut, status_code=201)
async def upload_artifact(
    job_id: uuid.UUID,
    request: Request,
    worker_name: str = Query(..., min_length=1, max_length=128),
    kind: str = Query(..., min_length=1, max_length=64),
    x_content_sha256: str = Header(..., alias="X-Content-SHA256"),
    content_type: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> ArtifactOut:
    """Загрузка результата воркера: sha256 сверяется, MP4 проверяется по структуре."""

    settings = request.app.state.settings
    job = _lock_job(session, job_id)
    _require_lease(job, worker_name)
    if job.status not in ACTIVE_LEASE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={"error": "job_not_active", "status": job.status},
        )
    attempt = _active_attempt(session, job.id)
    # Блокировка строки job удерживается до commit: параллельная загрузка
    # того же хэша не создаст дубль, а claim этого job не начнётся заново.
    body = await read_body_with_limit(request, settings.worker_max_artifact_bytes)
    if not body:
        raise HTTPException(status_code=422, detail="empty body")
    digest = hashlib.sha256(body).hexdigest()
    if digest != x_content_sha256.strip().lower():
        raise HTTPException(
            status_code=422,
            detail={
                "error": "sha256_mismatch",
                "expected": x_content_sha256.strip().lower(),
                "actual": digest,
            },
        )

    mime_type = (content_type or "application/octet-stream").split(";")[0].strip()
    if mime_type == "video/mp4":
        try:
            probe_mp4(body)
        except VideoProbeError as error:
            raise HTTPException(
                status_code=422,
                detail={"error": "invalid_mp4", "detail": str(error)},
            ) from error

    existing = session.scalar(
        select(Artifact).where(
            Artifact.attempt_id == attempt.id,
            Artifact.sha256 == digest,
            Artifact.kind == kind,
        )
    )
    if existing is not None:
        return ArtifactOut.model_validate(existing)

    store = BlobStore(settings.storage_root)
    suffix = {
        "video/mp4": ".mp4",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "audio/wav": ".wav",
        "audio/mpeg": ".mp3",
    }.get(mime_type, "")
    blob = store.put_bytes(body, suffix=suffix)
    artifact = Artifact(
        attempt_id=attempt.id,
        source="attempt",
        kind=kind,
        storage_key=blob.storage_key,
        sha256=blob.sha256,
        bytes=blob.size,
        mime_type=mime_type,
    )
    session.add(artifact)
    _append_event(
        session,
        job_id=job.id,
        attempt_id=attempt.id,
        event="artifact_uploaded",
        payload={
            "artifact_id": str(artifact.id),
            "sha256": blob.sha256,
            "bytes": blob.size,
            "mime_type": mime_type,
        },
    )
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="artifact upload conflict"
        ) from error
    session.refresh(artifact)
    return ArtifactOut.model_validate(artifact)


@router.post("/jobs/{job_id}/complete", response_model=WorkerCompleteOut)
def complete(
    job_id: uuid.UUID,
    payload: WorkerCompleteRequest,
    session: Session = Depends(get_session),
) -> WorkerCompleteOut:
    job = _lock_job(session, job_id)
    _require_lease(job, payload.worker_name)
    if job.status not in FINALIZABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={"error": "job_not_active", "status": job.status},
        )
    attempt = _active_attempt(session, job.id)
    artifacts = list(
        session.scalars(select(Artifact).where(Artifact.attempt_id == attempt.id))
    )
    if not artifacts:
        raise HTTPException(status_code=409, detail="artifact is required")

    attempt.status = "completed"
    attempt.workflow_version = payload.workflow_version
    attempt.model_hash = payload.model_hash
    attempt.seed = payload.seed
    attempt.native_fps = (
        Decimal(str(payload.native_fps)) if payload.native_fps is not None else None
    )
    attempt.duration_s = (
        Decimal(str(payload.duration_s)) if payload.duration_s is not None else None
    )
    attempt.peak_mem_mb = payload.peak_mem_mb
    if payload.parameters:
        attempt.parameters = {**(attempt.parameters or {}), **payload.parameters}

    job.status = "completed"
    job.error_code = None
    job.lease_until = None
    job.heartbeat_at = _now()
    artifact_ids = [artifact.id for artifact in artifacts]
    _append_event(
        session,
        job_id=job.id,
        attempt_id=attempt.id,
        event="completed",
        payload={"artifact_ids": [str(value) for value in artifact_ids]},
    )
    session.commit()
    return WorkerCompleteOut(
        job_id=job.id,
        status=job.status,
        attempt_id=attempt.id,
        artifact_ids=artifact_ids,
    )


@router.post("/jobs/{job_id}/fail", response_model=WorkerFailOut)
def fail(
    job_id: uuid.UUID,
    payload: WorkerFailRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> WorkerFailOut:
    job = _lock_job(session, job_id)
    _require_lease(job, payload.worker_name)
    if job.status not in FINALIZABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail={"error": "job_not_active", "status": job.status},
        )
    attempt = _active_attempt(session, job.id)
    attempt.status = "failed"

    backoff_s = request.app.state.settings.worker_retry_backoff_s
    retry = payload.retryable and job.attempts < job.max_attempts
    job.error_code = payload.error_code
    job.lease_until = None
    job.heartbeat_at = _now()
    if retry:
        job.status = "retry_wait"
        job.run_after = _now() + timedelta(seconds=backoff_s * max(1, job.attempts))
    else:
        job.status = "failed"
        job.run_after = None
    _append_event(
        session,
        job_id=job.id,
        attempt_id=attempt.id,
        event="failed",
        payload={
            "error_code": payload.error_code,
            "retryable": payload.retryable,
            "retry_scheduled": retry,
            "message": payload.message,
        },
    )
    session.commit()
    return WorkerFailOut(job_id=job.id, status=job.status, attempt_id=attempt.id)


@router.post("/resume", response_model=WorkerResumeOut)
def resume(
    payload: WorkerResumeRequest, session: Session = Depends(get_session)
) -> WorkerResumeOut:
    """После рестарта воркер сообщает, какие его job ещё живы.

    Статус job не меняется автоматически: воркер обязан прислать
    `heartbeat`/`complete`/`fail` по каждой задаче.
    """

    worker = _register_worker(session, payload.worker_name)
    jobs = list(
        session.scalars(
            select(Job)
            .where(
                Job.lease_owner == payload.worker_name,
                Job.status.in_(FINALIZABLE_STATUSES),
            )
            .order_by(Job.created_at)
        )
    )
    reported = set(payload.job_ids or [])
    result: list[WorkerResumeJobOut] = []
    for job in jobs:
        attempt = session.scalar(
            select(RenderAttempt)
            .where(RenderAttempt.job_id == job.id)
            .order_by(RenderAttempt.created_at.desc(), RenderAttempt.id.desc())
            .limit(1)
        )
        _append_event(
            session,
            job_id=job.id,
            attempt_id=attempt.id if attempt is not None else None,
            event="resumed",
            payload={
                "worker_name": payload.worker_name,
                "reported": str(job.id) in {str(value) for value in reported},
            },
        )
        result.append(
            WorkerResumeJobOut(
                job_id=job.id,
                status=job.status,
                attempt_id=attempt.id if attempt is not None else None,
                external_id=job.external_id,
                lease_until=job.lease_until,
            )
        )
    session.commit()
    return WorkerResumeOut(worker_id=worker.id, jobs=result)
