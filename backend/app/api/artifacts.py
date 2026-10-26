from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Artifact
from app.storage import BlobStore, StorageError

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])

MAX_UPLOAD_BYTES = 256 * 1024 * 1024

_MIME_SUFFIX = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "application/json": ".json",
    "text/plain": ".txt",
}


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source: str
    kind: str
    storage_key: str
    sha256: str
    bytes: int
    mime_type: str


def _store(request: Request) -> BlobStore:
    return BlobStore(request.app.state.settings.storage_root)


def _session(request: Request) -> Session:
    return Session(request.app.state.engine)


@router.post("", response_model=ArtifactOut, status_code=status.HTTP_201_CREATED)
async def upload_artifact(
    request: Request,
    kind: str = Query(..., min_length=1, max_length=64),
    x_content_sha256: str = Header(..., alias="X-Content-SHA256"),
    content_type: str | None = Header(default=None),
) -> ArtifactOut:
    """Загрузка артефакта: сервер пересчитывает sha256 и не доверяет заголовку."""

    body = await request.body()
    if not body:
        raise HTTPException(status_code=422, detail="empty body")
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="artifact is too large")
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
    store = _store(request)
    with _session(request) as session:
        existing = session.scalar(
            select(Artifact).where(
                Artifact.sha256 == digest,
                Artifact.kind == kind,
                Artifact.source == "upload",
            )
        )
        if existing is not None:
            return ArtifactOut.model_validate(existing)

        blob = store.put_bytes(body, suffix=_MIME_SUFFIX.get(mime_type, ""))
        artifact = Artifact(
            source="upload",
            kind=kind,
            storage_key=blob.storage_key,
            sha256=blob.sha256,
            bytes=blob.size,
            mime_type=mime_type,
        )
        session.add(artifact)
        session.commit()
        session.refresh(artifact)
        return ArtifactOut.model_validate(artifact)


@router.get("/{artifact_id}", response_model=ArtifactOut)
def get_artifact(artifact_id: uuid.UUID, request: Request) -> ArtifactOut:
    with _session(request) as session:
        artifact = session.get(Artifact, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return ArtifactOut.model_validate(artifact)


@router.get("/{artifact_id}/content")
def download_artifact(artifact_id: uuid.UUID, request: Request) -> FileResponse:
    with _session(request) as session:
        artifact = session.get(Artifact, artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        storage_key = artifact.storage_key
        mime_type = artifact.mime_type

    store = _store(request)
    try:
        path = store.resolve(storage_key)
    except StorageError as error:
        raise HTTPException(status_code=500, detail=f"invalid storage_key: {error}") from error
    if not path.is_file():
        raise HTTPException(status_code=404, detail="artifact content is missing")
    return FileResponse(path, media_type=mime_type)
