from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient


def import_privacy_test_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'privacy.db'}")
    monkeypatch.setenv("REDIS_URL", "memory://")
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "true")
    monkeypatch.setenv("MIE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("HF_TOKEN", "test")
    monkeypatch.setenv("MIE_RAG_ENABLED", "false")
    for module_name in [
        "meeting_intelligence_engine.config",
        "meeting_intelligence_engine.db",
        "meeting_intelligence_engine.models",
        "meeting_intelligence_engine.services.meetings",
        "meeting_intelligence_engine.api.main",
        "meeting_intelligence_engine.workers.celery_app",
        "meeting_intelligence_engine.workers.transcription",
        "meeting_intelligence_engine.workers.indexing",
    ]:
        sys.modules.pop(module_name, None)
    return importlib.import_module("meeting_intelligence_engine.api.main")


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required")
def test_privacy_endpoints(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_module = import_privacy_test_app(monkeypatch, tmp_path)
    meetings_module = importlib.import_module("meeting_intelligence_engine.services.meetings")
    db_module = importlib.import_module("meeting_intelligence_engine.db")
    db_module.init_db()

    audio_path = tmp_path / "sample.mp3"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio_path)],
        check=True,
    )

    with db_module.SessionLocal() as session:
        meeting = meetings_module.create_meeting_from_file(session, audio_path, title="Privacy Test")
        meeting_id = meeting.id

    with TestClient(app_module.app) as client:
        settings_resp = client.get("/privacy/settings")
        assert settings_resp.status_code == 200
        raw_path = Path(client.get(f"/meetings/{meeting_id}").json()["raw_audio_path"])
        assert raw_path.exists()

        retention_resp = client.post(f"/meetings/{meeting_id}/retention", json={"retention_days": 7})
        assert retention_resp.status_code == 200
        assert retention_resp.json()["retention_until"] is not None

        purge_resp = client.post(f"/meetings/{meeting_id}/privacy/purge-raw-audio")
        assert purge_resp.status_code == 200
        assert purge_resp.json()["raw_audio_deleted"] is True
        assert not raw_path.exists()

    with db_module.SessionLocal() as session:
        meeting = meetings_module.get_meeting(session, UUID(meeting_id))
        meeting.retention_until = datetime.now(timezone.utc) - timedelta(days=1)
        session.commit()

    with TestClient(app_module.app) as client:
        cleanup_resp = client.post("/privacy/cleanup-expired")
        assert cleanup_resp.status_code == 200
        assert meeting_id in cleanup_resp.json()["deleted_meeting_ids"]
