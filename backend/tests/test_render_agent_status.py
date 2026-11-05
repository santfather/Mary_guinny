"""WP-THERMAL-02 (Q-29): read-only статус render-agent."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.config import Settings
from app.main import create_app


@pytest.fixture
def status_client(conn: Connection, tmp_path) -> Iterator[TestClient]:
    app = create_app(
        Settings(
            storage_root=tmp_path / "storage",
            render_agent_state_path=tmp_path / "thermal-state.json",
            render_agent_events_path=tmp_path / "thermal-events.jsonl",
            render_agent_stale_seconds=180.0,
        )
    )

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


def _write_state(path, *, updated_at: datetime, **overrides) -> None:
    payload = {
        "schema": 1,
        "worker": "ltx-1",
        "profile": "eco",
        "pid": 4242,
        "updated_at": updated_at.isoformat(),
        "rendering": False,
        "current_job_id": None,
        "thermal": {"state": "fair", "source": "process_info"},
        "power": {"source": "ac", "battery_percent": 100},
        "memory": {"pressure": "normal", "pressure_level": 1, "available_bytes": 8 * 1024**3},
        "admission": {"allowed": True, "reason": None, "wait_seconds": 0.0},
        "cooldown": {"next_allowed_at": None, "remaining_seconds": 0.0},
        "pause": {"active": False, "reason": None, "since": None, "waited_seconds": 0.0},
        "batch": {"index": 2, "size": 3, "consecutive_jobs": 2},
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), "utf-8")


def test_status_without_files_reports_offline(status_client, tmp_path) -> None:
    response = status_client.get("/api/render-agent/status")

    assert response.status_code == 200
    body = response.json()
    assert body["worker_online"] is False
    assert body["stale"] is True
    assert body["thermal"] == {"state": "unknown", "source": "none"}
    # Счётчики очереди читаются из общей БД, поэтому проверяется только тип.
    assert isinstance(body["queue"]["active_render_jobs"], int)
    assert isinstance(body["queue"]["pending_render_jobs"], int)
    assert body["last_events"] == []


def test_status_reads_fresh_state(status_client, tmp_path) -> None:
    _write_state(
        tmp_path / "thermal-state.json",
        updated_at=datetime.now(timezone.utc),
        pause={
            "active": True,
            "reason": "thermal_serious",
            "since": "2026-11-04T10:00:00+00:00",
            "waited_seconds": 120.0,
        },
    )

    body = status_client.get("/api/render-agent/status").json()

    assert body["worker_online"] is True
    assert body["stale"] is False
    assert body["profile"] == "eco"
    assert body["worker"] == "ltx-1"
    assert body["thermal"] == {"state": "fair", "source": "process_info"}
    assert body["power"] == {
        "source": "ac",
        "battery_percent": 100,
        # WP-THERMAL-03: поля нет в state-файле → Unknown, а не `false`.
        "low_power_mode": None,
    }
    assert body["memory"]["available_mb"] == 8192
    assert body["pause"]["active"] is True
    assert body["pause"]["reason"] == "thermal_serious"
    assert body["batch"] == {"index": 2, "size": 3}
    assert body["age_seconds"] is not None and body["age_seconds"] < 5


def test_status_reports_low_power_mode_only_as_bool(status_client, tmp_path) -> None:
    """WP-THERMAL-03 (T-06): Low Power Mode — только чтение, без догадок."""

    _write_state(
        tmp_path / "thermal-state.json",
        updated_at=datetime.now(timezone.utc),
        low_power_mode=True,
    )
    body = status_client.get("/api/render-agent/status").json()
    assert body["power"]["low_power_mode"] is True

    _write_state(
        tmp_path / "thermal-state.json",
        updated_at=datetime.now(timezone.utc),
        low_power_mode="yes",
    )
    body = status_client.get("/api/render-agent/status").json()
    assert body["power"]["low_power_mode"] is None


def test_status_marks_stale_state_and_keeps_last_reading(status_client, tmp_path) -> None:
    _write_state(
        tmp_path / "thermal-state.json",
        updated_at=datetime.now(timezone.utc) - timedelta(minutes=10),
    )

    body = status_client.get("/api/render-agent/status").json()

    assert body["worker_online"] is False
    assert body["stale"] is True
    assert body["age_seconds"] >= 600
    assert body["thermal"]["state"] == "fair"


def test_status_returns_last_events_tail(status_client, tmp_path) -> None:
    lines = [
        json.dumps(
            {
                "ts": f"2026-11-04T10:{index:02d}:00+00:00",
                "event": "decision",
                "reason": f"reason-{index}",
                "thermal": "nominal",
                "job_id": None,
            }
        )
        for index in range(12)
    ]
    (tmp_path / "thermal-events.jsonl").write_text("\n".join(lines) + "\n", "utf-8")

    body = status_client.get("/api/render-agent/status").json()

    assert len(body["last_events"]) == 10
    assert body["last_events"][0]["reason"] == "reason-2"
    assert body["last_events"][-1]["reason"] == "reason-11"


def test_status_endpoint_is_read_only(status_client) -> None:
    assert status_client.post("/api/render-agent/status").status_code == 405
