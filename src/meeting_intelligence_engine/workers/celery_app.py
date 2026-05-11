from __future__ import annotations

from celery import Celery

from meeting_intelligence_engine.config import settings

broker_url = "memory://" if settings.celery_task_always_eager else settings.redis_url
result_backend = "cache+memory://" if settings.celery_task_always_eager else settings.redis_url

celery_app = Celery(
    "meeting_intelligence_engine",
    broker=broker_url,
    backend=result_backend,
    include=[
        "meeting_intelligence_engine.workers.transcription",
        "meeting_intelligence_engine.workers.analytics",
        "meeting_intelligence_engine.workers.indexing",
    ],
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "meeting_intelligence_engine.transcribe_meeting": {"queue": "transcription"},
        "meeting_intelligence_engine.analyze_meeting": {"queue": "analytics"},
        "meeting_intelligence_engine.index_meeting": {"queue": "indexing"},
        "meeting_intelligence_engine.remove_meeting_index": {"queue": "indexing"},
    },
)
