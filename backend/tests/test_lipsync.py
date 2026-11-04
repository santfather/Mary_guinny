"""WP-M8: интерфейс lip sync — без движка запрос отклоняется и ничего не пишет."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, text

from app import lipsync


def _counts(conn: Connection) -> tuple[int, int]:
    jobs = conn.execute(text("SELECT count(*) FROM jobs")).scalar_one()
    attempts = conn.execute(text("SELECT count(*) FROM render_attempts")).scalar_one()
    return jobs, attempts


def test_adapter_raises_engine_not_selected() -> None:
    assert lipsync.SELECTED_ENGINE is None
    with pytest.raises(lipsync.LipsyncUnavailable) as error:
        lipsync.request_lip_sync()
    assert error.value.code == lipsync.ENGINE_NOT_SELECTED


def test_lipsync_rejects_unknown_shot(api_client: TestClient) -> None:
    response = api_client.post(f"/api/shots/{uuid.uuid4()}/lipsync")
    assert response.status_code == 404
    assert response.json()["detail"] == "shot not found"


def test_lipsync_reports_engine_not_selected(
    api_client: TestClient, shot_id: uuid.UUID
) -> None:
    response = api_client.post(f"/api/shots/{shot_id}/lipsync")
    assert response.status_code == 409
    assert response.json() == {"detail": lipsync.ENGINE_NOT_SELECTED}


def test_lipsync_does_not_create_jobs_or_attempts(
    api_client: TestClient, conn: Connection, shot_id: uuid.UUID
) -> None:
    before = _counts(conn)
    response = api_client.post(f"/api/shots/{shot_id}/lipsync")
    assert response.status_code == 409
    assert _counts(conn) == before
