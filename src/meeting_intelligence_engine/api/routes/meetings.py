from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from meeting_intelligence_engine.api.deps import get_session, require_api_key
from meeting_intelligence_engine.api.schemas import RetentionRequest
from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.services.analytics import (
    action_item_to_dict,
    decision_to_dict,
    list_action_items,
    list_decisions,
    list_topics,
    topic_to_dict,
)
from meeting_intelligence_engine.services.meetings import (
    create_meeting_from_file,
    delete_meeting,
    get_meeting,
    get_transcript,
    list_meetings,
    list_transcript_segments,
    meeting_to_dict,
    purge_raw_audio,
    set_meeting_job_id,
    set_meeting_retention_days,
    transcript_segment_to_dict,
)
from meeting_intelligence_engine.services.speaker_labels import list_speaker_labels, speaker_label_to_dict
from meeting_intelligence_engine.workers.indexing import remove_meeting_index
from meeting_intelligence_engine.workers.transcription import transcribe_meeting

router = APIRouter(prefix="/meetings", tags=["meetings"])

ARTIFACT_MEDIA_TYPES = {
    "json": "application/json",
    "txt": "text/plain",
    "srt": "application/x-subrip",
    "md": "text/markdown",
}


@router.post("/upload", dependencies=[Depends(require_api_key)])
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


@router.get("")
def list_meetings_endpoint(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> list[dict]:
    return [meeting_to_dict(meeting) for meeting in list_meetings(session, limit=limit, offset=offset)]


@router.get("/{meeting_id}")
def get_meeting_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> dict:
    try:
        return meeting_to_dict(get_meeting(session, meeting_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{meeting_id}/transcript")
def get_transcript_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> dict:
    try:
        transcript = get_transcript(session, meeting_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for segment in transcript.get("segments", []):
        segment["display_speaker"] = segment.get("speaker_name") or segment.get("speaker_id")
    return transcript


@router.get("/{meeting_id}/segments")
def get_segments_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [transcript_segment_to_dict(segment) for segment in list_transcript_segments(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{meeting_id}/speaker-labels")
def get_speaker_labels_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [speaker_label_to_dict(label) for label in list_speaker_labels(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{meeting_id}/artifacts/{artifact_format}")
def get_artifact_endpoint(
    meeting_id: UUID, artifact_format: str, session: Session = Depends(get_session)
) -> FileResponse:
    if artifact_format not in ARTIFACT_MEDIA_TYPES:
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
    return FileResponse(
        artifact_path,
        media_type=ARTIFACT_MEDIA_TYPES[artifact_format],
        filename=f"{meeting.title}.{artifact_format}",
    )


@router.get("/{meeting_id}/action-items")
def get_action_items_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [action_item_to_dict(item) for item in list_action_items(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{meeting_id}/decisions")
def get_decisions_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [decision_to_dict(decision) for decision in list_decisions(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{meeting_id}/topics")
def get_topics_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    try:
        return [topic_to_dict(topic) for topic in list_topics(session, meeting_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{meeting_id}", dependencies=[Depends(require_api_key)])
def delete_meeting_endpoint(meeting_id: UUID, session: Session = Depends(get_session)) -> dict[str, str]:
    try:
        delete_meeting(session, meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if settings.rag_enabled:
        remove_meeting_index.apply_async(args=[str(meeting_id)])
    return {"meeting_id": str(meeting_id), "status": "deleted"}


@router.post("/{meeting_id}/privacy/purge-raw-audio", dependencies=[Depends(require_api_key)])
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


@router.post("/{meeting_id}/retention", dependencies=[Depends(require_api_key)])
def set_retention_endpoint(meeting_id: UUID, body: RetentionRequest, session: Session = Depends(get_session)) -> dict:
    try:
        meeting = set_meeting_retention_days(session, meeting_id, body.retention_days)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return meeting_to_dict(meeting)
