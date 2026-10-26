from __future__ import annotations

import uuid
from collections.abc import Iterator

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Project
from app.storage import BlobStore


def get_session(request: Request) -> Iterator[Session]:
    session = Session(request.app.state.engine)
    try:
        yield session
    finally:
        session.close()


def get_store(request: Request) -> BlobStore:
    return BlobStore(request.app.state.settings.storage_root)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def require_project(session: Session, project_id: uuid.UUID) -> Project:
    """Единая проверка существования проекта (404), общая для всех роутеров."""

    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project
