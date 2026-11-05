"""Загрузка viseme-набора шота и его проверка (WP-VOICE-06).

Общие функции для `api/viseme_set.py` и `api/mouth_animation.py`: разбор
`reference_assets(role='viseme_<state>')`, чтение байтов и отчёт совместимости.
Миграций нет; `closed` может быть неявно взят из approved-источника.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.mouth_sources import SourceImage
from app.models import ReferenceAsset, Shot, ShotReference
from app.mouth_animation import MouthRegion
from app.storage import BlobStore, StorageError
from app.viseme_assets import (
    VISEME_STATES,
    CompatibilityReport,
    VariantInfo,
    VisemeError,
    check_compatibility,
    role_for,
    state_from_role,
)


@dataclass(frozen=True)
class VariantEntry:
    """Один вариант набора: явный ассет или неявный approved-источник."""

    state: str
    storage_key: str
    sha256: str
    status: str
    content_url: str
    width: int | None = None
    height: int | None = None
    asset_id: uuid.UUID | None = None
    artifact_id: uuid.UUID | None = None
    implicit: bool = False

    def as_info(self) -> VariantInfo:
        return VariantInfo(
            state=self.state,
            reference_asset_id=str(self.asset_id) if self.asset_id else "",
            status=self.status,
            width=self.width,
            height=self.height,
            sha256=self.sha256,
            content_url=self.content_url,
        )


def load_entries(
    session: Session, shot: Shot, source: SourceImage | None = None
) -> dict[str, VariantEntry]:
    """Набор шота; при отсутствии `closed` используется approved-источник."""

    roles = [role_for(state) for state in VISEME_STATES]
    assets = list(
        session.scalars(
            select(ReferenceAsset)
            .join(
                ShotReference, ShotReference.reference_asset_id == ReferenceAsset.id
            )
            .where(ShotReference.shot_id == shot.id, ReferenceAsset.role.in_(roles))
        )
    )

    chosen: dict[str, ReferenceAsset] = {}
    for asset in assets:
        state = state_from_role(asset.role)
        if state is None:
            continue
        current = chosen.get(state)
        if current is None:
            chosen[state] = asset
            continue
        # Approved важнее черновика, затем — более свежий.
        if (asset.status == "approved") != (current.status == "approved"):
            if asset.status == "approved":
                chosen[state] = asset
        elif asset.created_at > current.created_at:
            chosen[state] = asset

    entries = {
        state: VariantEntry(
            state=state,
            storage_key=asset.storage_key,
            sha256=asset.sha256,
            status=asset.status,
            content_url=f"/api/reference-assets/{asset.id}/content",
            width=asset.width,
            height=asset.height,
            asset_id=asset.id,
        )
        for state, asset in chosen.items()
    }

    if "closed" not in entries and source is not None:
        if source.reference_asset_id is not None:
            entries["closed"] = VariantEntry(
                state="closed",
                storage_key=source.storage_key,
                sha256=source.sha256,
                status="approved",
                content_url=f"/api/reference-assets/{source.reference_asset_id}/content",
                asset_id=source.reference_asset_id,
                implicit=True,
            )
        elif source.artifact_id is not None:
            entries["closed"] = VariantEntry(
                state="closed",
                storage_key=source.storage_key,
                sha256=source.sha256,
                status="approved",
                content_url=f"/api/artifacts/{source.artifact_id}/content",
                artifact_id=source.artifact_id,
                implicit=True,
            )
    return entries


def read_entry(store: BlobStore, entry: VariantEntry) -> bytes:
    try:
        path = store.resolve(entry.storage_key)
    except StorageError as error:
        raise VisemeError(
            "viseme_file_missing", f"{entry.state}: некорректный storage_key"
        ) from error
    if not path.is_file():
        raise VisemeError(
            "viseme_file_missing", f"{entry.state}: файл не найден в storage"
        )
    return path.read_bytes()


def set_report(
    store: BlobStore,
    source_bytes: bytes,
    entries: dict[str, VariantEntry],
    region: MouthRegion,
    *,
    outside_max_ratio: float = 0.01,
    max_shift_px: int = 8,
) -> CompatibilityReport:
    """Отчёт совместимости по явным и неявным вариантам набора."""

    payloads: dict[str, bytes] = {}
    statuses: dict[str, str] = {}
    metadata: dict[str, VariantInfo] = {}
    for state, entry in entries.items():
        try:
            payloads[state] = read_entry(store, entry)
        except VisemeError:
            # Отсутствующий файл — это incomplete, код добавит check_compatibility.
            continue
        statuses[state] = entry.status
        metadata[state] = entry.as_info()

    return check_compatibility(
        source_bytes,
        payloads,
        region,
        outside_max_ratio=outside_max_ratio,
        max_shift_px=max_shift_px,
        statuses=statuses,
        metadata=metadata,
    )


def variant_sha256(entries: dict[str, VariantEntry]) -> dict[str, str]:
    return {state: entry.sha256 for state, entry in entries.items()}
