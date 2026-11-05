"""Аудио шота: импорт, библиотека, waveform (WP-VOICE-02, DECISIONS §4.19).

Аудио живёт в существующей таблице `reference_assets` (`kind='uploaded'`,
`role='shot_audio'`) и привязывается к шоту через `shot_references`
(`purpose='other'`). Утверждение — существующий approve/reject референса.
Оригинал сохраняется без изменений; рядом в storage кладётся рабочая PCM-копия
48 кГц mono. Новых таблиц и второго storage нет.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.artifacts import read_body_with_limit
from app.api.deps import get_session, get_settings, get_store
from app.api.shots import require_shot, shot_project_id
from app.config import Settings
from app.models import ReferenceAsset, ShotReference
from app.shot_audio import (
    ENVELOPE_RATE_HZ,
    SHOT_AUDIO_ROLE,
    WORK_CHANNELS,
    WORK_SAMPLE_RATE,
    ShotAudioError,
    analyse_envelope,
    decode_envelope,
    probe_audio_details,
    waveform_peaks,
    write_work_wav,
)
from app.storage import BlobStore, StorageError

router = APIRouter(prefix="/api", tags=["shot-audio"])

AUDIO_MIME_SUFFIX = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/x-aac": ".aac",
}

WAVEFORM_MIN_BUCKETS = 16
WAVEFORM_MAX_BUCKETS = 2000
MAX_ORIGINAL_NAME = 200


class ShotAudioOut(BaseModel):
    reference_asset_id: uuid.UUID
    shot_id: uuid.UUID
    link_id: uuid.UUID
    status: str
    selected: bool
    sha256: str
    mime_type: str | None
    duration_s: float
    sample_rate: int | None
    channels: int | None
    codec: str | None
    format_name: str | None
    original_name: str | None
    content_url: str
    work_sample_rate: int
    work_channels: int
    envelope_rate_hz: int
    speech_ratio: float | None
    speech_segments: list[dict[str, float]]
    silence_segments: list[dict[str, float]]
    approved_at: datetime | None
    created_at: datetime


class WaveformOut(BaseModel):
    reference_asset_id: uuid.UUID
    duration_s: float
    buckets: int
    peaks: list[float]


def _normalize_mime(value: str | None) -> str:
    return (value or "").split(";")[0].strip().lower()


def _original_name(request: Request) -> str | None:
    raw = request.headers.get("x-original-name")
    if raw is None:
        return None
    name = raw.strip().replace("\\", "/").rsplit("/", 1)[-1]
    return name[:MAX_ORIGINAL_NAME] or None


def _audio_assets(session: Session, shot_id: uuid.UUID) -> list[tuple[ShotReference, ReferenceAsset]]:
    rows = session.execute(
        select(ShotReference, ReferenceAsset)
        .join(ReferenceAsset, ReferenceAsset.id == ShotReference.reference_asset_id)
        .where(
            ShotReference.shot_id == shot_id,
            ReferenceAsset.role == SHOT_AUDIO_ROLE,
        )
        .order_by(ShotReference.created_at.desc(), ShotReference.id.desc())
    ).all()
    return [(row[0], row[1]) for row in rows]


def selected_audio_id(session: Session, shot_id: uuid.UUID) -> uuid.UUID | None:
    """Выбранная запись — самый свежий утверждённый аудиоассет шота.

    Approve неизменяем (S15), поэтому замена записи — это approve новой: старая
    остаётся в библиотеке, «выбранной» становится последняя утверждённая.
    """

    rows = [
        asset
        for _link, asset in _audio_assets(session, shot_id)
        if asset.status == "approved"
    ]
    if not rows:
        return None
    rows.sort(
        key=lambda asset: (asset.approved_at or asset.created_at, asset.id),
        reverse=True,
    )
    return rows[0].id


def _asset_out(asset: ReferenceAsset, link: ShotReference, selected: bool) -> ShotAudioOut:
    metadata = asset.metadata_json or {}
    return ShotAudioOut(
        reference_asset_id=asset.id,
        shot_id=link.shot_id,
        link_id=link.id,
        status=asset.status,
        selected=selected,
        sha256=asset.sha256,
        mime_type=asset.mime_type,
        duration_s=float(metadata.get("duration_s") or 0.0),
        sample_rate=metadata.get("sample_rate"),
        channels=metadata.get("channels"),
        codec=metadata.get("codec"),
        format_name=metadata.get("format_name"),
        original_name=metadata.get("original_name"),
        content_url=f"/api/reference-assets/{asset.id}/content",
        work_sample_rate=int(metadata.get("work_sample_rate") or WORK_SAMPLE_RATE),
        work_channels=int(metadata.get("work_channels") or WORK_CHANNELS),
        envelope_rate_hz=int(metadata.get("envelope_rate_hz") or ENVELOPE_RATE_HZ),
        speech_ratio=metadata.get("speech_ratio"),
        speech_segments=metadata.get("speech_segments") or [],
        silence_segments=metadata.get("silence_segments") or [],
        approved_at=asset.approved_at,
        created_at=asset.created_at,
    )


def _ensure_link(
    session: Session, project_id: uuid.UUID, shot_id: uuid.UUID, asset_id: uuid.UUID
) -> ShotReference:
    link = session.scalar(
        select(ShotReference).where(
            ShotReference.shot_id == shot_id,
            ShotReference.reference_asset_id == asset_id,
            ShotReference.purpose == "other",
        )
    )
    if link is not None:
        return link
    link = ShotReference(
        project_id=project_id,
        shot_id=shot_id,
        reference_asset_id=asset_id,
        purpose="other",
    )
    session.add(link)
    session.flush()
    return link


def _prepare(body: bytes, suffix: str, settings: Settings) -> tuple[dict[str, object], bytes]:
    """ffprobe → рабочий WAV 48 кГц mono → огибающая. Оригинал только читается."""

    with tempfile.TemporaryDirectory(prefix="mary-shot-audio-") as workdir:
        source = Path(workdir) / f"source{suffix}"
        source.write_bytes(body)
        try:
            details = probe_audio_details(source)
            if details.duration_s > settings.shot_audio_max_duration_s:
                raise ShotAudioError(
                    "audio_too_long",
                    f"запись {details.duration_s:.1f} с, максимум "
                    f"{settings.shot_audio_max_duration_s:.0f} с",
                )
            work = Path(workdir) / "work.wav"
            write_work_wav(source, work)
            envelope = decode_envelope(work)
            work_bytes = work.read_bytes()
        except ShotAudioError as error:
            raise HTTPException(
                status_code=422,
                detail={"error": error.code, "message": error.message},
            ) from error

    analysis = analyse_envelope(envelope)
    metadata: dict[str, object] = {
        "source": "upload",
        "duration_s": details.duration_s,
        "sample_rate": details.sample_rate,
        "channels": details.channels,
        "codec": details.codec,
        "format_name": details.format_name,
        "work_sample_rate": WORK_SAMPLE_RATE,
        "work_channels": WORK_CHANNELS,
        "envelope_rate_hz": ENVELOPE_RATE_HZ,
        "gate": analysis["gate"],
        "peak_rms": analysis["peak_rms"],
        "envelope": analysis["envelope"],
        "speech_segments": analysis["speech_segments"],
        "silence_segments": analysis["silence_segments"],
        "speech_ratio": analysis["speech_ratio"],
        "imported_at": datetime.now(timezone.utc).isoformat(),
    }
    return metadata, work_bytes


@router.post(
    "/shots/{shot_id}/audio",
    response_model=ShotAudioOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_shot_audio(
    shot_id: uuid.UUID,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> ShotAudioOut:
    """Импорт готовой записи: WAV/MP3/M4A/AAC, оригинал + рабочая копия 48 кГц mono."""

    shot = require_shot(session, shot_id)
    project_id = shot_project_id(session, shot)

    mime_type = _normalize_mime(request.headers.get("content-type"))
    if mime_type not in AUDIO_MIME_SUFFIX:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "unsupported_audio_type",
                "message": f"неподдерживаемый тип аудио: {mime_type or 'unknown'}",
            },
        )

    body = await read_body_with_limit(request, settings.shot_audio_upload_max_bytes)
    if not body:
        raise HTTPException(status_code=422, detail={"error": "empty_body"})

    digest = hashlib.sha256(body).hexdigest()
    declared = (request.headers.get("x-content-sha256") or "").strip().lower()
    if declared and declared != digest:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "sha256_mismatch",
                "expected": declared,
                "actual": digest,
            },
        )

    duplicate = session.scalar(
        select(ReferenceAsset).where(
            ReferenceAsset.project_id == project_id,
            ReferenceAsset.sha256 == digest,
        )
    )
    if duplicate is not None:
        if duplicate.role != SHOT_AUDIO_ROLE:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "duplicate_reference",
                    "reference_asset_id": str(duplicate.id),
                },
            )
        link = _ensure_link(session, project_id, shot.id, duplicate.id)
        session.commit()
        response.status_code = status.HTTP_200_OK
        return _asset_out(
            duplicate, link, selected_audio_id(session, shot.id) == duplicate.id
        )

    metadata, work_bytes = _prepare(body, AUDIO_MIME_SUFFIX[mime_type], settings)
    work_blob = store.put_bytes(work_bytes, suffix=".wav")
    metadata["work_storage_key"] = work_blob.storage_key
    metadata["work_sha256"] = work_blob.sha256
    metadata["original_name"] = _original_name(request)

    original = store.put_bytes(body, suffix=AUDIO_MIME_SUFFIX[mime_type])
    asset = ReferenceAsset(
        project_id=project_id,
        kind="uploaded",
        status="draft",
        role=SHOT_AUDIO_ROLE,
        storage_key=original.storage_key,
        sha256=original.sha256,
        mime_type=mime_type,
        metadata_json=metadata,
    )
    session.add(asset)
    try:
        session.flush()
        link = _ensure_link(session, project_id, shot.id, asset.id)
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise HTTPException(
            status_code=409, detail={"error": "duplicate_reference"}
        ) from error
    session.refresh(asset)
    session.refresh(link)
    return _asset_out(asset, link, selected_audio_id(session, shot.id) == asset.id)


@router.get("/shots/{shot_id}/audio", response_model=list[ShotAudioOut])
def list_shot_audio(
    shot_id: uuid.UUID, session: Session = Depends(get_session)
) -> list[ShotAudioOut]:
    """Библиотека аудио шота: свежие сверху, выбранная помечена `selected`."""

    require_shot(session, shot_id)
    chosen = selected_audio_id(session, shot_id)
    return [
        _asset_out(asset, link, chosen == asset.id)
        for link, asset in _audio_assets(session, shot_id)
    ]


def _require_shot_audio(
    session: Session, shot_id: uuid.UUID, asset_id: uuid.UUID
) -> tuple[ShotReference, ReferenceAsset]:
    rows = _audio_assets(session, shot_id)
    for link, asset in rows:
        if asset.id == asset_id:
            return link, asset
    raise HTTPException(status_code=404, detail="shot audio not found")


def audio_metadata(asset: ReferenceAsset) -> dict[str, object]:
    return asset.metadata_json or {}


@router.get(
    "/shots/{shot_id}/audio/{asset_id}/waveform", response_model=WaveformOut
)
def shot_audio_waveform(
    shot_id: uuid.UUID,
    asset_id: uuid.UUID,
    buckets: int = Query(default=400, ge=WAVEFORM_MIN_BUCKETS, le=WAVEFORM_MAX_BUCKETS),
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
) -> WaveformOut:
    """Пики огибающей из metadata; при их отсутствии — пересчёт из рабочей копии."""

    _link, asset = _require_shot_audio(session, shot_id, asset_id)
    metadata = audio_metadata(asset)
    envelope = metadata.get("envelope")
    if not isinstance(envelope, list):
        work_key = metadata.get("work_storage_key")
        if not isinstance(work_key, str):
            raise HTTPException(status_code=409, detail={"error": "envelope_missing"})
        try:
            path = store.resolve(work_key)
        except StorageError as error:
            raise HTTPException(status_code=500, detail=f"invalid storage_key: {error}") from error
        if not path.is_file():
            raise HTTPException(status_code=409, detail={"error": "work_audio_missing"})
        try:
            envelope = decode_envelope(path)
        except ShotAudioError as error:
            raise HTTPException(
                status_code=422,
                detail={"error": error.code, "message": error.message},
            ) from error

    values = [float(value) for value in envelope if isinstance(value, (int, float))]
    peaks = waveform_peaks(values, buckets)
    return WaveformOut(
        reference_asset_id=asset.id,
        duration_s=float(metadata.get("duration_s") or len(values) / ENVELOPE_RATE_HZ),
        buckets=len(peaks),
        peaks=peaks,
    )
