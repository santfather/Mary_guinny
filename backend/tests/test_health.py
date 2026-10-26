from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_health_reports_database_ok() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_api_health_alias() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
