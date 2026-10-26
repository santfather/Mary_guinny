from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.config import Settings
from app.db import build_engine
from app.main import create_app


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = build_engine(Settings())
    yield engine
    engine.dispose()


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    """Соединение в транзакции, которая всегда откатывается: БД остаётся чистой."""
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def api_client(conn: Connection, tmp_path) -> Iterator[TestClient]:
    """Клиент API на транзакции `conn`: изменения откатываются вместе с ней."""
    app = create_app(Settings(storage_root=tmp_path / "storage"))

    def _session_override() -> Iterator[Session]:
        session = Session(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = _session_override
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.state.engine.dispose()


@pytest.fixture
def project_id(conn: Connection) -> uuid.UUID:
    value = uuid.uuid4()
    conn.execute(
        text("INSERT INTO projects (id, title) VALUES (:id, 'Project A')"), {"id": value}
    )
    return value


@pytest.fixture
def second_project_id(conn: Connection) -> uuid.UUID:
    value = uuid.uuid4()
    conn.execute(
        text("INSERT INTO projects (id, title) VALUES (:id, 'Project B')"), {"id": value}
    )
    return value


@pytest.fixture
def scene_id(conn: Connection, project_id: uuid.UUID) -> uuid.UUID:
    value = uuid.uuid4()
    conn.execute(
        text("INSERT INTO scenes (id, project_id, sequence_no) VALUES (:id, :project_id, 1)"),
        {"id": value, "project_id": project_id},
    )
    return value


@pytest.fixture
def shot_id(conn: Connection, scene_id: uuid.UUID) -> uuid.UUID:
    value = uuid.uuid4()
    conn.execute(
        text("INSERT INTO shots (id, scene_id, sequence_no) VALUES (:id, :scene_id, 1)"),
        {"id": value, "scene_id": scene_id},
    )
    return value


@pytest.fixture
def character_id(conn: Connection, project_id: uuid.UUID) -> uuid.UUID:
    value = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO characters (id, project_id, slug, name, kind)"
            " VALUES (:id, :project_id, 'guinness', 'Guinness', 'cat')"
        ),
        {"id": value, "project_id": project_id},
    )
    return value


@pytest.fixture
def location_id(conn: Connection, project_id: uuid.UUID) -> uuid.UUID:
    value = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO locations (id, project_id, slug, name)"
            " VALUES (:id, :project_id, 'living-room', 'Living room')"
        ),
        {"id": value, "project_id": project_id},
    )
    return value


@pytest.fixture
def prop_id(conn: Connection, project_id: uuid.UUID) -> uuid.UUID:
    value = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO props (id, project_id, slug, name)"
            " VALUES (:id, :project_id, 'red-ball', 'Red ball')"
        ),
        {"id": value, "project_id": project_id},
    )
    return value


@pytest.fixture
def make_asset(conn: Connection) -> Callable[..., uuid.UUID]:
    def _make(
        *,
        project_id: uuid.UUID,
        kind: str = "uploaded",
        character_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        prop_id: uuid.UUID | None = None,
        sha256: str | None = None,
        status: str = "draft",
    ) -> uuid.UUID:
        value = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO reference_assets"
                " (id, project_id, kind, character_id, location_id, prop_id,"
                "  status, storage_key, sha256, mime_type)"
                " VALUES (:id, :project_id, :kind, :character_id, :location_id, :prop_id,"
                "  :status, :storage_key, :sha256, 'image/png')"
            ),
            {
                "id": value,
                "project_id": project_id,
                "kind": kind,
                "character_id": character_id,
                "location_id": location_id,
                "prop_id": prop_id,
                "status": status,
                "storage_key": f"projects/{project_id}/refs/{value}.png",
                "sha256": sha256 or (uuid.uuid4().hex + uuid.uuid4().hex),
            },
        )
        return value

    return _make


@pytest.fixture
def make_reference(conn: Connection) -> Callable[..., uuid.UUID]:
    def _make(
        *,
        project_id: uuid.UUID,
        character_id: uuid.UUID | None = None,
        location_id: uuid.UUID | None = None,
        prop_id: uuid.UUID | None = None,
        status: str = "draft",
        view: str | None = None,
        pose: str | None = None,
        expression: str | None = None,
        storage_key: str | None = None,
        sha256: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> uuid.UUID:
        if character_id is not None:
            kind = "character_reference"
        elif location_id is not None:
            kind = "location_reference"
        elif prop_id is not None:
            kind = "prop_reference"
        else:
            kind = "uploaded"

        value = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO reference_assets"
                " (id, project_id, kind, character_id, location_id, prop_id, status,"
                "  storage_key, sha256, mime_type, view, pose, expression, metadata,"
                "  approved_at)"
                " VALUES (:id, :project_id, :kind, :character_id, :location_id, :prop_id,"
                "  :status, :storage_key, :sha256, 'image/png', :view, :pose, :expression,"
                "  CAST(:metadata AS jsonb), :approved_at)"
            ),
            {
                "id": value,
                "project_id": project_id,
                "kind": kind,
                "character_id": character_id,
                "location_id": location_id,
                "prop_id": prop_id,
                "status": status,
                "storage_key": storage_key
                or f"blobs/{value.hex[:2]}/{value.hex}.png",
                "sha256": sha256 or (uuid.uuid4().hex + uuid.uuid4().hex),
                "view": view,
                "pose": pose,
                "expression": expression,
                "metadata": json.dumps(metadata or {}),
                "approved_at": datetime.now(timezone.utc)
                if status == "approved"
                else None,
            },
        )
        return value

    return _make


@pytest.fixture
def make_bible(conn: Connection) -> Callable[..., uuid.UUID]:
    def _make(
        *,
        project_id: uuid.UUID,
        character_id: uuid.UUID,
        version: int = 1,
        body: str = "# Bible",
        status: str = "draft",
    ) -> uuid.UUID:
        value = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO character_bible_versions"
                " (id, project_id, character_id, version, body, sha256, status, source)"
                " VALUES (:id, :project_id, :character_id, :version, :body, :sha256,"
                "  :status, 'import')"
            ),
            {
                "id": value,
                "project_id": project_id,
                "character_id": character_id,
                "version": version,
                "body": body,
                "sha256": hashlib.sha256(body.encode()).hexdigest(),
                "status": status,
            },
        )
        return value

    return _make


@pytest.fixture
def make_composition(conn: Connection) -> Callable[..., uuid.UUID]:
    def _make(
        *,
        project_id: uuid.UUID,
        shot_id: uuid.UUID,
        revision: int = 1,
        width: int = 512,
        height: int = 512,
    ) -> uuid.UUID:
        value = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO shot_compositions"
                " (id, project_id, shot_id, revision, width, height)"
                " VALUES (:id, :project_id, :shot_id, :revision, :width, :height)"
            ),
            {
                "id": value,
                "project_id": project_id,
                "shot_id": shot_id,
                "revision": revision,
                "width": width,
                "height": height,
            },
        )
        return value

    return _make


@pytest.fixture
def expect_violation(conn: Connection) -> Callable[..., None]:
    """Выполняет SQL внутри SAVEPOINT и требует ошибку БД."""

    def _expect(sql: str, params: dict[str, object], match: str | None = None) -> None:
        savepoint = conn.begin_nested()
        try:
            with pytest.raises(DBAPIError) as excinfo:
                conn.execute(text(sql), params)
            if match is not None:
                assert match in str(excinfo.value), str(excinfo.value)
        finally:
            savepoint.rollback()

    return _expect
