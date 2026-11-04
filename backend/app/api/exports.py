"""Сборка и список экспортов проекта (WP-M2).

Экспорт синхронный: очередь и worker не участвуют. Результат — обычный
`Artifact` с `source='export'`; провенанс (клипы, таймкоды, аудио) хранится в
`artifacts.metadata` (DECISIONS §4.8). Исходные блобы только читаются.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_store, require_project
from app.api.shots import shot_project_id
from app.assembly import (
    TARGET_FPS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    AssemblyError,
    ClipSource,
    assemble_export,
    ffmpeg_version,
    prepare_clip,
)
from app.models import Artifact, RenderAttempt, Shot
from app.storage import BlobStore, StorageError

router = APIRouter(tags=["exports"])

MAX_EXPORT_CLIPS = 30
EXPORT_MIME = "video/mp4"
EXPORT_KIND = "export_video"


class ExportClipIn(BaseModel):
    shot_id: uuid.UUID
    attempt_id: uuid.UUID
    trim_start_s: float | None = Field(default=None, ge=0)
    trim_end_s: float | None = Field(default=None, gt=0)


class ExportCreate(BaseModel):
    clips: list[ExportClipIn] = Field(min_length=1, max_length=MAX_EXPORT_CLIPS)
    audio_artifact_id: uuid.UUID | None = None


class ExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    artifact_id: uuid.UUID
    content_url: str
    sha256: str
    bytes: int
    width: int
    height: int
    fps: int
    duration_s: float
    clip_count: int
    audio_artifact_id: uuid.UUID | None
    created_at: datetime


def _content_url(artifact_id: uuid.UUID) -> str:
    return f"/api/artifacts/{artifact_id}/content"


def _artifact_path(store: BlobStore, artifact: Artifact) -> Path:
    try:
        path = store.resolve(artifact.storage_key)
    except StorageError as error:
        raise HTTPException(
            status_code=500, detail=f"invalid storage_key: {error}"
        ) from error
    if not path.is_file():
        raise HTTPException(status_code=409, detail="artifact content is missing")
    return path


def _attempt_artifact(
    session: Session, project_id: uuid.UUID, clip: ExportClipIn
) -> tuple[Shot, RenderAttempt, Artifact]:
    shot = session.get(Shot, clip.shot_id)
    if shot is None:
        raise HTTPException(status_code=404, detail="shot not found")
    if shot_project_id(session, shot) != project_id:
        raise HTTPException(status_code=409, detail="shot belongs to another project")
    attempt = session.get(RenderAttempt, clip.attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="render attempt not found")
    if attempt.shot_id != shot.id:
        raise HTTPException(status_code=409, detail="attempt does not belong to shot")
    if attempt.kind != "video":
        raise HTTPException(status_code=409, detail="attempt is not a video attempt")
    if attempt.status != "completed":
        raise HTTPException(status_code=409, detail="attempt is not completed")
    artifact = session.scalar(
        select(Artifact)
        .where(Artifact.attempt_id == attempt.id)
        .order_by(Artifact.created_at.desc())
        .limit(1)
    )
    if artifact is None:
        raise HTTPException(status_code=409, detail="attempt artifact is missing")
    if artifact.mime_type != EXPORT_MIME:
        raise HTTPException(status_code=409, detail="attempt artifact is not an MP4")
    return shot, attempt, artifact


def _audio_artifact(session: Session, artifact_id: uuid.UUID) -> Artifact:
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="audio artifact not found")
    if not artifact.mime_type.startswith("audio/"):
        raise HTTPException(status_code=409, detail="artifact is not audio")
    return artifact


def _export_out(artifact: Artifact, metadata: dict[str, object] | None = None) -> ExportOut:
    data = artifact.metadata_json if metadata is None else metadata
    data = data or {}
    clips = data.get("clips")
    audio = data.get("audio_artifact_id")
    return ExportOut(
        artifact_id=artifact.id,
        content_url=_content_url(artifact.id),
        sha256=artifact.sha256,
        bytes=artifact.bytes,
        width=int(data.get("width") or TARGET_WIDTH),
        height=int(data.get("height") or TARGET_HEIGHT),
        fps=int(data.get("fps") or TARGET_FPS),
        duration_s=float(data.get("duration_s") or 0.0),
        clip_count=len(clips) if isinstance(clips, list) else 0,
        audio_artifact_id=uuid.UUID(str(audio)) if audio else None,
        created_at=artifact.created_at,
    )


@router.post(
    "/api/projects/{project_id}/exports",
    response_model=ExportOut,
    status_code=status.HTTP_201_CREATED,
)
def create_export(
    project_id: uuid.UUID,
    payload: ExportCreate,
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
) -> ExportOut:
    """Собирает 9:16 MP4 из клипов; исходные MP4 не изменяются."""

    require_project(session, project_id)
    resolved = [
        (clip, *_attempt_artifact(session, project_id, clip)) for clip in payload.clips
    ]
    audio = (
        _audio_artifact(session, payload.audio_artifact_id)
        if payload.audio_artifact_id is not None
        else None
    )

    with tempfile.TemporaryDirectory(prefix="mary-export-") as workdir:
        sources: list[ClipSource] = []
        for clip, _shot, _attempt, artifact in resolved:
            path = _artifact_path(store, artifact)
            try:
                sources.append(
                    prepare_clip(
                        path,
                        trim_start_s=clip.trim_start_s,
                        trim_end_s=clip.trim_end_s,
                    )
                )
            except AssemblyError as error:
                raise HTTPException(
                    status_code=422,
                    detail={"error": error.code, "message": str(error)},
                ) from error

        audio_path = _artifact_path(store, audio) if audio is not None else None
        output = Path(workdir) / "export.mp4"
        try:
            info = assemble_export(sources, audio_path, output)
        except AssemblyError as error:
            raise HTTPException(
                status_code=500,
                detail={"error": error.code, "message": str(error)},
            ) from error
        blob = store.put_file(output, suffix=".mp4")

    metadata: dict[str, object] = {
        "project_id": str(project_id),
        "width": TARGET_WIDTH,
        "height": TARGET_HEIGHT,
        "fps": TARGET_FPS,
        "duration_s": round(info.duration_s, 3),
        "audio_artifact_id": str(audio.id) if audio is not None else None,
        "ffmpeg_version": ffmpeg_version(),
        "clips": [
            {
                "shot_id": str(shot.id),
                "attempt_id": str(attempt.id),
                "artifact_id": str(artifact.id),
                "sha256": artifact.sha256,
                "trim_start_s": source.trim_start_s,
                "trim_end_s": source.trim_end_s,
            }
            for (_clip, shot, attempt, artifact), source in zip(resolved, sources)
        ],
    }

    export = Artifact(
        source="export",
        kind=EXPORT_KIND,
        storage_key=blob.storage_key,
        sha256=blob.sha256,
        bytes=blob.size,
        mime_type=EXPORT_MIME,
        metadata_json=metadata,
    )
    session.add(export)
    session.commit()
    session.refresh(export)
    return _export_out(export, metadata)


@router.get("/api/projects/{project_id}/exports", response_model=list[ExportOut])
def list_exports(
    project_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[ExportOut]:
    """Экспорты проекта, свежие первыми."""

    require_project(session, project_id)
    artifacts = session.scalars(
        select(Artifact)
        .where(
            Artifact.source == "export",
            Artifact.metadata_json["project_id"].astext == str(project_id),
        )
        .order_by(Artifact.created_at.desc())
        .limit(limit)
    )
    return [_export_out(artifact) for artifact in artifacts]
