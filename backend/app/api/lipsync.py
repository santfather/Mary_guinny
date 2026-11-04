"""WP-M8: интерфейс lip sync шота — движок не выбран, запрос отклоняется."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.api.shots import require_shot
from app.lipsync import LipsyncUnavailable, request_lip_sync

router = APIRouter(prefix="/api", tags=["lipsync"])


@router.post("/shots/{shot_id}/lipsync")
def request_shot_lipsync(
    shot_id: uuid.UUID, session: Session = Depends(get_session)
) -> None:
    """Проверяет шот и отклоняет запрос, пока движок lip sync не утверждён.

    В БД ничего не пишется, job не создаётся: это интерфейс без движка (WP-M8).
    """

    require_shot(session, shot_id)
    try:
        request_lip_sync()
    except LipsyncUnavailable as error:
        raise HTTPException(status_code=409, detail=error.code) from error
