from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WorkerClaimRequest(BaseModel):
    worker_name: str = Field(min_length=1, max_length=128)
    kinds: list[str] = Field(
        default_factory=lambda: ["render_video"], min_length=1, max_length=8
    )
    lease_seconds: int | None = Field(default=None, ge=5, le=3600)


class WorkerClaimOut(BaseModel):
    job_id: uuid.UUID
    attempt_id: uuid.UUID
    worker_id: uuid.UUID
    kind: str
    status: str
    attempts: int
    max_attempts: int
    lease_until: datetime
    workflow_id: str
    workflow_version: str | None
    inputs: dict[str, Any]
    output_prefix: str


class WorkerHeartbeatRequest(BaseModel):
    worker_name: str = Field(min_length=1, max_length=128)
    progress: float | None = Field(default=None, ge=0, le=1)
    stage: str | None = Field(default=None, max_length=64)
    lease_seconds: int | None = Field(default=None, ge=5, le=3600)


class WorkerHeartbeatOut(BaseModel):
    job_id: uuid.UUID
    status: str
    sequence: int
    lease_until: datetime


class WorkerExternalRequest(BaseModel):
    """Внешний id рендера (ComfyUI prompt_id) для восстановления после рестарта."""

    worker_name: str = Field(min_length=1, max_length=128)
    external_id: str = Field(min_length=1, max_length=128)


class WorkerExternalOut(BaseModel):
    job_id: uuid.UUID
    status: str
    external_id: str


class WorkerCompleteRequest(BaseModel):
    worker_name: str = Field(min_length=1, max_length=128)
    workflow_version: str | None = Field(default=None, max_length=128)
    model_hash: str | None = Field(default=None, max_length=128)
    seed: int | None = None
    native_fps: float | None = Field(default=None, ge=0)
    duration_s: float | None = Field(default=None, ge=0)
    peak_mem_mb: int | None = Field(default=None, ge=0)
    # Фактические параметры рендера (ширина/высота, aspect, cfg, snapshot
    # workflow) — дописываются в `render_attempts.parameters`.
    parameters: dict[str, Any] | None = None


class WorkerCompleteOut(BaseModel):
    job_id: uuid.UUID
    status: str
    attempt_id: uuid.UUID
    artifact_ids: list[uuid.UUID]


class WorkerFailRequest(BaseModel):
    worker_name: str = Field(min_length=1, max_length=128)
    error_code: str = Field(min_length=1, max_length=64)
    retryable: bool = False
    message: str | None = Field(default=None, max_length=500)


class WorkerFailOut(BaseModel):
    job_id: uuid.UUID
    status: str
    attempt_id: uuid.UUID


class WorkerResumeRequest(BaseModel):
    worker_name: str = Field(min_length=1, max_length=128)
    job_ids: list[uuid.UUID] | None = None


class WorkerResumeJobOut(BaseModel):
    job_id: uuid.UUID
    status: str
    attempt_id: uuid.UUID | None
    external_id: str | None
    lease_until: datetime | None


class WorkerResumeOut(BaseModel):
    worker_id: uuid.UUID
    jobs: list[WorkerResumeJobOut]


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: str
    shot_id: uuid.UUID | None
    scene_id: uuid.UUID | None
    attempts: int
    max_attempts: int
    error_code: str | None
    lease_owner: str | None
    lease_until: datetime | None
    run_after: datetime | None
    created_at: datetime
    updated_at: datetime


class JobEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    event: str
    stage: str | None
    progress: float | None
    attempt_id: uuid.UUID | None
    payload: dict[str, Any]
    created_at: datetime


class JobDetailOut(JobOut):
    last_event: JobEventOut | None = None
