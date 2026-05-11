from __future__ import annotations

from collections.abc import Iterator

from fastapi import Header, HTTPException, status
from sqlalchemy.orm import Session

from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.db import SessionLocal


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Guard side-effecting / paid-API endpoints when MIE_API_KEY is configured.

    No-op when no key is set, so local development needs no extra config.
    """
    expected = settings.secret("api_key")
    if expected is None:
        return
    if x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-API-Key header")
