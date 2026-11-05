"""Разрешение источника кадра для mouth-анимации (WP-VOICE-02, §4.18).

Источник — approved-изображение: либо approved-референс шота, либо стартовый
кадр шота (artifact). Video Talking в MVP не поддерживается: надёжного tracking
морды в проекте нет, поэтому видео-источник отклоняется явным кодом.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.shots import shot_project_id
from app.models import Artifact, ReferenceAsset, RenderAttempt, Shot, ShotReference
from app.mouth_animation import MouthRegion
from app.storage import BlobStore, StorageError

SOURCE_REFERENCE = "reference"
SOURCE_KEYFRAME = "keyframe"


@dataclass(frozen=True)
class SourceImage:
    kind: str
    storage_key: str
    sha256: str
    mime_type: str
    reference_asset_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None

    def read(self, store: BlobStore) -> bytes:
        try:
            path = store.resolve(self.storage_key)
        except StorageError as error:
            raise HTTPException(
                status_code=500, detail=f"invalid storage_key: {error}"
            ) from error
        if not path.is_file():
            raise HTTPException(status_code=409, detail={"error": "source_file_missing"})
        return path.read_bytes()

    def as_metadata(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "reference_asset_id": (
                str(self.reference_asset_id) if self.reference_asset_id else None
            ),
            "artifact_id": str(self.artifact_id) if self.artifact_id else None,
            "sha256": self.sha256,
            "mime_type": self.mime_type,
        }


def _is_image(mime_type: str | None) -> bool:
    return bool(mime_type and mime_type.startswith("image/"))


def _is_video(mime_type: str | None) -> bool:
    return bool(mime_type and mime_type.startswith("video/"))


def _reject_video() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "error": "video_talking_not_supported",
            "message": (
                "Video Talking не поддерживается: нет надёжного tracking морды. "
                "Используйте image-режим с approved-изображением."
            ),
        },
    )


def resolve_source_image(
    session: Session,
    shot: Shot,
    reference_asset_id: uuid.UUID | None,
    *,
    store: BlobStore,
    keyframe_artifact_id: uuid.UUID | None = None,
) -> SourceImage:
    """approved-референс или стартовый кадр шота; иначе типизированный 409."""

    if reference_asset_id is not None:
        asset = session.get(ReferenceAsset, reference_asset_id)
        if asset is None or asset.project_id != shot_project_id(session, shot):
            raise HTTPException(status_code=404, detail="reference asset not found")
        if _is_video(asset.mime_type):
            raise _reject_video()
        if not _is_image(asset.mime_type) or (asset.metadata_json or {}).get(
            "multi_view"
        ) is True:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "source_image_required",
                    "message": "источником может быть только обычное изображение",
                },
            )
        if asset.status != "approved":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "source_reference_not_approved",
                    "message": "референс не утверждён человеком",
                },
            )
        return SourceImage(
            kind=SOURCE_REFERENCE,
            storage_key=asset.storage_key,
            sha256=asset.sha256,
            mime_type=asset.mime_type or "image/png",
            reference_asset_id=asset.id,
        )

    artifact_id = keyframe_artifact_id or shot.start_keyframe_artifact_id
    if artifact_id is None:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "source_image_required",
                "message": "укажите approved-референс или утвердите стартовый кадр",
            },
        )
    artifact = session.get(Artifact, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=409, detail={"error": "source_file_missing"})
    if _is_video(artifact.mime_type):
        raise _reject_video()
    if not _is_image(artifact.mime_type):
        raise HTTPException(
            status_code=409, detail={"error": "source_image_required"}
        )
    return SourceImage(
        kind=SOURCE_KEYFRAME,
        storage_key=artifact.storage_key,
        sha256=artifact.sha256,
        mime_type=artifact.mime_type,
        artifact_id=artifact.id,
    )


def require_calibration_source(
    session: Session,
    shot: Shot,
    reference_asset_id: uuid.UUID | None,
    keyframe_artifact_id: uuid.UUID | None,
) -> None:
    """Калибровка привязана к шоту: референс — в его ссылках, кадр — его keyframe."""

    if reference_asset_id is not None:
        asset = session.get(ReferenceAsset, reference_asset_id)
        if asset is None or asset.project_id != shot_project_id(session, shot):
            raise HTTPException(status_code=404, detail="reference asset not found")
        link = session.scalar(
            select(ShotReference.id).where(
                ShotReference.shot_id == shot.id,
                ShotReference.reference_asset_id == asset.id,
            )
        )
        if link is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "reference_not_linked",
                    "message": "референс не привязан к шоту",
                },
            )
        if not _is_image(asset.mime_type):
            raise HTTPException(
                status_code=409, detail={"error": "source_image_required"}
            )
        return

    assert keyframe_artifact_id is not None
    artifact = session.get(Artifact, keyframe_artifact_id)
    if artifact is None or artifact.attempt_id is None:
        raise HTTPException(status_code=404, detail="keyframe artifact not found")
    attempt = session.get(RenderAttempt, artifact.attempt_id)
    if attempt is None or attempt.shot_id != shot.id or attempt.kind != "keyframe":
        raise HTTPException(status_code=404, detail="keyframe artifact not found")


def region_from_calibration(row) -> MouthRegion:  # noqa: ANN001 - ORM-строка
    return MouthRegion(
        x=float(row.x),
        y=float(row.y),
        width=float(row.width),
        height=float(row.height),
        rotation=float(row.rotation),
        max_open=float(row.max_open),
        sensitivity=float(row.sensitivity),
        smoothing=float(row.smoothing),
    )
