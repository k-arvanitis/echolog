from __future__ import annotations

from pathlib import Path
from uuid import UUID

from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.db import SessionLocal, init_db
from meeting_intelligence_engine.rag.ingest import delete_by_meeting_id, ingest_meeting_markdown
from meeting_intelligence_engine.services.meetings import get_meeting
from meeting_intelligence_engine.workers.celery_app import celery_app


@celery_app.task(name="meeting_intelligence_engine.index_meeting", bind=True, max_retries=2)
def index_meeting(self, meeting_id: str) -> dict[str, str]:
    if not settings.rag_enabled:
        return {"meeting_id": meeting_id, "task_id": self.request.id or "", "status": "skipped"}
    init_db()
    parsed_meeting_id = UUID(meeting_id)
    try:
        with SessionLocal() as session:
            meeting = get_meeting(session, parsed_meeting_id)
            transcript_md_path = meeting.transcript_md_path
        if not transcript_md_path:
            raise RuntimeError(f"No markdown transcript available for meeting {meeting_id}")
        ingest_meeting_markdown(meeting_id, Path(transcript_md_path))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1)) from exc
        raise
    return {"meeting_id": meeting_id, "task_id": self.request.id or "", "status": "indexed"}


@celery_app.task(name="meeting_intelligence_engine.remove_meeting_index", bind=True, max_retries=2)
def remove_meeting_index(self, meeting_id: str) -> dict[str, str]:
    if not settings.rag_enabled:
        return {"meeting_id": meeting_id, "task_id": self.request.id or "", "status": "skipped"}
    try:
        delete_by_meeting_id(meeting_id)
    except Exception as exc:
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1)) from exc
        raise
    return {"meeting_id": meeting_id, "task_id": self.request.id or "", "status": "removed"}
