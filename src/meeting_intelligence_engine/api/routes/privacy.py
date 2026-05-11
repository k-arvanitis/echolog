from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from meeting_intelligence_engine.api.deps import get_session, require_api_key
from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.services.meetings import cleanup_expired_meetings
from meeting_intelligence_engine.workers.indexing import remove_meeting_index

router = APIRouter(prefix="/privacy", tags=["privacy"])


@router.get("/settings")
def get_privacy_settings() -> dict[str, int | bool | None]:
    return {
        "default_retention_days": settings.default_retention_days,
        "delete_raw_audio_after_processing": settings.delete_raw_audio_after_processing,
    }


@router.post("/cleanup-expired", dependencies=[Depends(require_api_key)])
def cleanup_expired_endpoint(session: Session = Depends(get_session)) -> dict[str, object]:
    deleted_ids = cleanup_expired_meetings(session)
    if settings.rag_enabled:
        for meeting_id in deleted_ids:
            remove_meeting_index.apply_async(args=[meeting_id])
    return {"deleted_meeting_ids": deleted_ids, "deleted_count": len(deleted_ids)}
