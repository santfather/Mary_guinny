from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.main import create_app


def _upload(client: TestClient, payload: bytes, *, kind: str, digest: str | None = None):
    return client.post(
        "/api/artifacts",
        params={"kind": kind},
        content=payload,
        headers={
            "X-Content-SHA256": digest or hashlib.sha256(payload).hexdigest(),
            "Content-Type": "image/png",
        },
    )


def test_upload_and_download_artifact(tmp_path: Path) -> None:
    settings = Settings(storage_root=tmp_path / "storage")
    app = create_app(settings)
    payload = b"fake-png-bytes"
    digest = hashlib.sha256(payload).hexdigest()

    try:
        with TestClient(app) as client:
            created = _upload(client, payload, kind="keyframe")
            assert created.status_code == 201
            artifact = created.json()
            assert artifact["sha256"] == digest
            assert artifact["source"] == "upload"
            assert artifact["storage_key"].startswith("blobs/")
            assert not artifact["storage_key"].startswith("/")
            assert artifact["bytes"] == len(payload)

            repeated = _upload(client, payload, kind="keyframe")
            assert repeated.status_code == 201
            assert repeated.json()["id"] == artifact["id"]

            metadata = client.get(f"/api/artifacts/{artifact['id']}")
            assert metadata.status_code == 200
            assert metadata.json()["mime_type"] == "image/png"

            content = client.get(f"/api/artifacts/{artifact['id']}/content")
            assert content.status_code == 200
            assert content.content == payload

            mismatch = _upload(client, payload, kind="keyframe", digest="0" * 64)
            assert mismatch.status_code == 422
            assert mismatch.json()["detail"]["error"] == "sha256_mismatch"

            missing = client.get(f"/api/artifacts/{uuid.uuid4()}")
            assert missing.status_code == 404
    finally:
        engine = app.state.engine
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM artifacts WHERE sha256 = :sha256"), {"sha256": digest}
            )
        engine.dispose()


def test_download_missing_artifact_returns_404(tmp_path: Path) -> None:
    app = create_app(Settings(storage_root=tmp_path / "storage"))
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/artifacts/{uuid.uuid4()}/content")
            assert response.status_code == 404
    finally:
        app.state.engine.dispose()
