from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_store, require_project
from app.preflight import run_preflight
from app.series_import import ImportOptions, import_series
from app.series_manifest import (
    ManifestError,
    cross_check_queue,
    parse_manifest,
    parse_queue_csv,
)
from app.storage import BlobStore

router = APIRouter(prefix="/api/projects", tags=["series"])


class SeriesRequest(BaseModel):
    """Тело импорта/preflight: манифест передаётся как JSON, без путей на сервере."""

    manifest: dict[str, Any]
    queue_csv: str | None = None
    fps: int = Field(default=24, ge=1, le=120)
    dry_run: bool = False


def _parse(request: SeriesRequest) -> tuple[Any, list[dict[str, str]] | None]:
    try:
        manifest = parse_manifest(request.manifest)
    except ManifestError as error:
        raise HTTPException(status_code=422, detail={"manifest": error.errors}) from error
    rows = None
    if request.queue_csv:
        try:
            rows = parse_queue_csv(request.queue_csv)
        except ManifestError as error:
            raise HTTPException(status_code=422, detail={"queue_csv": error.errors}) from error
    return manifest, rows


@router.post("/{project_id}/series/import")
def import_series_manifest(
    project_id: uuid.UUID,
    request: SeriesRequest,
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
) -> dict[str, Any]:
    """Идемпотентный импорт манифеста в существующие Project/Episode/Scene/Shot."""

    project = require_project(session, project_id)
    manifest, rows = _parse(request)
    if rows is not None:
        mismatches = cross_check_queue(manifest, rows)
        if mismatches:
            raise HTTPException(status_code=422, detail={"queue_csv": mismatches})
    report = import_series(
        session,
        store,
        manifest,
        ImportOptions(project_title=project.title, fps=request.fps),
        apply=not request.dry_run,
        project=project,
    )
    if request.dry_run:
        session.rollback()
    else:
        session.commit()
    return report.as_dict()


@router.post("/{project_id}/series/preflight")
def series_preflight(
    project_id: uuid.UUID,
    request: SeriesRequest,
    session: Session = Depends(get_session),
    store: BlobStore = Depends(get_store),
) -> dict[str, Any]:
    """Проверки готовности серии: шоты, референсы, стартовые кадры, workflow."""

    project = require_project(session, project_id)
    manifest, rows = _parse(request)
    report = run_preflight(
        session,
        store,
        manifest,
        project=project,
        queue_rows=rows,
        fps=request.fps,
    )
    return report.as_dict()
