from __future__ import annotations

import importlib
import shutil
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from meeting_intelligence_engine.core.schemas import (
    ActionItemExtract,
    AnalyticsResult,
    DecisionExtract,
    ProcessingStage,
    TopicExtract,
    TranscriptResult,
    TranscriptSegment,
    Word,
)


def fake_transcribe_and_diarize_stage(audio_path: Path, meeting_id: UUID, _config, progress) -> TranscriptResult:
    assert audio_path.exists()
    progress.update(ProcessingStage.transcribing, 35)
    progress.update(ProcessingStage.diarizing, 70)
    progress.update(ProcessingStage.aligning, 85)
    return TranscriptResult(
        meeting_id=meeting_id,
        speakers=["SPEAKER_00"],
        segments=[
            TranscriptSegment(
                speaker_id="SPEAKER_00",
                speaker_name=None,
                start_time=0.0,
                end_time=1.0,
                text="Hi, I'm Jason Somerville.",
                words=[
                    Word(text="Hi", start=0.0, end=0.1),
                    Word(text="I'm", start=0.2, end=0.4),
                    Word(text="Jason", start=0.5, end=0.7),
                    Word(text="Somerville", start=0.7, end=1.0),
                ],
            ),
            TranscriptSegment(
                speaker_id="SPEAKER_00",
                speaker_name=None,
                start_time=1.1,
                end_time=2.0,
                text="hello meeting",
                words=[Word(text="hello", start=1.1, end=1.4), Word(text="meeting", start=1.5, end=2.0)],
            ),
        ],
        metadata={
            "asr_model_name": "fake-asr",
            "diarization_model_name": "fake-diarization",
            "processing_duration_seconds": 0.01,
            "word_count": 2,
            "diarization_fallback": False,
            "diarization_warning": None,
        },
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required")
def test_upload_process_and_fetch_transcript(make_app, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_module = make_app()
    meetings_module = importlib.import_module("meeting_intelligence_engine.services.meetings")
    analytics_module = importlib.import_module("meeting_intelligence_engine.services.analytics")
    monkeypatch.setattr(meetings_module, "transcribe_and_diarize_stage", fake_transcribe_and_diarize_stage)
    monkeypatch.setattr(
        analytics_module,
        "extract_analytics",
        lambda _text, _settings: AnalyticsResult(
            action_items=[
                ActionItemExtract(
                    description="Follow up with customer",
                    assignee_inferred="SPEAKER_00",
                    priority="high",
                    confidence=0.9,
                    timestamp=0.0,
                )
            ],
            decisions=[
                DecisionExtract(
                    decision_text="Use the mocked pipeline",
                    context="Test transcript",
                    stakeholders=["SPEAKER_00"],
                    timestamp=0.0,
                    confidence=0.95,
                )
            ],
            topics=[
                TopicExtract(
                    topic_name="Testing",
                    start_time=0.0,
                    end_time=1.0,
                    keywords=["mock", "pipeline"],
                    confidence=0.8,
                )
            ],
        ),
    )

    audio_path = tmp_path / "sample.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            str(audio_path),
        ],
        check=True,
    )

    with TestClient(app_module.app) as client:
        with audio_path.open("rb") as audio_file:
            upload = client.post(
                "/meetings/upload",
                files={"file": ("sample.mp3", audio_file, "audio/mpeg")},
                data={"title": "Sample"},
            )
        assert upload.status_code == 200, upload.text
        body = upload.json()
        assert body["status"] == "pending"
        assert body["job_id"]

        meeting = client.get(f"/meetings/{body['meeting_id']}")
        assert meeting.status_code == 200
        meeting_body = meeting.json()
        assert meeting_body["status"] == "completed"
        assert meeting_body["processing_stage"] == "completed"
        assert meeting_body["progress_percent"] == 100.0

        transcript = client.get(f"/meetings/{body['meeting_id']}/transcript")
        assert transcript.status_code == 200
        data = transcript.json()
        assert data["speakers"] == ["SPEAKER_00"]
        assert data["segments"][0]["speaker_name"] == "Jason Somerville"
        assert data["segments"][0]["display_speaker"] == "Jason Somerville"
        assert data["segments"][1]["text"] == "hello meeting"

        segments = client.get(f"/meetings/{body['meeting_id']}/segments")
        assert segments.status_code == 200
        assert segments.json()[0]["display_speaker"] == "Jason Somerville"

        speaker_labels = client.get(f"/meetings/{body['meeting_id']}/speaker-labels")
        assert speaker_labels.status_code == 200
        assert speaker_labels.json()[0]["speaker_name"] == "Jason Somerville"

        txt_artifact = client.get(f"/meetings/{body['meeting_id']}/artifacts/txt")
        assert txt_artifact.status_code == 200
        assert "hello meeting" in txt_artifact.text

        bad_artifact = client.get(f"/meetings/{body['meeting_id']}/artifacts/pdf")
        assert bad_artifact.status_code == 400

        action_items = client.get(f"/meetings/{body['meeting_id']}/action-items")
        assert action_items.status_code == 200
        assert action_items.json()[0]["description"] == "Follow up with customer"

        decisions = client.get(f"/meetings/{body['meeting_id']}/decisions")
        assert decisions.status_code == 200
        assert decisions.json()[0]["decision_text"] == "Use the mocked pipeline"

        topics = client.get(f"/meetings/{body['meeting_id']}/topics")
        assert topics.status_code == 200
        assert topics.json()[0]["topic_name"] == "Testing"

        markdown_artifact = client.get(f"/meetings/{body['meeting_id']}/artifacts/md")
        assert markdown_artifact.status_code == 200
        assert "Jason Somerville" in markdown_artifact.text

        rag_query = client.post("/query", json={"query": "hello"})
        assert rag_query.status_code == 503

        deleted = client.delete(f"/meetings/{body['meeting_id']}")
        assert deleted.status_code == 200

        meeting_after_delete = client.get(f"/meetings/{body['meeting_id']}")
        assert meeting_after_delete.status_code == 404


def test_health_and_root_ui(make_app) -> None:
    app_module = make_app()
    with TestClient(app_module.app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        response = client.get("/")
        assert response.status_code == 200
        assert "<!doctype html>" in response.text.lower()


def test_query_request_validation(make_app) -> None:
    app_module = make_app(rag_enabled=True)
    with TestClient(app_module.app) as client:
        assert client.post("/query", json={"query": "   "}).status_code == 422
        assert client.post("/query", json={"query": "ok", "top_k": 99}).status_code == 422
        assert client.post("/query", json={}).status_code == 422


def test_api_key_guard_blocks_side_effects(make_app) -> None:
    app_module = make_app(extra_env={"MIE_API_KEY": "s3cret"})
    with TestClient(app_module.app) as client:
        assert client.delete(f"/meetings/{uuid4()}").status_code == 401
        assert client.delete(f"/meetings/{uuid4()}", headers={"X-API-Key": "wrong"}).status_code == 401
        # read endpoints stay open
        assert client.get("/meetings").status_code == 200
        # correct key passes the guard (then 404 because the meeting does not exist)
        assert client.delete(f"/meetings/{uuid4()}", headers={"X-API-Key": "s3cret"}).status_code == 404


def test_query_routes(make_app, monkeypatch: pytest.MonkeyPatch) -> None:
    app_module = make_app(rag_enabled=True)
    query_routes = importlib.import_module("meeting_intelligence_engine.api.routes.query")
    monkeypatch.setattr(
        query_routes,
        "query_markdown_knowledge",
        lambda query, top_k=5, meeting_ids=None: {
            "answer": f"answer:{query}",
            "sources": [{"meeting_ids": meeting_ids or []}],
            "processing_time_ms": 1,
        },
    )
    monkeypatch.setattr(
        query_routes,
        "query_single_meeting",
        lambda meeting_id, query, top_k=5: {
            "answer": f"single:{query}:{meeting_id}",
            "sources": [{"meeting_id": str(meeting_id)}],
            "processing_time_ms": 1,
        },
    )
    db_module = importlib.import_module("meeting_intelligence_engine.db")
    models_module = importlib.import_module("meeting_intelligence_engine.models")
    db_module.init_db()
    with db_module.SessionLocal() as session:
        session.add(
            models_module.Meeting(
                id=str(uuid4()),
                title="Query Test",
                source="upload",
                status="completed",
                processing_stage="completed",
                progress_percent=100.0,
                raw_audio_path=str(Path("/tmp/query-test.wav")),
            )
        )
        session.commit()

    with TestClient(app_module.app) as client:
        response = client.post("/query", json={"query": "test", "top_k": 3, "meeting_ids": ["m1"]})
        assert response.status_code == 200
        assert response.json()["answer"] == "answer:test"

        meeting_id = client.get("/meetings").json()[0]["id"]
        scoped = client.post(f"/meetings/{meeting_id}/query", json={"query": "inside"})
        assert scoped.status_code == 200
        assert scoped.json()["answer"].startswith("single:inside:")
