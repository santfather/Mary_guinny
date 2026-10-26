from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db import build_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings()
    app = FastAPI(title="Mary Studio API", version="0.1.0")
    app.state.settings = resolved
    app.state.engine = build_engine(resolved)

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
