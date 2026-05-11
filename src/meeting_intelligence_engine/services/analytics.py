from __future__ import annotations

import json
import logging
import re
from uuid import UUID, uuid4

from groq import Groq
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from meeting_intelligence_engine import prompts
from meeting_intelligence_engine.config import Settings, settings
from meeting_intelligence_engine.core.schemas import AnalyticsResult
from meeting_intelligence_engine.models import ActionItem, Decision, Topic, TranscriptSegment
from meeting_intelligence_engine.services.meetings import get_meeting, mark_meeting_completed

logger = logging.getLogger(__name__)


_FLOAT_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def transcript_for_analytics(session: Session, meeting_id: UUID) -> str:
    segments = _transcript_segments(session, meeting_id)
    lines = [
        f"[{segment.start_time:.2f}s - {segment.end_time:.2f}s] {segment.speaker_name or segment.speaker_id}: {segment.text}"
        for segment in segments
        if segment.text.strip()
    ]
    return "\n".join(lines)


def _transcript_segments(session: Session, meeting_id: UUID) -> list[TranscriptSegment]:
    return session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.meeting_id == str(meeting_id))
        .order_by(TranscriptSegment.start_time)
    ).all()


def _groq_client(config: Settings = settings) -> Groq:
    if not config.groq_api_key:
        raise RuntimeError("Missing GROQ_API_KEY")
    return Groq(api_key=config.secret("groq_api_key"))


def _request_json(messages: list[dict[str, str]], config: Settings = settings) -> dict:
    client = _groq_client(config)
    logger.info("analytics LLM call model=%s prompt_version=%s", config.analytics_model_name, prompts.PROMPT_VERSION)
    response = client.chat.completions.create(
        model=config.analytics_model_name,
        temperature=0.0,
        response_format={"type": "json_object"},
        messages=messages,
    )
    content = response.choices[0].message.content or "{}"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid analytics JSON from LLM: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Invalid analytics JSON from LLM: top-level response was not an object")
    return payload


def _extract_topics_only(transcript_text: str, config: Settings = settings) -> list[dict]:
    payload = _request_json(
        [
            {"role": "system", "content": prompts.ANALYTICS_TOPICS_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Transcript:\n{transcript_text}\n\n"
                    f"Return JSON shaped like:\n{prompts.ANALYTICS_TOPICS_USER_EXAMPLE}"
                ),
            },
        ],
        config,
    )
    sanitized = sanitize_analytics_payload({"topics": payload.get("topics") or []})
    return sanitized["topics"]


def extract_analytics(transcript_text: str, config: Settings = settings) -> AnalyticsResult:
    payload = _request_json(
        [
            {"role": "system", "content": prompts.ANALYTICS_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Transcript:\n{transcript_text}\n\n"
                    f"Return JSON shaped like:\n{json.dumps(prompts.ANALYTICS_JSON_TEMPLATE)}"
                ),
            },
        ],
        config,
    )
    sanitized = sanitize_analytics_payload(payload)
    if not sanitized["topics"]:
        sanitized["topics"] = _extract_topics_only(transcript_text, config)
    try:
        return AnalyticsResult.model_validate(sanitized)
    except ValidationError as exc:
        raise RuntimeError(f"Invalid analytics JSON from LLM: {exc}") from exc


def _coerce_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        if any(separator in stripped for separator in (":", "/")) and not stripped.endswith("s"):
            return None
        match = _FLOAT_PATTERN.search(stripped)
        if match:
            try:
                return float(match.group(0))
            except ValueError:
                return None
    return None


def _coerce_string(value: object, default: str | None = None) -> str | None:
    if value is None:
        return default
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or default
    return str(value).strip() or default


def _coerce_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in (_coerce_string(item) for item in value) if item]
    if isinstance(value, str):
        normalized = value.replace(" and ", ",")
        return [part.strip() for part in normalized.split(",") if part.strip()]
    coerced = _coerce_string(value)
    return [coerced] if coerced else []


def sanitize_analytics_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    action_items = []
    for item in payload.get("action_items") or []:
        if isinstance(item, dict) and item.get("description"):
            action_items.append(
                {
                    "description": _coerce_string(item.get("description"), "") or "",
                    "assignee_inferred": _coerce_string(item.get("assignee_inferred")),
                    "deadline": _coerce_string(item.get("deadline")),
                    "priority": _coerce_string(item.get("priority"), "medium") or "medium",
                    "confidence": _coerce_float(item.get("confidence")) or 0.0,
                    "timestamp": _coerce_float(item.get("timestamp")),
                }
            )

    decisions = []
    for decision in payload.get("decisions") or []:
        if isinstance(decision, dict) and decision.get("decision_text"):
            decisions.append(
                {
                    "decision_text": _coerce_string(decision.get("decision_text"), "") or "",
                    "context": _coerce_string(decision.get("context")),
                    "stakeholders": _coerce_string_list(decision.get("stakeholders")),
                    "timestamp": _coerce_float(decision.get("timestamp")),
                    "confidence": _coerce_float(decision.get("confidence")) or 0.0,
                }
            )

    topics = []
    for topic in payload.get("topics") or []:
        if not isinstance(topic, dict) or not topic.get("topic_name"):
            continue
        start_time = _coerce_float(topic.get("start_time"))
        end_time = _coerce_float(topic.get("end_time"))
        if start_time is None or end_time is None:
            continue
        topics.append(
            {
                "topic_name": _coerce_string(topic.get("topic_name"), "") or "",
                "start_time": start_time,
                "end_time": end_time,
                "keywords": _coerce_string_list(topic.get("keywords")),
                "confidence": _coerce_float(topic.get("confidence")) or 0.0,
            }
        )

    return {"action_items": action_items, "decisions": decisions, "topics": topics}


def process_analytics(session: Session, meeting_id: UUID, config: Settings = settings) -> None:
    get_meeting(session, meeting_id)
    transcript_text = transcript_for_analytics(session, meeting_id)
    if not transcript_text.strip():
        raise RuntimeError(f"No transcript text available for meeting {meeting_id}")
    try:
        result = extract_analytics(transcript_text, config)
    except RuntimeError as exc:
        logger.warning("analytics extraction failed for meeting %s; storing empty result: %s", meeting_id, exc)
        result = AnalyticsResult()
    enrich_analytics_from_transcript(session, meeting_id, result)
    save_analytics(session, meeting_id, result)
    mark_meeting_completed(session, meeting_id)


def enrich_analytics_from_transcript(session: Session, meeting_id: UUID, result: AnalyticsResult) -> None:
    segments = _transcript_segments(session, meeting_id)
    if not segments:
        return
    for decision in result.decisions:
        if decision.timestamp is not None:
            nearby = [
                segment
                for segment in segments
                if segment.start_time <= decision.timestamp + 20
                and segment.end_time >= max(0.0, decision.timestamp - 20)
            ]
        else:
            nearby = [segment for segment in segments if decision.decision_text.lower()[:40] in segment.text.lower()]
            if not nearby:
                nearby = segments[:3]
        if not decision.context:
            context_parts = [segment.text.strip() for segment in nearby[:2] if segment.text.strip()]
            if context_parts:
                decision.context = " ".join(context_parts)
        if not decision.stakeholders:
            stakeholders = []
            for segment in nearby[:3]:
                speaker = segment.speaker_name or segment.speaker_id
                if speaker and speaker not in stakeholders:
                    stakeholders.append(speaker)
            decision.stakeholders = stakeholders


def save_analytics(session: Session, meeting_id: UUID, result: AnalyticsResult) -> None:
    meeting_id_str = str(meeting_id)
    session.execute(delete(ActionItem).where(ActionItem.meeting_id == meeting_id_str))
    session.execute(delete(Decision).where(Decision.meeting_id == meeting_id_str))
    session.execute(delete(Topic).where(Topic.meeting_id == meeting_id_str))

    for item in result.action_items:
        session.add(
            ActionItem(
                id=str(uuid4()),
                meeting_id=meeting_id_str,
                description=item.description,
                assignee_inferred=item.assignee_inferred,
                deadline=item.deadline,
                priority=item.priority,
                confidence=item.confidence,
                timestamp=item.timestamp,
            )
        )
    for decision in result.decisions:
        session.add(
            Decision(
                id=str(uuid4()),
                meeting_id=meeting_id_str,
                decision_text=decision.decision_text,
                context=decision.context,
                stakeholders=decision.stakeholders,
                timestamp=decision.timestamp,
                confidence=decision.confidence,
            )
        )
    for topic in result.topics:
        session.add(
            Topic(
                id=str(uuid4()),
                meeting_id=meeting_id_str,
                topic_name=topic.topic_name,
                start_time=topic.start_time,
                end_time=topic.end_time,
                keywords=topic.keywords,
                confidence=topic.confidence,
            )
        )
    session.commit()


def list_action_items(session: Session, meeting_id: UUID) -> list[ActionItem]:
    get_meeting(session, meeting_id)
    return list(session.scalars(select(ActionItem).where(ActionItem.meeting_id == str(meeting_id))))


def list_decisions(session: Session, meeting_id: UUID) -> list[Decision]:
    get_meeting(session, meeting_id)
    return list(session.scalars(select(Decision).where(Decision.meeting_id == str(meeting_id))))


def list_topics(session: Session, meeting_id: UUID) -> list[Topic]:
    get_meeting(session, meeting_id)
    return list(session.scalars(select(Topic).where(Topic.meeting_id == str(meeting_id)).order_by(Topic.start_time)))


def action_item_to_dict(item: ActionItem) -> dict:
    return {
        "id": item.id,
        "meeting_id": item.meeting_id,
        "description": item.description,
        "assignee_inferred": item.assignee_inferred,
        "deadline": item.deadline,
        "priority": item.priority,
        "status": item.status,
        "confidence": item.confidence,
        "timestamp": item.timestamp,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def decision_to_dict(decision: Decision) -> dict:
    return {
        "id": decision.id,
        "meeting_id": decision.meeting_id,
        "decision_text": decision.decision_text,
        "context": decision.context,
        "stakeholders": decision.stakeholders,
        "timestamp": decision.timestamp,
        "confidence": decision.confidence,
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


def topic_to_dict(topic: Topic) -> dict:
    return {
        "id": topic.id,
        "meeting_id": topic.meeting_id,
        "topic_name": topic.topic_name,
        "start_time": topic.start_time,
        "end_time": topic.end_time,
        "keywords": topic.keywords,
        "confidence": topic.confidence,
        "created_at": topic.created_at.isoformat() if topic.created_at else None,
    }
