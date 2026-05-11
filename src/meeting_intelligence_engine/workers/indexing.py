from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.db import SessionLocal, init_db
from meeting_intelligence_engine.rag.ingest import delete_by_meeting_id, ingest_meeting_markdown
from meeting_intelligence_engine.services.meetings import get_meeting
from meeting_intelligence_engine.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="meeting_intelligence_engine.index_meeting", bind=True, max_retries=2)
def index_meeting(self, meeting_id: str) -> dict[str, str]:
    if not settings.rag_enabled:
        return {"meeting_id": meeting_id, "task_id": self.request.id or "", "status": "skipped"}
    init_db()
    parsed_meeting_id = UUID(meeting_id)
    logger.info("index_meeting start meeting_id=%s attempt=%d", meeting_id, self.request.retries + 1)
    try:
        with SessionLocal() as session:
            meeting = get_meeting(session, parsed_meeting_id)
            transcript_md_path = meeting.transcript_md_path
        if not transcript_md_path:
            raise RuntimeError(f"No markdown transcript available for meeting {meeting_id}")
        chunk_count = ingest_meeting_markdown(meeting_id, Path(transcript_md_path))
    except Exception as exc:
        if self.request.retries < self.max_retries:
            logger.warning("index_meeting retrying meeting_id=%s: %s", meeting_id, exc)
            raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1)) from exc
        logger.exception("index_meeting failed permanently meeting_id=%s", meeting_id)
        raise
    logger.info("index_meeting done meeting_id=%s chunks=%d", meeting_id, chunk_count)
    return {"meeting_id": meeting_id, "task_id": self.request.id or "", "status": "indexed"}


@celery_app.task(name="meeting_intelligence_engine.remove_meeting_index", bind=True, max_retries=2)
def remove_meeting_index(self, meeting_id: str) -> dict[str, str]:
    if not settings.rag_enabled:
        return {"meeting_id": meeting_id, "task_id": self.request.id or "", "status": "skipped"}
    try:
        delete_by_meeting_id(meeting_id)
    except Exception as exc:
        if self.request.retries < self.max_retries:
            logger.warning("remove_meeting_index retrying meeting_id=%s: %s", meeting_id, exc)
            raise self.retry(exc=exc, countdown=10 * (self.request.retries + 1)) from exc
        logger.exception("remove_meeting_index failed permanently meeting_id=%s", meeting_id)
        raise
    logger.info("remove_meeting_index done meeting_id=%s", meeting_id)
    return {"meeting_id": meeting_id, "task_id": self.request.id or "", "status": "removed"}
