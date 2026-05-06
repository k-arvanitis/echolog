from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MeetingStatus(StrEnum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ProcessingStage(StrEnum):
    uploaded = "uploaded"
    normalizing_audio = "normalizing_audio"
    loading_models = "loading_models"
    transcribing = "transcribing"
    diarizing = "diarizing"
    aligning = "aligning"
    exporting = "exporting"
    extracting_analytics = "extracting_analytics"
    completed = "completed"
    failed = "failed"


class SpeakerSegment(BaseModel):
    speaker_id: str
    start: float
    end: float
    confidence: float = 1.0


class Word(BaseModel):
    text: str
    start: float
    end: float
    confidence: float = 1.0


class ASRSegment(BaseModel):
    text: str
    start: float
    end: float
    words: list[Word] = Field(default_factory=list)


class TranscriptSegment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    speaker_id: str
    speaker_name: str | None = None
    start_time: float
    end_time: float
    text: str
    words: list[Word] = Field(default_factory=list)


class TranscriptResult(BaseModel):
    meeting_id: UUID
    segments: list[TranscriptSegment]
    speakers: list[str]
    metadata: dict[str, str | int | float | bool | None]


class ActionItemExtract(BaseModel):
    description: str
    assignee_inferred: str | None = None
    deadline: str | None = None
    priority: str = "medium"
    confidence: float = 0.0
    timestamp: float | None = None


class DecisionExtract(BaseModel):
    decision_text: str
    context: str | None = None
    stakeholders: list[str] = Field(default_factory=list)
    timestamp: float | None = None
    confidence: float = 0.0


class TopicExtract(BaseModel):
    topic_name: str
    start_time: float
    end_time: float
    keywords: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class AnalyticsResult(BaseModel):
    action_items: list[ActionItemExtract] = Field(default_factory=list)
    decisions: list[DecisionExtract] = Field(default_factory=list)
    topics: list[TopicExtract] = Field(default_factory=list)


class MeetingRecord(BaseModel):
    id: UUID
    title: str
    source_path: Path
    processed_audio_path: Path | None = None
    transcript_path: Path | None = None
    status: MeetingStatus = MeetingStatus.pending
    error_message: str | None = None
    duration_seconds: float | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
