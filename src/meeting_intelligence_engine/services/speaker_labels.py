from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from groq import Groq
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from meeting_intelligence_engine import prompts
from meeting_intelligence_engine.config import Settings, settings
from meeting_intelligence_engine.core.schemas import TranscriptResult
from meeting_intelligence_engine.models import Meeting, SpeakerLabel

logger = logging.getLogger(__name__)


INTRO_PATTERNS = [
    re.compile(
        r"\b(?:hi|hello|hey|good morning|good afternoon|good evening)[,\s]+(?:i am|i'm|my name is|this is)\s+"
        r"(?P<name>[A-Z][A-Za-z'`-]+(?:\s+[A-Z][A-Za-z'`-]+){0,2})(?=[,.;]|(?:\s+(?:and|from|with|the|your)\b)|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:i am|i'm|my name is|this is)\s+"
        r"(?P<name>[A-Z][A-Za-z'`-]+(?:\s+[A-Z][A-Za-z'`-]+){0,2})(?=[,.;]|(?:\s+(?:and|from|with|the|your)\b)|$)",
        re.IGNORECASE,
    ),
]

NON_PERSON_TOKENS = {
    "the",
    "a",
    "an",
    "director",
    "manager",
    "assistant",
    "officer",
    "lead",
    "head",
    "team",
    "staff",
    "department",
    "sales",
    "marketing",
    "operations",
    "finance",
    "product",
    "engineering",
    "hr",
    "human",
    "resources",
    "in",
    "on",
    "at",
    "to",
    "of",
    "for",
    "with",
    "by",
    "from",
    "as",
    "and",
    "or",
    "but",
    "if",
    "not",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "should",
    "could",
    "can",
    "may",
    "might",
    "must",
    "going",
    "update",
    "line",
    "out",
    "up",
    "down",
    "off",
    "over",
    "under",
    "again",
    "more",
    "less",
    "now",
    "then",
    "here",
    "there",
    "where",
    "when",
    "how",
    "why",
    "who",
    "what",
    "which",
    "this",
    "that",
    "these",
    "those",
    "all",
    "any",
    "some",
    "no",
    "yes",
    "ok",
    "okay",
    "yeah",
    "uh",
    "um",
}

_NAME_TOKEN_RE = re.compile(r"^[A-Z][a-zA-Z'\-]{1,}$")


@dataclass
class SpeakerLabelCandidate:
    speaker_id: str
    speaker_name: str
    confidence: float
    method: str
    evidence_text: str | None
    evidence_start_time: float | None


def _normalize_name(name: str) -> str:
    parts = [part for part in re.split(r"\s+", name.strip()) if part]
    return " ".join(part[:1].upper() + part[1:] for part in parts)


def _looks_like_person_name(name: str) -> bool:
    tokens = [token.strip(".,") for token in name.split() if token.strip(".,")]
    if not tokens or len(tokens) > 3:
        return False
    if any(token.lower() in NON_PERSON_TOKENS for token in tokens):
        return False
    if not all(_NAME_TOKEN_RE.match(token) for token in tokens):
        return False
    return True


def _segment_intro_candidate(
    speaker_id: str, text: str, start_time: float | None = None
) -> SpeakerLabelCandidate | None:
    stripped = text.strip()
    if not stripped:
        return None
    for pattern in INTRO_PATTERNS:
        match = pattern.search(stripped)
        if not match:
            continue
        speaker_name = _normalize_name(match.group("name"))
        if not _looks_like_person_name(speaker_name):
            return None
        return SpeakerLabelCandidate(
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            confidence=_candidate_confidence(stripped, match),
            method="rule",
            evidence_text=stripped,
            evidence_start_time=start_time,
        )
    return None


def _candidate_confidence(text: str, match: re.Match[str]) -> float:
    confidence = 0.9
    stripped = text.strip()
    if stripped.endswith((".", "!", "?")):
        confidence += 0.06
    trailing = stripped[match.end() :].strip().lower()
    if trailing.startswith(","):
        confidence += 0.04
    if re.search(r"\b(with|and|for|to|of|the|a|an)\s*$", stripped.lower()):
        confidence -= 0.35
    if len(stripped.split()) <= 4 and not stripped.endswith((".", "!", "?")):
        confidence -= 0.2
    return max(0.0, min(0.99, confidence))


def _extract_rule_candidates(
    transcript: TranscriptResult,
    max_segments: int = 40,
) -> tuple[dict[str, SpeakerLabelCandidate], set[str]]:
    candidates: dict[str, list[SpeakerLabelCandidate]] = {}
    for segment in transcript.segments[:max_segments]:
        if segment.speaker_name:
            continue
        candidate = _segment_intro_candidate(segment.speaker_id, segment.text, segment.start_time)
        if candidate:
            candidates.setdefault(segment.speaker_id, []).append(candidate)

    resolved: dict[str, SpeakerLabelCandidate] = {}
    blocked: set[str] = set()
    for speaker_id, options in candidates.items():
        best_by_name: dict[str, SpeakerLabelCandidate] = {}
        for option in options:
            current = best_by_name.get(option.speaker_name)
            if current is None or option.confidence > current.confidence:
                best_by_name[option.speaker_name] = option
        ranked = sorted(best_by_name.values(), key=lambda item: item.confidence, reverse=True)
        if not ranked:
            continue
        if len(ranked) == 1:
            if ranked[0].confidence >= 0.75:
                resolved[speaker_id] = ranked[0]
            else:
                blocked.add(speaker_id)
            continue
        if ranked[0].confidence >= 0.9 and ranked[0].confidence - ranked[1].confidence >= 0.2:
            resolved[speaker_id] = ranked[0]
        else:
            blocked.add(speaker_id)
    return resolved, blocked


def _fallback_candidates_with_llm(
    transcript: TranscriptResult,
    unresolved_speaker_ids: list[str],
    config: Settings = settings,
) -> dict[str, SpeakerLabelCandidate]:
    if not unresolved_speaker_ids:
        return {}
    if not config.groq_api_key:
        logger.info(
            "GROQ_API_KEY not set; leaving %d speaker(s) unresolved: %s",
            len(unresolved_speaker_ids),
            ", ".join(unresolved_speaker_ids),
        )
        return {}

    lines = [
        f"[{segment.start_time:.2f}s - {segment.end_time:.2f}s] {segment.speaker_id}: {segment.text}"
        for segment in transcript.segments[:80]
        if segment.text.strip()
    ]
    if not lines:
        return {}

    client = Groq(api_key=config.secret("groq_api_key"))
    logger.info(
        "speaker-label LLM call model=%s prompt_version=%s unresolved=%d",
        config.analytics_model_name,
        prompts.PROMPT_VERSION,
        len(unresolved_speaker_ids),
    )
    response = client.chat.completions.create(
        model=config.analytics_model_name,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompts.SPEAKER_LABEL_SYSTEM},
            {
                "role": "user",
                "content": (
                    "Unresolved speaker IDs:\n"
                    + "\n".join(unresolved_speaker_ids)
                    + "\n\nTranscript excerpt:\n"
                    + "\n".join(lines)
                ),
            },
        ],
    )
    content = response.choices[0].message.content or "{}"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        logger.warning("speaker-label LLM returned invalid JSON: %s", exc)
        return {}

    resolved: dict[str, SpeakerLabelCandidate] = {}
    for item in payload.get("speaker_labels") or []:
        if not isinstance(item, dict):
            continue
        speaker_id = str(item.get("speaker_id") or "").strip()
        speaker_name = _normalize_name(str(item.get("speaker_name") or "").strip())
        confidence = item.get("confidence")
        evidence_text = str(item.get("evidence_text") or "").strip() or None
        if speaker_id not in unresolved_speaker_ids or not speaker_name or not _looks_like_person_name(speaker_name):
            continue
        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError):
            confidence_value = 0.0
        if confidence_value < 0.7:
            continue
        resolved[speaker_id] = SpeakerLabelCandidate(
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            confidence=confidence_value,
            method="llm",
            evidence_text=evidence_text,
            evidence_start_time=None,
        )

    name_counts: dict[str, int] = {}
    for candidate in resolved.values():
        name_counts[candidate.speaker_name] = name_counts.get(candidate.speaker_name, 0) + 1
    deduped = {sid: c for sid, c in resolved.items() if name_counts[c.speaker_name] == 1}
    dropped = len(resolved) - len(deduped)
    if dropped:
        logger.info("dropped %d speaker label(s) due to duplicate-name conflict", dropped)
    return deduped


def infer_speaker_labels(transcript: TranscriptResult, config: Settings = settings) -> dict[str, SpeakerLabelCandidate]:
    resolved, blocked = _extract_rule_candidates(transcript)
    unresolved = [
        speaker_id for speaker_id in transcript.speakers if speaker_id not in resolved and speaker_id not in blocked
    ]
    resolved.update(_fallback_candidates_with_llm(transcript, unresolved, config))
    return resolved


def apply_speaker_labels(transcript: TranscriptResult, labels: dict[str, SpeakerLabelCandidate]) -> TranscriptResult:
    for segment in transcript.segments:
        global_candidate = labels.get(segment.speaker_id)
        local_candidate = _segment_intro_candidate(segment.speaker_id, segment.text, segment.start_time)
        if local_candidate and local_candidate.confidence >= 0.85:
            segment.speaker_name = local_candidate.speaker_name
            continue
        if local_candidate and global_candidate and local_candidate.speaker_name != global_candidate.speaker_name:
            segment.speaker_name = None
            continue
        if global_candidate:
            segment.speaker_name = global_candidate.speaker_name
    return transcript


def save_speaker_labels(session: Session, meeting_id: UUID, labels: dict[str, SpeakerLabelCandidate]) -> None:
    meeting_id_str = str(meeting_id)
    session.execute(delete(SpeakerLabel).where(SpeakerLabel.meeting_id == meeting_id_str))
    for candidate in labels.values():
        session.add(
            SpeakerLabel(
                id=str(uuid4()),
                meeting_id=meeting_id_str,
                speaker_id=candidate.speaker_id,
                speaker_name=candidate.speaker_name,
                confidence=candidate.confidence,
                method=candidate.method,
                evidence_text=candidate.evidence_text,
                evidence_start_time=candidate.evidence_start_time,
            )
        )
    session.commit()


def list_speaker_labels(session: Session, meeting_id: UUID) -> list[SpeakerLabel]:
    if session.get(Meeting, str(meeting_id)) is None:
        raise KeyError(f"Meeting not found: {meeting_id}")
    return list(
        session.scalars(
            select(SpeakerLabel).where(SpeakerLabel.meeting_id == str(meeting_id)).order_by(SpeakerLabel.speaker_id)
        )
    )


def speaker_label_to_dict(label: SpeakerLabel) -> dict:
    return {
        "id": label.id,
        "meeting_id": label.meeting_id,
        "speaker_id": label.speaker_id,
        "speaker_name": label.speaker_name,
        "confidence": label.confidence,
        "method": label.method,
        "evidence_text": label.evidence_text,
        "evidence_start_time": label.evidence_start_time,
        "created_at": label.created_at.isoformat() if label.created_at else None,
    }
