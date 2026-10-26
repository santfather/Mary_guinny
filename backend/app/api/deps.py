from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.storage import BlobStore


def get_session(request: Request) -> Iterator[Session]:
    session = Session(request.app.state.engine)
    try:
        yield session
    finally:
        session.close()


def get_store(request: Request) -> BlobStore:
    return BlobStore(request.app.state.settings.storage_root)
