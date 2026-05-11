"""Centralized LLM prompts.

Everything the models are told to do lives here, not inline at the call sites.
Bump ``PROMPT_VERSION`` whenever any prompt below changes so eval runs and logs
can be correlated with the prompt that produced them.
"""

from __future__ import annotations

PROMPT_VERSION = "2026-05-11"

# Answer returned (and required from the LLM verbatim) when retrieval has no support.
NO_INFO_MESSAGE = "I don't have information about that in the meeting records."

# Shape the analytics extractor must return; embedded in the user message as an example.
ANALYTICS_JSON_TEMPLATE = {
    "action_items": [
        {
            "description": "string",
            "assignee_inferred": "string or null",
            "deadline": "string or null",
            "priority": "low|medium|high",
            "confidence": 0.0,
            "timestamp": 0.0,
        }
    ],
    "decisions": [
        {
            "decision_text": "string",
            "context": "string or null",
            "stakeholders": ["string"],
            "timestamp": 0.0,
            "confidence": 0.0,
        }
    ],
    "topics": [
        {
            "topic_name": "string",
            "start_time": 0.0,
            "end_time": 0.0,
            "keywords": ["string"],
            "confidence": 0.0,
        }
    ],
}

ANALYTICS_SYSTEM = (
    "Extract meeting intelligence from the transcript and return only JSON. "
    "The JSON must contain exactly these keys: action_items, decisions, topics. "
    "Use arrays for all three keys, even if empty. "
    "Timestamps must be numeric seconds copied from the transcript timestamps, not date strings, "
    "not values like '24.90s'. "
    "stakeholders and keywords must be arrays of strings. "
    "priority must be one of low, medium, high. "
    "confidence must be a number from 0 to 1. "
    "For each decision, include a short context sentence explaining what was agreed and who was involved "
    "when that is supported by the transcript. "
    "For each decision, populate stakeholders with the participant names or speaker labels involved "
    "when present in the transcript. "
    "If a field is unknown, use null for scalar fields and [] for list fields. "
    "Do not return prose. Do not wrap JSON in markdown."
)

ANALYTICS_TOPICS_SYSTEM = (
    "Extract only meeting topics from the transcript. Return only valid JSON with one key: topics. "
    "Each topic must be an object with keys topic_name, start_time, end_time, keywords, confidence. "
    "start_time and end_time must be numeric seconds taken from the transcript timestamps, not strings. "
    "keywords must be an array of short strings. confidence must be a number from 0 to 1. "
    "You must return at least one topic when the meeting clearly contains any discussion topic. "
    "Do not return prose. Do not wrap JSON in markdown."
)

ANALYTICS_TOPICS_USER_EXAMPLE = (
    '{"topics":[{"topic_name":"Parking policy","start_time":120.5,"end_time":240.0,'
    '"keywords":["parking","spaces"],"confidence":0.82}]}'
)

SPEAKER_LABEL_SYSTEM = (
    "You resolve diarized speaker IDs to real names only when the transcript explicitly supports it. "
    "Return JSON with one key: speaker_labels. Its value must be a list of objects with keys "
    "speaker_id, speaker_name, confidence, evidence_text. Only include a speaker if the evidence is explicit. "
    "If uncertain, omit it. Do not guess."
)

RAG_ANSWER_SYSTEM = (
    "Answer only from the provided meeting transcript context. "
    "If the answer is not supported by the context, say exactly: "
    f'"{NO_INFO_MESSAGE}" '
    "When you answer, include inline citations like [Source 1]."
)

# Variant used by the RAG eval harness — biased toward terse, gradeable answers.
RAG_EVAL_ANSWER_SYSTEM = (
    "Answer only from the provided meeting transcript context. "
    "Give the most direct answer possible. "
    "For yes/no questions, start with Yes or No. "
    "For who/what/when questions, answer in one short sentence if possible. "
    "If the answer is not supported, say exactly: "
    f'"{NO_INFO_MESSAGE}" '
    "Include inline citations like [Source 1]."
)
