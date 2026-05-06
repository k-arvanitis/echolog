from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.db import get_session, init_db
from meeting_intelligence_engine.rag.query import query_markdown_knowledge, query_single_meeting
from meeting_intelligence_engine.services.analytics import (
    action_item_to_dict,
    decision_to_dict,
    list_action_items,
    list_decisions,
    list_topics,
    topic_to_dict,
)
from meeting_intelligence_engine.services.meetings import (
    cleanup_expired_meetings,
    create_meeting_from_file,
    delete_meeting,
    get_meeting,
    get_transcript,
    list_transcript_segments,
    list_meetings,
    meeting_to_dict,
    purge_raw_audio,
    set_meeting_retention_days,
    set_meeting_job_id,
    transcript_segment_to_dict,
)
from meeting_intelligence_engine.services.speaker_labels import list_speaker_labels, speaker_label_to_dict
from meeting_intelligence_engine.workers.transcription import transcribe_meeting
from meeting_intelligence_engine.workers.indexing import remove_meeting_index


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Meeting Intelligence Engine", version="0.1.0", lifespan=lifespan)
static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/privacy/settings")
def get_privacy_settings() -> dict[str, int | bool | None]:
    return {
        "default_retention_days": settings.default_retention_days,
        "delete_raw_audio_after_processing": settings.delete_raw_audio_after_processing,
    }


@app.get("/")
def root() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.post("/meetings/upload")
def upload_meeting(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    suffix = "." + file.filename.rsplit(".", 1)[-1] if file.filename and "." in file.filename else ""
    with NamedTemporaryFile(prefix="mie-upload-", suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        meeting = create_meeting_from_file(session, source_path=Path(tmp_path), title=title or file.filename)
        task = transcribe_meeting.apply_async(args=[meeting.id])
        set_meeting_job_id(session, UUID(meeting.id), task.id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return {"meeting_id": meeting.id, "status": meeting.status, "job_id": task.id}


@app.get("/meetings")
def list_meetings_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[dict]:
    return [meeting_to_dict(meeting) for meeting in list_meetings(session, limit=limit, offset=offset)]


@app.get("/meetings/{meeting_id}")
def get_meeting_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> dict:
    try:
        return meeting_to_dict(get_meeting(session, meeting_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/meetings/{meeting_id}/transcript")
def get_transcript_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> dict:
    try:
        transcript = get_transcript(session, meeting_id).model_dump(mode="json")
        for segment in transcript.get("segments", []):
            segment["display_speaker"] = segment.get("speaker_name") or segment.get("speaker_id")
        return transcript
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/meetings/{meeting_id}/segments")
def get_segments_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [transcript_segment_to_dict(segment) for segment in list_transcript_segments(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/meetings/{meeting_id}/speaker-labels")
def get_speaker_labels_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [speaker_label_to_dict(label) for label in list_speaker_labels(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/meetings/{meeting_id}/artifacts/{artifact_format}")
def get_artifact_endpoint(meeting_id: UUID, artifact_format: str, session: Session = Depends(get_session)) -> FileResponse:
    if artifact_format not in {"json", "txt", "srt", "md"}:
        raise HTTPException(status_code=400, detail="artifact_format must be json, txt, srt, or md")
    try:
        meeting = get_meeting(session, meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    path_by_format = {
        "json": meeting.transcript_json_path,
        "txt": meeting.transcript_txt_path,
        "srt": meeting.transcript_srt_path,
        "md": meeting.transcript_md_path,
    }
    artifact_path = path_by_format[artifact_format]
    if artifact_path is None or not Path(artifact_path).exists():
        raise HTTPException(status_code=404, detail=f"{artifact_format} artifact not ready")

    media_type_by_format = {
        "json": "application/json",
        "txt": "text/plain",
        "srt": "application/x-subrip",
        "md": "text/markdown",
    }
    return FileResponse(
        artifact_path,
        media_type=media_type_by_format[artifact_format],
        filename=f"{meeting.title}.{artifact_format}",
    )


@app.get("/meetings/{meeting_id}/action-items")
def get_action_items_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [action_item_to_dict(item) for item in list_action_items(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/meetings/{meeting_id}/decisions")
def get_decisions_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [decision_to_dict(decision) for decision in list_decisions(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/meetings/{meeting_id}/topics")
def get_topics_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [topic_to_dict(topic) for topic in list_topics(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/meetings/{meeting_id}")
def delete_meeting_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        delete_meeting(session, meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if settings.rag_enabled:
        remove_meeting_index.apply_async(args=[str(meeting_id)])
    return {"meeting_id": str(meeting_id), "status": "deleted"}


@app.post("/meetings/{meeting_id}/privacy/purge-raw-audio")
def purge_raw_audio_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> dict[str, str | bool | None]:
    try:
        existed = purge_raw_audio(session, meeting_id)
        meeting = get_meeting(session, meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "meeting_id": str(meeting_id),
        "raw_audio_deleted": True,
        "raw_audio_previously_existed": existed,
        "raw_audio_deleted_at": meeting.raw_audio_deleted_at.isoformat() if meeting.raw_audio_deleted_at else None,
    }


@app.post("/meetings/{meeting_id}/retention")
def set_retention_endpoint(meeting_id: UUID, body: dict, session: Session = Depends(get_session)) -> dict:
    raw_days = body.get("retention_days")
    if raw_days is None:
        raise HTTPException(status_code=400, detail="retention_days is required")
    try:
        retention_days = int(raw_days)
        meeting = set_meeting_retention_days(session, meeting_id, retention_days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="retention_days must be an integer") from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return meeting_to_dict(meeting)


@app.post("/privacy/cleanup-expired")
def cleanup_expired_endpoint(session: Session = Depends(get_session)) -> dict[str, object]:
    deleted_ids = cleanup_expired_meetings(session)
    if settings.rag_enabled:
        for meeting_id in deleted_ids:
            remove_meeting_index.apply_async(args=[meeting_id])
    return {"deleted_meeting_ids": deleted_ids, "deleted_count": len(deleted_ids)}


def parse_query_request(body: dict) -> tuple[str, int, list[str] | None]:
    query = str(body.get("query", "")).strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    top_k = int(body.get("top_k", 5))
    top_k = max(1, min(top_k, 10))
    raw_meeting_ids = body.get("meeting_ids")
    meeting_ids = [str(value) for value in raw_meeting_ids] if isinstance(raw_meeting_ids, list) else None
    return query, top_k, meeting_ids


@app.post("/knowledge/query")
def query_knowledge(body: dict) -> dict:
    if not settings.rag_enabled:
        raise HTTPException(status_code=503, detail="RAG is disabled")
    query, top_k, meeting_ids = parse_query_request(body)
    return query_markdown_knowledge(query, top_k=top_k, meeting_ids=meeting_ids)


@app.post("/query")
def query_all_meetings(body: dict) -> dict:
    if not settings.rag_enabled:
        raise HTTPException(status_code=503, detail="RAG is disabled")
    query, top_k, meeting_ids = parse_query_request(body)
    return query_markdown_knowledge(query, top_k=top_k, meeting_ids=meeting_ids)


@app.post("/meetings/{meeting_id}/query")
def query_one_meeting(meeting_id: UUID, body: dict, session: Session = Depends(get_session)) -> dict:
    if not settings.rag_enabled:
        raise HTTPException(status_code=503, detail="RAG is disabled")
    try:
        get_meeting(session, meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    query, top_k, _meeting_ids = parse_query_request(body)
    return query_single_meeting(meeting_id, query, top_k=top_k)


def main() -> None:
    uvicorn.run(
        "meeting_intelligence_engine.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
