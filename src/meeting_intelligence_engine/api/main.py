from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from meeting_intelligence_engine.api.routes import meetings, privacy, query, system
from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.db import init_db
from meeting_intelligence_engine.logging_config import configure_logging

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    init_db()
    logger.info("Meeting Intelligence Engine API ready (rag_enabled=%s)", settings.rag_enabled)
    yield


def create_app() -> FastAPI:
    app = FastAPI(title=settings.ui_title, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(system.router)
    app.include_router(meetings.router)
    app.include_router(query.router)
    app.include_router(privacy.router)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    return app


app = create_app()


def main() -> None:
    configure_logging()
    uvicorn.run(
        "meeting_intelligence_engine.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.reload,
    )
