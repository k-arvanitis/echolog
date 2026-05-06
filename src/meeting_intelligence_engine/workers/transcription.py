from __future__ import annotations

from uuid import UUID

from meeting_intelligence_engine.db import SessionLocal, init_db
from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.services.meetings import mark_meeting_failed, process_meeting
from meeting_intelligence_engine.workers.celery_app import celery_app


@celery_app.task(name="meeting_intelligence_engine.transcribe_meeting", bind=True, max_retries=2)
def transcribe_meeting(self, meeting_id: str) -> dict[str, str]:
    init_db()
    parsed_meeting_id = UUID(meeting_id)
    try:
        with SessionLocal() as session:
            process_meeting(session, parsed_meeting_id, mark_failed=False)
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1)) from exc
        with SessionLocal() as session:
            mark_meeting_failed(session, parsed_meeting_id, str(exc))
        raise
    if settings.analytics_enabled:
        from meeting_intelligence_engine.workers.analytics import analyze_meeting

        analyze_meeting.apply_async(args=[meeting_id])
    elif settings.rag_enabled:
        from meeting_intelligence_engine.workers.indexing import index_meeting

        index_meeting.apply_async(args=[meeting_id])
    return {"meeting_id": meeting_id, "task_id": self.request.id or ""}
