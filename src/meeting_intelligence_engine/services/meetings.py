from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from meeting_intelligence_engine.audio import validate_audio
from meeting_intelligence_engine.config import Settings, settings
from meeting_intelligence_engine.core.schemas import MeetingStatus, ProcessingStage, TranscriptResult
from meeting_intelligence_engine.exporters import read_transcript, write_transcript_outputs
from meeting_intelligence_engine.models import Meeting, TranscriptSegment
from meeting_intelligence_engine.services.segment_repairs import repair_intro_fragments
from meeting_intelligence_engine.services.speaker_labels import apply_speaker_labels, infer_speaker_labels, save_speaker_labels
from meeting_intelligence_engine.services.transcription_stages import (
    ProgressReporter,
    normalize_stage,
    transcribe_and_diarize_stage,
)


def create_meeting_from_file(
    session: Session,
    source_path: Path,
    title: str | None = None,
    config: Settings = settings,
) -> Meeting:
    meeting_id = uuid4()
    meeting_dir = config.data_dir / "meetings" / str(meeting_id)
    raw_path = meeting_dir / "raw" / source_path.name
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, raw_path)
    duration = validate_audio(raw_path, config.max_upload_mb, config.max_duration_seconds)
    retention_until = None
    if config.default_retention_days and config.default_retention_days > 0:
        retention_until = datetime.now(timezone.utc) + timedelta(days=config.default_retention_days)
    meeting = Meeting(
        id=str(meeting_id),
        title=title or source_path.stem,
        source="upload",
        status=MeetingStatus.pending.value,
        processing_stage=ProcessingStage.uploaded.value,
        progress_percent=0.0,
        raw_audio_path=str(raw_path),
        duration_seconds=duration,
        retention_until=retention_until,
    )
    session.add(meeting)
    session.commit()
    session.refresh(meeting)
    return meeting


def get_meeting(session: Session, meeting_id: UUID) -> Meeting:
    meeting = session.get(Meeting, str(meeting_id))
    if meeting is None:
        raise KeyError(f"Meeting not found: {meeting_id}")
    return meeting


def list_meetings(session: Session, limit: int = 100, offset: int = 0) -> list[Meeting]:
    statement = select(Meeting).order_by(Meeting.created_at.desc()).limit(limit).offset(offset)
    return list(session.scalars(statement))


def set_meeting_job_id(session: Session, meeting_id: UUID, job_id: str) -> None:
    meeting = get_meeting(session, meeting_id)
    meeting.job_id = job_id
    session.commit()


def update_progress(
    session: Session,
    meeting: Meeting,
    stage: ProcessingStage,
    progress_percent: float,
    status: MeetingStatus = MeetingStatus.processing,
) -> None:
    meeting.status = status.value
    meeting.processing_stage = stage.value
    meeting.progress_percent = progress_percent
    meeting.error_message = None
    session.commit()


def mark_meeting_failed(session: Session, meeting_id: UUID, error_message: str) -> None:
    meeting = get_meeting(session, meeting_id)
    meeting.status = MeetingStatus.failed.value
    meeting.processing_stage = ProcessingStage.failed.value
    meeting.error_message = error_message
    session.commit()


def process_meeting(session: Session, meeting_id: UUID, config: Settings = settings, mark_failed: bool = True) -> None:
    meeting = get_meeting(session, meeting_id)
    try:
        meeting_dir = Path(meeting.raw_audio_path).parents[1]
        processed_audio_path = meeting_dir / "processed" / "audio.wav"
        progress = ProgressReporter(
            lambda stage, percent: update_progress(session, meeting, stage, percent, MeetingStatus.processing)
        )
        normalize_stage(Path(meeting.raw_audio_path), processed_audio_path, progress)
        meeting.processed_audio_path = str(processed_audio_path)
        session.commit()

        transcript = transcribe_and_diarize_stage(processed_audio_path, meeting_id, config, progress)
        repair_intro_fragments(transcript)
        speaker_labels = infer_speaker_labels(transcript, config)
        apply_speaker_labels(transcript, speaker_labels)
        progress.update(ProcessingStage.exporting, 95)
        transcript_base_path = meeting_dir / "transcript" / "transcript"
        write_transcript_outputs(transcript_base_path, transcript, meeting_title=meeting.title)
        save_transcript(session, meeting, transcript, transcript_base_path, complete=not config.analytics_enabled)
        save_speaker_labels(session, meeting_id, speaker_labels)
        if config.delete_raw_audio_after_processing:
            purge_raw_audio(session, meeting_id)
    except Exception as exc:
        if mark_failed:
            mark_meeting_failed(session, meeting_id, str(exc))
        raise


def save_transcript(
    session: Session,
    meeting: Meeting,
    transcript: TranscriptResult,
    transcript_base_path: Path,
    complete: bool = True,
) -> None:
    session.execute(delete(TranscriptSegment).where(TranscriptSegment.meeting_id == meeting.id))
    for segment in transcript.segments:
        session.add(
            TranscriptSegment(
                id=str(segment.id),
                meeting_id=meeting.id,
                speaker_id=segment.speaker_id,
                speaker_name=segment.speaker_name,
                start_time=segment.start_time,
                end_time=segment.end_time,
                text=segment.text,
                words=[word.model_dump(mode="json") for word in segment.words],
            )
        )
    meeting.transcript_json_path = str(transcript_base_path.with_suffix(".json"))
    meeting.transcript_txt_path = str(transcript_base_path.with_suffix(".txt"))
    meeting.transcript_srt_path = str(transcript_base_path.with_suffix(".srt"))
    meeting.transcript_md_path = str(transcript_base_path.with_suffix(".md"))
    if complete:
        meeting.status = MeetingStatus.completed.value
        meeting.processing_stage = ProcessingStage.completed.value
        meeting.progress_percent = 100.0
        meeting.completed_at = datetime.now(timezone.utc)
    else:
        meeting.status = MeetingStatus.processing.value
        meeting.processing_stage = ProcessingStage.extracting_analytics.value
        meeting.progress_percent = 96.0
    meeting.error_message = None
    session.commit()


def mark_meeting_completed(session: Session, meeting_id: UUID) -> None:
    meeting = get_meeting(session, meeting_id)
    meeting.status = MeetingStatus.completed.value
    meeting.processing_stage = ProcessingStage.completed.value
    meeting.progress_percent = 100.0
    meeting.completed_at = datetime.now(timezone.utc)
    meeting.error_message = None
    session.commit()


def delete_meeting(session: Session, meeting_id: UUID, remove_files: bool = True) -> None:
    meeting = get_meeting(session, meeting_id)
    meeting_dir = Path(meeting.raw_audio_path).parents[1]
    session.delete(meeting)
    session.commit()
    if remove_files:
        shutil.rmtree(meeting_dir, ignore_errors=True)


def purge_raw_audio(session: Session, meeting_id: UUID) -> bool:
    meeting = get_meeting(session, meeting_id)
    raw_path = Path(meeting.raw_audio_path)
    existed = raw_path.exists()
    raw_path.unlink(missing_ok=True)
    meeting.raw_audio_deleted_at = datetime.now(timezone.utc)
    session.commit()
    return existed


def set_meeting_retention_days(session: Session, meeting_id: UUID, retention_days: int | None) -> Meeting:
    meeting = get_meeting(session, meeting_id)
    if retention_days is None or retention_days <= 0:
        meeting.retention_until = None
    else:
        meeting.retention_until = datetime.now(timezone.utc) + timedelta(days=retention_days)
    session.commit()
    session.refresh(meeting)
    return meeting


def cleanup_expired_meetings(session: Session, now: datetime | None = None, remove_files: bool = True) -> list[str]:
    now = now or datetime.now(timezone.utc)
    statement = select(Meeting).where(Meeting.retention_until.is_not(None), Meeting.retention_until <= now)
    meetings = list(session.scalars(statement))
    deleted_ids: list[str] = []
    for meeting in meetings:
        deleted_ids.append(meeting.id)
        meeting_dir = Path(meeting.raw_audio_path).parents[1]
        session.delete(meeting)
        session.flush()
        if remove_files:
            shutil.rmtree(meeting_dir, ignore_errors=True)
    session.commit()
    return deleted_ids


def get_transcript(session: Session, meeting_id: UUID) -> TranscriptResult:
    meeting = get_meeting(session, meeting_id)
    if meeting.transcript_json_path is None:
        raise KeyError(f"Transcript not ready: {meeting_id}")
    return read_transcript(Path(meeting.transcript_json_path))


def list_transcript_segments(session: Session, meeting_id: UUID) -> list[TranscriptSegment]:
    get_meeting(session, meeting_id)
    statement = (
        select(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == str(meeting_id))
        .order_by(TranscriptSegment.start_time)
    )
    return list(session.scalars(statement))


def transcript_segment_to_dict(segment: TranscriptSegment) -> dict:
    return {
        "id": segment.id,
        "meeting_id": segment.meeting_id,
        "speaker_id": segment.speaker_id,
        "speaker_name": segment.speaker_name,
        "display_speaker": segment.speaker_name or segment.speaker_id,
        "start_time": segment.start_time,
        "end_time": segment.end_time,
        "text": segment.text,
        "words": segment.words,
        "created_at": segment.created_at.isoformat() if segment.created_at else None,
    }


def meeting_to_dict(meeting: Meeting) -> dict:
    return {
        "id": meeting.id,
        "title": meeting.title,
        "source": meeting.source,
        "status": meeting.status,
        "processing_stage": meeting.processing_stage,
        "progress_percent": meeting.progress_percent,
        "raw_audio_path": meeting.raw_audio_path,
        "processed_audio_path": meeting.processed_audio_path,
        "transcript_json_path": meeting.transcript_json_path,
        "transcript_txt_path": meeting.transcript_txt_path,
        "transcript_srt_path": meeting.transcript_srt_path,
        "transcript_md_path": meeting.transcript_md_path,
        "duration_seconds": meeting.duration_seconds,
        "error_message": meeting.error_message,
        "job_id": meeting.job_id,
        "retention_until": meeting.retention_until.isoformat() if meeting.retention_until else None,
        "raw_audio_deleted_at": meeting.raw_audio_deleted_at.isoformat() if meeting.raw_audio_deleted_at else None,
        "created_at": meeting.created_at.isoformat() if meeting.created_at else None,
        "completed_at": meeting.completed_at.isoformat() if meeting.completed_at else None,
    }
