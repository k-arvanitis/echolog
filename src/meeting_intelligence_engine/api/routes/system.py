from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["system"])

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
