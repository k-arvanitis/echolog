from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from meeting_intelligence_engine.audio import normalize_audio, validate_audio
from uuid import uuid4

from meeting_intelligence_engine.core.schemas import ASRSegment, AnalyticsResult, SpeakerSegment, TranscriptResult, TranscriptSegment, Word
from meeting_intelligence_engine.implementations.local_pipeline import TimeOverlapAlignment, clean_transcript_segments
from meeting_intelligence_engine.services.analytics import extract_analytics, sanitize_analytics_payload
from meeting_intelligence_engine.services.segment_repairs import repair_intro_fragments
from meeting_intelligence_engine.services.speaker_labels import apply_speaker_labels, infer_speaker_labels


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required")
def test_validate_and_normalize_audio_accepts_mp3(tmp_path: Path) -> None:
    mp3 = tmp_path / "meeting.mp3"
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
            str(mp3),
        ],
        check=True,
    )

    duration = validate_audio(mp3, max_size_mb=10, max_duration_seconds=10)
    wav = tmp_path / "audio.wav"
    normalize_audio(mp3, wav)

    assert duration > 0
    assert wav.exists()


def test_time_overlap_alignment_assigns_words_to_speakers() -> None:
    asr_segments = [
        ASRSegment(
            text="hello there next speaker",
            start=0.0,
            end=4.0,
            words=[
                Word(text="hello", start=0.0, end=0.5),
                Word(text="there", start=0.6, end=1.0),
                Word(text="next", start=2.1, end=2.6),
                Word(text="speaker", start=2.7, end=3.2),
            ],
        )
    ]
    speaker_segments = [
        SpeakerSegment(speaker_id="SPEAKER_00", start=0.0, end=1.5),
        SpeakerSegment(speaker_id="SPEAKER_01", start=2.0, end=4.0),
    ]

    aligned = TimeOverlapAlignment().align(asr_segments, speaker_segments)

    assert [(segment.speaker_id, segment.text) for segment in aligned] == [
        ("SPEAKER_00", "hello there"),
        ("SPEAKER_01", "next speaker"),
    ]


def test_clean_transcript_segments_drops_empty_and_merges_tiny_fragment() -> None:
    aligned = TimeOverlapAlignment().align(
        [
            ASRSegment(text="I", start=1.0, end=1.2, words=[Word(text="I", start=1.0, end=1.2)]),
            ASRSegment(text="think this is fine", start=1.2, end=3.0, words=[]),
            ASRSegment(text="", start=3.1, end=4.0, words=[]),
        ],
        [
            SpeakerSegment(speaker_id="SPEAKER_00", start=1.0, end=1.2),
            SpeakerSegment(speaker_id="SPEAKER_01", start=1.2, end=3.0),
            SpeakerSegment(speaker_id="SPEAKER_02", start=3.1, end=4.0),
        ],
    )

    cleaned = clean_transcript_segments(aligned)

    assert [(segment.speaker_id, segment.text) for segment in cleaned] == [
        ("SPEAKER_01", "I think this is fine")
    ]


def test_sanitize_analytics_payload_coerces_sloppy_llm_types() -> None:
    payload = {
        "action_items": [
            {
                "description": "Follow up with parking vendor",
                "assignee_inferred": "SPEAKER_01",
                "priority": None,
                "confidence": "0.82",
                "timestamp": "2023-02-15 14:30:00",
            }
        ],
        "decisions": [
            {
                "decision_text": "Keep parking reimbursement policy",
                "context": "Budget discussion",
                "stakeholders": "Management and staff",
                "timestamp": "24.90s",
                "confidence": "0.74",
            }
        ],
        "topics": [
            {
                "topic_name": "Parking",
                "start_time": "24.90s",
                "end_time": "45.50s",
                "keywords": "parking, reimbursement",
                "confidence": "0.66",
            }
        ],
    }

    result = AnalyticsResult.model_validate(sanitize_analytics_payload(payload))

    assert result.action_items[0].priority == "medium"
    assert result.action_items[0].timestamp is None
    assert result.decisions[0].stakeholders == ["Management", "staff"]
    assert result.decisions[0].timestamp == 24.9
    assert result.topics[0].start_time == 24.9
    assert result.topics[0].keywords == ["parking", "reimbursement"]


def test_infer_speaker_labels_from_self_introduction() -> None:
    transcript = TranscriptResult(
        meeting_id=uuid4(),
        speakers=["SPEAKER_00", "SPEAKER_01"],
        segments=[
            TranscriptSegment(speaker_id="SPEAKER_00", start_time=0.0, end_time=1.0, text="Hi, I'm Jason Somerville."),
            TranscriptSegment(speaker_id="SPEAKER_01", start_time=1.0, end_time=2.0, text="Let's begin."),
        ],
        metadata={},
    )

    labels = infer_speaker_labels(transcript)
    apply_speaker_labels(transcript, labels)

    assert labels["SPEAKER_00"].speaker_name == "Jason Somerville"
    assert transcript.segments[0].speaker_name == "Jason Somerville"
    assert transcript.segments[1].speaker_name is None


def test_infer_speaker_labels_prefers_complete_intro_over_truncated_fragment() -> None:
    transcript = TranscriptResult(
        meeting_id=uuid4(),
        speakers=["SPEAKER_01"],
        segments=[
            TranscriptSegment(speaker_id="SPEAKER_01", start_time=0.0, end_time=1.0, text="I'm Lucy Strokes, PA to Rita."),
            TranscriptSegment(speaker_id="SPEAKER_01", start_time=1.1, end_time=1.8, text="I'm Sue Carpenter with a"),
        ],
        metadata={},
    )

    labels = infer_speaker_labels(transcript)

    assert labels["SPEAKER_01"].speaker_name == "Lucy Strokes"


def test_apply_speaker_labels_drops_conflicting_truncated_intro_from_display() -> None:
    transcript = TranscriptResult(
        meeting_id=uuid4(),
        speakers=["SPEAKER_01"],
        segments=[
            TranscriptSegment(speaker_id="SPEAKER_01", start_time=0.0, end_time=1.0, text="I'm Lucy Strokes, PA to Rita."),
            TranscriptSegment(speaker_id="SPEAKER_01", start_time=1.1, end_time=1.8, text="I'm Sue Carpenter with a"),
        ],
        metadata={},
    )

    labels = infer_speaker_labels(transcript)
    apply_speaker_labels(transcript, labels)

    assert transcript.segments[0].speaker_name == "Lucy Strokes"
    assert transcript.segments[1].speaker_name is None


def test_infer_speaker_labels_rejects_role_titles_as_names() -> None:
    transcript = TranscriptResult(
        meeting_id=uuid4(),
        speakers=["SPEAKER_02"],
        segments=[
            TranscriptSegment(speaker_id="SPEAKER_02", start_time=0.0, end_time=1.0, text="I'm the sales director."),
        ],
        metadata={},
    )

    labels = infer_speaker_labels(transcript)

    assert labels == {}


def test_repair_intro_fragments_merges_broken_adjacent_intro_turns() -> None:
    transcript = TranscriptResult(
        meeting_id=uuid4(),
        speakers=["SPEAKER_01", "SPEAKER_02"],
        segments=[
            TranscriptSegment(speaker_id="SPEAKER_01", start_time=80.3, end_time=82.28, text="I'm Lucy Strokes, PA to Rita."),
            TranscriptSegment(speaker_id="SPEAKER_01", start_time=83.46, end_time=84.96, text="I'm Sue Carpenter with a"),
            TranscriptSegment(speaker_id="SPEAKER_02", start_time=84.96, end_time=87.02, text="D and I'm the sales director."),
        ],
        metadata={},
    )

    repair_intro_fragments(transcript)

    assert len(transcript.segments) == 2
    assert transcript.segments[1].speaker_id == "SPEAKER_01"
    assert transcript.segments[1].text == "I'm Sue Carpenter with a D and I'm the sales director."


def test_repair_intro_fragments_moves_short_leading_sentence_to_previous_segment() -> None:
    transcript = TranscriptResult(
        meeting_id=uuid4(),
        speakers=["SPEAKER_04", "SPEAKER_02"],
        segments=[
            TranscriptSegment(speaker_id="SPEAKER_04", start_time=159.9, end_time=162.76, text="I got held up in a previous"),
            TranscriptSegment(
                speaker_id="SPEAKER_02",
                start_time=162.76,
                end_time=171.08,
                text="meeting. Okay, it's okay. We're just discussing car parking Right.",
            ),
        ],
        metadata={},
    )

    repair_intro_fragments(transcript)

    assert len(transcript.segments) == 2
    assert transcript.segments[0].text == "I got held up in a previous meeting."
    assert transcript.segments[1].text == "Okay, it's okay. We're just discussing car parking Right."


def test_extract_analytics_uses_topic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        {"action_items": [], "decisions": [], "topics": []},
        {
            "topics": [
                {
                    "topic_name": "Parking",
                    "start_time": 120.5,
                    "end_time": 240.0,
                    "keywords": ["parking", "spaces"],
                    "confidence": 0.82,
                }
            ]
        },
    ]

    monkeypatch.setattr(
        "meeting_intelligence_engine.services.analytics._request_json",
        lambda _messages, config=None: responses.pop(0),
    )

    result = extract_analytics("[120.50s - 240.00s] SPEAKER_00: We are discussing parking.")

    assert result.topics[0].topic_name == "Parking"
    assert result.topics[0].start_time == 120.5


def test_sanitize_analytics_payload_keeps_decision_context_when_present() -> None:
    payload = {
        "decisions": [
            {
                "decision_text": "Discuss cleanliness problem",
                "context": "They agreed to schedule a dedicated follow-up meeting.",
                "stakeholders": [],
                "timestamp": 833.66,
                "confidence": 0.73,
            }
        ]
    }

    result = AnalyticsResult.model_validate(sanitize_analytics_payload(payload))

    assert result.decisions[0].context == "They agreed to schedule a dedicated follow-up meeting."
