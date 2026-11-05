from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.artifacts import router as artifacts_router
from app.api.attempts import router as attempts_router
from app.api.characters import router as characters_router
from app.api.compositions import router as compositions_router
from app.api.exports import router as exports_router
from app.api.jobs import router as jobs_router
from app.api.library import router as library_router
from app.api.lipsync import router as lipsync_router
from app.api.mouth_animation import router as mouth_animation_router
from app.api.mouth_calibrations import router as mouth_calibrations_router
from app.api.presets import router as presets_router
from app.api.production_plans import router as production_plans_router
from app.api.projects import router as projects_router
from app.api.reference_assets import router as reference_assets_router
from app.api.render_agent import router as render_agent_router
from app.api.scene_plans import router as scene_plans_router
from app.api.series import router as series_router
from app.api.series_runs import (
    project_router as series_runs_project_router,
    run_router as series_runs_router,
    worker_router as series_runs_worker_router,
)
from app.api.shots import router as shots_router
from app.api.shot_audio import router as shot_audio_router
from app.api.viseme_set import router as viseme_set_router
from app.api.voice import router as voice_router
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
    app.include_router(voice_router)
    app.include_router(reference_assets_router)
    app.include_router(library_router)
    app.include_router(shots_router)
    app.include_router(shot_audio_router)
    app.include_router(lipsync_router)
    app.include_router(mouth_calibrations_router)
    app.include_router(mouth_animation_router)
    app.include_router(viseme_set_router)
    app.include_router(attempts_router)
    app.include_router(compositions_router)
    app.include_router(scene_plans_router)
    app.include_router(exports_router)
    app.include_router(production_plans_router)
    app.include_router(presets_router)
    app.include_router(render_agent_router)
    app.include_router(series_router)
    app.include_router(series_runs_project_router)
    app.include_router(series_runs_router)
    app.include_router(jobs_router)
    app.include_router(worker_router)
    app.include_router(series_runs_worker_router)

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
