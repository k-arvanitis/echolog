from __future__ import annotations

import re

from meeting_intelligence_engine.core.schemas import TranscriptResult, TranscriptSegment

INTRO_LEAD_RE = re.compile(r"\b(?:i am|i'm|my name is|this is)\b", re.IGNORECASE)
INTRO_FRAGMENT_END_RE = re.compile(
    r"(?:\bwith\s+a\b|\bwith\s+an\b|\bwith\s+the\b|\band\b|\bfrom\b|\bat\b|\bfor\b)\s*[.]?$",
    re.IGNORECASE,
)
INTRO_CONTINUATION_RE = re.compile(
    r"^(?:[A-Z]\b|[a-z]|[A-Z][a-z]+|\s*[A-Z]\b|\s*[a-z]).*(?:\b(?:i'm|i am)\b.*\b(?:director|manager|lead|assistant|officer)\b|"
    r"\b(?:director|manager|lead|assistant|officer|marketing|sales|operations|finance|product|engineering)\b)",
    re.IGNORECASE,
)
DANGLING_END_RE = re.compile(
    r"(?:\b(?:a|an|the|my|your|our|their|this|that|these|those|previous|next|last|first|another|some|any|each|every)\b|"
    r"\b(?:with|from|to|for|of|in|on|at|by)\b)\s*$",
    re.IGNORECASE,
)
LEADING_SENTENCE_RE = re.compile(r"^(?P<prefix>[A-Za-z0-9'`-]+(?:\s+[A-Za-z0-9'`-]+){0,2}[.!?])(?:\s+(?P<rest>.*))?$")


def _is_short(segment: TranscriptSegment, max_duration: float = 3.0, max_words: int = 10) -> bool:
    return (segment.end_time - segment.start_time) <= max_duration or len(segment.text.split()) <= max_words


def _looks_like_intro_fragment(text: str) -> bool:
    stripped = text.strip()
    return bool(INTRO_LEAD_RE.search(stripped) and INTRO_FRAGMENT_END_RE.search(stripped))


def _looks_like_intro_continuation(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    return bool(INTRO_CONTINUATION_RE.search(stripped))


def _merge_segments(left: TranscriptSegment, right: TranscriptSegment) -> TranscriptSegment:
    joined = f"{left.text.rstrip()} {right.text.lstrip()}".strip()
    return TranscriptSegment(
        id=left.id,
        speaker_id=left.speaker_id,
        speaker_name=left.speaker_name,
        start_time=left.start_time,
        end_time=right.end_time,
        text=joined,
        words=[*left.words, *right.words],
    )


def _looks_like_dangling_fragment(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped and not stripped.endswith((".", "!", "?")) and DANGLING_END_RE.search(stripped))


def _split_leading_sentence(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    match = LEADING_SENTENCE_RE.match(stripped)
    if not match:
        return None
    prefix = match.group("prefix").strip()
    rest = (match.group("rest") or "").strip()
    if len(prefix.split()) > 3:
        return None
    return prefix, rest


def _move_leading_prefix(
    left: TranscriptSegment, right: TranscriptSegment, prefix: str, rest: str
) -> tuple[TranscriptSegment, TranscriptSegment | None]:
    merged_left = TranscriptSegment(
        id=left.id,
        speaker_id=left.speaker_id,
        speaker_name=left.speaker_name,
        start_time=left.start_time,
        end_time=right.start_time
        + min(right.end_time - right.start_time, max(0.2, (right.end_time - right.start_time) * 0.2)),
        text=f"{left.text.rstrip()} {prefix}".strip(),
        words=[*left.words],
    )
    if not rest:
        return merged_left, None
    new_right = TranscriptSegment(
        id=right.id,
        speaker_id=right.speaker_id,
        speaker_name=right.speaker_name,
        start_time=merged_left.end_time,
        end_time=right.end_time,
        text=rest,
        words=[*right.words],
    )
    return merged_left, new_right


def repair_intro_fragments(transcript: TranscriptResult, intro_window_seconds: float = 300.0) -> TranscriptResult:
    repaired: list[TranscriptSegment] = []
    index = 0
    segments = transcript.segments
    while index < len(segments):
        current = segments[index]
        next_segment = segments[index + 1] if index + 1 < len(segments) else None
        if (
            next_segment is not None
            and next_segment.start_time - current.end_time <= 0.2
            and _is_short(current, max_duration=3.5, max_words=8)
            and _looks_like_dangling_fragment(current.text)
        ):
            split = _split_leading_sentence(next_segment.text)
            if split is not None:
                prefix, rest = split
                moved_left, moved_right = _move_leading_prefix(current, next_segment, prefix, rest)
                repaired.append(moved_left)
                if moved_right is not None:
                    repaired.append(moved_right)
                index += 2
                continue
        if (
            next_segment is not None
            and current.start_time <= intro_window_seconds
            and next_segment.start_time - current.end_time <= 0.5
            and _is_short(current)
            and _is_short(next_segment, max_duration=3.5, max_words=12)
            and _looks_like_intro_fragment(current.text)
            and _looks_like_intro_continuation(next_segment.text)
        ):
            repaired.append(_merge_segments(current, next_segment))
            index += 2
            continue
        repaired.append(current)
        index += 1
    transcript.segments = repaired
    transcript.speakers = sorted({segment.speaker_id for segment in repaired})
    return transcript
