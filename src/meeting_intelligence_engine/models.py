from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from meeting_intelligence_engine.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Meeting(Base):
    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="upload", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    processing_stage: Mapped[str] = mapped_column(String(64), default="uploaded", nullable=False)
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    raw_audio_path: Mapped[str] = mapped_column(Text, nullable=False)
    processed_audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_json_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_txt_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_srt_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_md_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_audio_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    transcripts: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.start_time",
    )
    action_items: Mapped[list[ActionItem]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    decisions: Mapped[list[Decision]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    topics: Mapped[list[Topic]] = relationship(back_populates="meeting", cascade="all, delete-orphan")
    speaker_labels: Mapped[list[SpeakerLabel]] = relationship(
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="SpeakerLabel.speaker_id",
    )


class TranscriptSegment(Base):
    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    speaker_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    speaker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    words: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="transcripts")


Index("ix_transcripts_meeting_start", TranscriptSegment.meeting_id, TranscriptSegment.start_time)


class ActionItem(Base):
    __tablename__ = "action_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assignee_inferred: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deadline: Mapped[str | None] = mapped_column(String(32), nullable=True)
    priority: Mapped[str] = mapped_column(String(32), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="action_items")


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    decision_text: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    stakeholders: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="decisions")


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    topic_name: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="topics")


class SpeakerLabel(Base):
    __tablename__ = "speaker_labels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(String(36), ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    speaker_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    speaker_name: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False, default="rule")
    evidence_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    meeting: Mapped[Meeting] = relationship(back_populates="speaker_labels")


Index("ix_speaker_labels_meeting_speaker", SpeakerLabel.meeting_id, SpeakerLabel.speaker_id, unique=True)
