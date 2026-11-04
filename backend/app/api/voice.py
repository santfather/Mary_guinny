"""WP-M6: голосовой образец персонажа как `reference_assets(role='voice')`.

Схема БД не меняется: аудио живёт в существующей таблице референсов, поэтому
approve/reject и immutable-правила (S15) работают без нового кода. Синтез речи
и клонирование голоса — вне этого пакета.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.artifacts import read_body_with_limit
from app.api.deps import get_session, get_settings, get_store
from app.api.schemas import ReferenceOut
from app.audio_timeline import AudioTimelineError, probe_audio
from app.config import Settings
from app.models import Character, ReferenceAsset
from app.storage import BlobStore

router = APIRouter(prefix="/api", tags=["characters"])

VOICE_ROLE = "voice"

VOICE_MIME_SUFFIX = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
}


def _normalize_mime(value: str | None) -> str:
    return (value or "").split(";")[0].strip().lower()


def _probe_duration(body: bytes, suffix: str, limit_s: float) -> float:
    """ffprobe по временному файлу: длительность и наличие аудиодорожки."""

    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    path = Path(handle.name)
    try:
        with handle:
            handle.write(body)
        try:
            duration, has_audio = probe_audio(path)
        except AudioTimelineError as error:
            raise HTTPException(status_code=422, detail=f"audio probe failed: {error}") from error
    finally:
        path.unlink(missing_ok=True)

    if not has_audio:
        raise HTTPException(status_code=422, detail="file has no audio track")
    if duration > limit_s:
        raise HTTPException(
            status_code=422,
            detail=f"voice sample is {duration:.2f} s, maximum is {limit_s:.0f} s",
        )
    return round(duration, 3)


@router.post(
    "/characters/{character_id}/voice",
    response_model=ReferenceOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_character_voice(
    character_id: uuid.UUID,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> ReferenceOut:
    character = session.get(Character, character_id)
    if character is None:
        raise HTTPException(status_code=404, detail="character not found")

    mime_type = _normalize_mime(request.headers.get("content-type"))
    if mime_type not in VOICE_MIME_SUFFIX:
        raise HTTPException(
            status_code=422,
            detail=f"unsupported audio type: {mime_type or 'unknown'}",
        )

    body = await read_body_with_limit(request, settings.voice_upload_max_bytes)
    if not body:
        raise HTTPException(status_code=422, detail="empty body")

    digest = hashlib.sha256(body).hexdigest()
    existing = session.scalar(
        select(ReferenceAsset).where(
            ReferenceAsset.project_id == character.project_id,
            ReferenceAsset.sha256 == digest,
        )
    )
    if existing is not None:
        if existing.character_id == character.id and existing.role == VOICE_ROLE:
            response.status_code = status.HTTP_200_OK
            return ReferenceOut.from_asset(existing)
        raise HTTPException(
            status_code=409,
            detail={
                "error": "duplicate_reference",
                "reference_asset_id": str(existing.id),
            },
        )

    suffix = VOICE_MIME_SUFFIX[mime_type]
    duration = _probe_duration(body, suffix, settings.voice_max_duration_s)

    blob = store.put_bytes(body, suffix=suffix)
    asset = ReferenceAsset(
        project_id=character.project_id,
        kind="character_reference",
        character_id=character.id,
        status="draft",
        role=VOICE_ROLE,
        storage_key=blob.storage_key,
        sha256=blob.sha256,
        mime_type=mime_type,
        metadata_json={"source": "upload", "duration_s": duration},
    )
    session.add(asset)
    try:
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail={"error": "duplicate_reference"}
        ) from error
    session.refresh(asset)
    return ReferenceOut.from_asset(asset)
