from __future__ import annotations

from meeting_intelligence_engine.workers.celery_app import celery_app


def main() -> None:
    celery_app.worker_main(["worker", "--loglevel=INFO", "-Q", "transcription,analytics,indexing"])
