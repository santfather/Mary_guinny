"""Talking Preview: `mouth_animation_mvp` (legacy) и `viseme_frame_blend_v1` (WP-VOICE-06).

Генерация локальная и синхронная (как экспорт и рендер композиции): GPU, LTX,
ComfyUI и TTS не участвуют. Результат — обычная видео-попытка шота, поэтому
review идёт существующими `approve`/`reject`. Автоматического утверждения нет.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_settings, get_store
from app.api.mouth_sources import (
    SourceImage,
    region_from_calibration,
    resolve_source_image,
)
from app.api.shot_audio import selected_audio_id
from app.api.shots import require_shot, shot_project_id
from app.config import Settings
from app.models import (
    Artifact,
    Job,
    MouthCalibration,
    ReferenceAsset,
    RenderAttempt,
    ShotReference,
)
from app.mouth_animation import (
    LIMITATION,
    MODE,
    RESULT_KIND,
    RESULT_MIME,
    WORKFLOW_VERSION,
    MouthAnimationError,
    preview_parameters,
    render_talking_preview,
)
from app import rhubarb
from app.shot_audio import ENVELOPE_RATE_HZ, SHOT_AUDIO_ROLE, decode_envelope
from app.storage import BlobStore
from app.viseme_assets import VisemeError
from app.viseme_blend import (
    ENGINE as VISEME_ENGINE,
    LIMITATION as VISEME_LIMITATION,
    MODE as VISEME_MODE,
    WORKFLOW_VERSION as VISEME_WORKFLOW_VERSION,
    VisemeSpan,
    blend_parameters,
    check_timing_bounds,
    parse_timings,
    render_blend_preview,
)
from app.viseme_service import load_entries, read_entry, set_report, variant_sha256

router = APIRouter(prefix="/api", tags=["mouth-animation"])

ENGINES = ("mouth_animation_mvp", "viseme_frame_blend_v1")


class MouthAnimationRequest(BaseModel):
    """Параметры запуска: источник, запись, калибровка и движок."""

    source_kind: Literal["image", "video"] = "image"
    reference_asset_id: uuid.UUID | None = None
    audio_asset_id: uuid.UUID | None = None
    calibration_id: uuid.UUID | None = None
    # WP-VOICE-06: сборка из viseme-кадров.
    engine: Literal["mouth_animation_mvp", "viseme_frame_blend_v1"] = (
        "mouth_animation_mvp"
    )
    timing: Any | None = None
    blend_ms: float | None = None
    min_hold_ms: float | None = None
    close_in_silence: bool = True
    use_rhubarb: bool = False


class MouthAnimationOut(BaseModel):
    shot_id: uuid.UUID
    job_id: uuid.UUID
    attempt_id: uuid.UUID
    artifact_id: uuid.UUID
    content_url: str
    sha256: str
    bytes: int
    width: int
    height: int
    fps: int
    frames: int
    duration_s: float
    audio_asset_id: uuid.UUID
    calibration_id: uuid.UUID
    mode: str
    limitation: str


def _audio_asset(
    session: Session, shot_id: uuid.UUID, audio_asset_id: uuid.UUID | None
) -> ReferenceAsset:
    if audio_asset_id is None:
        chosen = selected_audio_id(session, shot_id)
        if chosen is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "audio_required",
                    "message": "у шота нет утверждённой записи: импортируйте и утвердите аудио",
                },
            )
        audio_asset_id = chosen

    asset = session.get(ReferenceAsset, audio_asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="shot audio not found")
    linked = session.scalar(
        select(ShotReference.id).where(
            ShotReference.shot_id == shot_id,
            ShotReference.reference_asset_id == asset.id,
        )
    )
    if asset.role != SHOT_AUDIO_ROLE or linked is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "audio_required",
                "message": "запись не привязана к шоту как аудио",
            },
        )
    if asset.status != "approved":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "audio_not_approved",
                "message": "запись должна быть утверждена человеком",
            },
        )
    return asset


def resolve_calibration(
    session: Session,
    shot_id: uuid.UUID,
    source: SourceImage,
    calibration_id: uuid.UUID | None,
) -> MouthCalibration:
    row: MouthCalibration | None
    if calibration_id is not None:
        row = session.get(MouthCalibration, calibration_id)
        if row is None or row.shot_id != shot_id:
            raise HTTPException(status_code=404, detail="mouth calibration not found")
    else:
        statement = select(MouthCalibration).where(MouthCalibration.shot_id == shot_id)
        if source.reference_asset_id is not None:
            statement = statement.where(
                MouthCalibration.reference_asset_id == source.reference_asset_id
            )
        else:
            statement = statement.where(
                MouthCalibration.keyframe_artifact_id == source.artifact_id
            )
        row = session.scalar(statement)
        if row is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "calibration_required",
                    "message": "сначала сохраните калибровку области рта для этого источника",
                },
            )

    matches_reference = (
        source.reference_asset_id is not None
        and row.reference_asset_id == source.reference_asset_id
    )
    matches_keyframe = (
        source.artifact_id is not None and row.keyframe_artifact_id == source.artifact_id
    )
    if not matches_reference and not matches_keyframe:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "calibration_source_mismatch",
                "message": "калибровка относится к другому источнику изображения",
            },
        )
    return row


def _audio_payload(store: BlobStore, asset: ReferenceAsset) -> tuple[Path, list[float], float]:
    metadata = asset.metadata_json or {}
    work_key = metadata.get("work_storage_key")
    if not isinstance(work_key, str):
        raise HTTPException(
            status_code=409,
            detail={"error": "audio_work_copy_missing", "message": "нет рабочей PCM-копии"},
        )
    work_path = store.resolve(work_key)
    if not work_path.is_file():
        raise HTTPException(
            status_code=409,
            detail={"error": "audio_work_copy_missing", "message": "рабочая копия потеряна"},
        )

    raw_envelope = metadata.get("envelope")
    if isinstance(raw_envelope, list):
        envelope = [float(value) for value in raw_envelope]
    else:
        try:
            envelope = decode_envelope(work_path)
        except Exception as error:  # noqa: BLE001 - пробрасываем как 409
            raise HTTPException(
                status_code=409,
                detail={"error": "audio_work_copy_invalid", "message": str(error)},
            ) from error

    duration = metadata.get("duration_s")
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        duration = len(envelope) / ENVELOPE_RATE_HZ
    return work_path, envelope, float(duration)


def _persist_result(
    session: Session,
    shot,
    store: BlobStore,
    output: Path,
    *,
    info,
    parameters: dict[str, Any],
    mode: str,
    workflow_version: str,
    source: SourceImage,
    audio: ReferenceAsset,
    calibration: MouthCalibration,
) -> MouthAnimationOut:
    """Общий финал: Job + RenderAttempt + Artifact без автоутверждения."""

    blob = store.put_file(output, suffix=".mp4")

    job = Job(
        kind="mouth_animation",
        shot_id=shot.id,
        status="completed",
        payload={
            "shot_id": str(shot.id),
            "mode": mode,
            "audio_asset_id": str(audio.id),
            "calibration_id": str(calibration.id),
            "source_kind": source.kind,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    session.add(job)
    session.flush()

    attempt = RenderAttempt(
        shot_id=shot.id,
        job_id=job.id,
        kind="video",
        status="completed",
        input_artifact_ids=(
            [str(source.artifact_id)] if source.artifact_id is not None else []
        ),
        workflow_version=workflow_version,
        duration_s=Decimal(str(info.duration_s)),
        parameters=parameters,
    )
    session.add(attempt)
    session.flush()

    artifact = Artifact(
        attempt_id=attempt.id,
        source="attempt",
        kind=RESULT_KIND,
        storage_key=blob.storage_key,
        sha256=blob.sha256,
        bytes=blob.size,
        mime_type=RESULT_MIME,
        metadata_json={
            **parameters,
            "artifact_kind": RESULT_KIND,
        },
    )
    session.add(artifact)
    session.flush()

    job.payload = {
        **(job.payload or {}),
        "attempt_id": str(attempt.id),
        "artifact_id": str(artifact.id),
    }
    session.commit()
    session.refresh(artifact)

    return MouthAnimationOut(
        shot_id=shot.id,
        job_id=job.id,
        attempt_id=attempt.id,
        artifact_id=artifact.id,
        content_url=f"/api/artifacts/{artifact.id}/content",
        sha256=artifact.sha256,
        bytes=artifact.bytes,
        width=info.width,
        height=info.height,
        fps=info.fps,
        frames=info.frames,
        duration_s=info.duration_s,
        audio_asset_id=audio.id,
        calibration_id=calibration.id,
        mode=mode,
        limitation=(
            VISEME_LIMITATION if mode == VISEME_MODE else LIMITATION
        ),
    )


def _create_viseme_animation(
    shot,
    payload: MouthAnimationRequest,
    session: Session,
    settings: Settings,
    store: BlobStore,
) -> MouthAnimationOut:
    """Сборка из viseme-кадров: проверка набора → тайминги → MP4 → попытка."""

    audio = _audio_asset(session, shot.id, payload.audio_asset_id)
    source = resolve_source_image(
        session, shot, payload.reference_asset_id, store=store
    )
    calibration = resolve_calibration(session, shot.id, source, payload.calibration_id)
    region = region_from_calibration(calibration)
    try:
        region.validate()
    except MouthAnimationError as error:
        raise HTTPException(
            status_code=409, detail={"error": error.code, "message": error.message}
        ) from error

    entries = load_entries(session, shot, source)
    source_bytes = source.read(store)
    report = set_report(
        store,
        source_bytes,
        entries,
        region,
        outside_max_ratio=settings.viseme_outside_max_ratio,
        max_shift_px=settings.viseme_max_shift_px,
    )
    if not report.ready:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "viseme_set_blocked",
                "message": "набор viseme-кадров не прошёл проверку совместимости",
                "missing": report.missing,
                "blockers": report.blockers,
            },
        )

    work_path, _envelope, duration = _audio_payload(store, audio)
    audio_metadata = audio.metadata_json or {}

    timing_raw = payload.timing
    timing_source = "payload"
    if payload.use_rhubarb:
        try:
            timing_raw = rhubarb.analyze(
                work_path,
                configured=settings.rhubarb_binary,
                expected_sha256=settings.rhubarb_sha256,
            )
            timing_source = "rhubarb"
        except rhubarb.RhubarbError as error:
            raise HTTPException(
                status_code=409, detail={"error": error.code, "message": error.message}
            ) from error

    if timing_raw is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "viseme_timing_required",
                "message": "нужен viseme timing JSON или проверенный Rhubarb",
            },
        )
    try:
        timing: list[VisemeSpan] = parse_timings(timing_raw)
        check_timing_bounds(timing, duration)
    except VisemeError as error:
        raise HTTPException(
            status_code=422, detail={"error": error.code, "message": error.message}
        ) from error

    payloads = {state: read_entry(store, entry) for state, entry in entries.items()}
    blend_ms = (
        payload.blend_ms if payload.blend_ms is not None else settings.viseme_blend_ms
    )
    min_hold_ms = (
        payload.min_hold_ms
        if payload.min_hold_ms is not None
        else settings.viseme_min_hold_ms
    )
    silences = audio_metadata.get("silence_segments")
    silence_segments = silences if isinstance(silences, list) else []

    with tempfile.TemporaryDirectory(prefix="mary-viseme-") as workdir:
        output = Path(workdir) / "viseme_preview.mp4"
        try:
            info = render_blend_preview(
                source_bytes,
                payloads,
                timing,
                duration,
                work_path,
                region,
                output_path=output,
                fps=settings.mouth_animation_fps,
                max_side=settings.mouth_animation_max_side,
                blend_ms=blend_ms,
                min_hold_ms=min_hold_ms,
                silence_segments=silence_segments,
                close_in_silence=payload.close_in_silence,
            )
        except VisemeError as error:
            raise HTTPException(
                status_code=500,
                detail={"error": error.code, "message": error.message},
            ) from error

        parameters = blend_parameters(
            region=region,
            info=info,
            audio_asset_id=str(audio.id),
            audio_sha256=audio.sha256,
            source=source.as_metadata(),
            calibration_id=str(calibration.id),
            variant_sha256=variant_sha256(entries),
            timing=timing,
            blend_ms=blend_ms,
            min_hold_ms=min_hold_ms,
            close_in_silence=payload.close_in_silence,
            timing_source=timing_source,
            extras={
                "compatibility": report.as_dict(),
                "envelope_rate_hz": ENVELOPE_RATE_HZ,
                "gate": audio_metadata.get("gate"),
                "speech_ratio": audio_metadata.get("speech_ratio"),
                "silence_segments": silence_segments,
            },
        )
        return _persist_result(
            session,
            shot,
            store,
            output,
            info=info,
            parameters=parameters,
            mode=VISEME_MODE,
            workflow_version=VISEME_WORKFLOW_VERSION,
            source=source,
            audio=audio,
            calibration=calibration,
        )


@router.post("/shots/{shot_id}/mouth-animation", response_model=MouthAnimationOut)
def create_mouth_animation(
    shot_id: uuid.UUID,
    payload: MouthAnimationRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
    store: BlobStore = Depends(get_store),
) -> MouthAnimationOut:
    """Синхронный Talking Preview: approved-кадр + запись + калибровка → MP4."""

    shot = require_shot(session, shot_id)
    shot_project_id(session, shot)

    if payload.source_kind == "video":
        raise HTTPException(
            status_code=409,
            detail={
                "error": "video_talking_not_supported",
                "message": (
                    "Video Talking не поддерживается: нет надёжного tracking морды. "
                    "Используйте image-режим."
                ),
            },
        )

    if payload.engine == VISEME_ENGINE:
        return _create_viseme_animation(shot, payload, session, settings, store)

    audio = _audio_asset(session, shot.id, payload.audio_asset_id)
    source = resolve_source_image(
        session, shot, payload.reference_asset_id, store=store
    )
    calibration = resolve_calibration(session, shot.id, source, payload.calibration_id)
    region = region_from_calibration(calibration)
    try:
        region.validate()
    except MouthAnimationError as error:
        raise HTTPException(
            status_code=409, detail={"error": error.code, "message": error.message}
        ) from error

    work_path, envelope, duration = _audio_payload(store, audio)
    source_bytes = source.read(store)
    audio_metadata = audio.metadata_json or {}

    with tempfile.TemporaryDirectory(prefix="mary-mouth-") as workdir:
        output = Path(workdir) / "talking_preview.mp4"
        try:
            info = render_talking_preview(
                source_bytes,
                work_path,
                envelope,
                duration,
                region,
                output_path=output,
                fps=settings.mouth_animation_fps,
                max_side=settings.mouth_animation_max_side,
            )
        except MouthAnimationError as error:
            raise HTTPException(
                status_code=500,
                detail={"error": error.code, "message": error.message},
            ) from error

        parameters = preview_parameters(
            region=region,
            info=info,
            audio_asset_id=str(audio.id),
            audio_sha256=audio.sha256,
            source=source.as_metadata(),
            calibration_id=str(calibration.id),
            envelope_summary=audio_metadata,
        )
        return _persist_result(
            session,
            shot,
            store,
            output,
            info=info,
            parameters=parameters,
            mode=MODE,
            workflow_version=WORKFLOW_VERSION,
            source=source,
            audio=audio,
            calibration=calibration,
        )
