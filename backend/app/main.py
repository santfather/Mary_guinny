from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.artifacts import router as artifacts_router
from app.api.characters import router as characters_router
from app.api.compositions import router as compositions_router
from app.api.jobs import router as jobs_router
from app.api.locations import router as locations_router
from app.api.projects import router as projects_router
from app.api.props import router as props_router
from app.api.reference_assets import router as reference_assets_router
from app.api.scene_plans import router as scene_plans_router
from app.api.shots import router as shots_router
from app.api.worker import router as worker_router
from app.config import Settings
from app.db import build_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    app = FastAPI(title="Mary Studio API", version="0.1.0")
    app.state.settings = resolved
    app.state.engine = build_engine(resolved)
    app.include_router(artifacts_router)
    app.include_router(projects_router)
    app.include_router(characters_router)
    app.include_router(reference_assets_router)
    app.include_router(locations_router)
    app.include_router(props_router)
    app.include_router(shots_router)
    app.include_router(compositions_router)
    app.include_router(scene_plans_router)
    app.include_router(jobs_router)
    app.include_router(worker_router)

    @app.get("/api/health")
    @app.get("/health")
    def health(request: Request) -> JSONResponse:
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse(
                status_code=503, content={"status": "degraded", "database": "unavailable"}
            )
        return JSONResponse(content={"status": "ok", "database": "ok"})

    return app


app = create_app()
