from __future__ import annotations

import logging
import time
from uuid import UUID

from groq import Groq
from qdrant_client.models import FieldCondition, Filter, Fusion, FusionQuery, MatchAny, MatchValue, Prefetch

from meeting_intelligence_engine.config import Settings, settings
from meeting_intelligence_engine.rag.embeddings import dense_embed, get_qdrant_client, sparse_embed

logger = logging.getLogger(__name__)

NO_INFO_MESSAGE = "I don't have information about that in the meeting records."


def build_meeting_filter(meeting_ids: list[str] | None = None) -> Filter | None:
    cleaned = [meeting_id for meeting_id in (meeting_ids or []) if meeting_id]
    if not cleaned:
        return None
    if len(cleaned) == 1:
        return Filter(must=[FieldCondition(key="meeting_id", match=MatchValue(value=cleaned[0]))])
    return Filter(must=[FieldCondition(key="meeting_id", match=MatchAny(any=cleaned))])


def retrieve_markdown_sources(query: str, top_k: int = 5, meeting_ids: list[str] | None = None) -> list[dict]:
    query_filter = build_meeting_filter(meeting_ids)
    try:
        result = get_qdrant_client().query_points(
            collection_name=settings.qdrant_collection,
            prefetch=[
                Prefetch(
                    query=dense_embed(f"query: {query}"), using="dense", limit=max(20, top_k * 4), filter=query_filter
                ),
                Prefetch(query=sparse_embed(query), using="sparse", limit=max(20, top_k * 4), filter=query_filter),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
    except Exception:
        logger.exception("retrieval failed for query=%r; returning no sources", query)
        return []
    sources = []
    for point in result.points:
        payload = point.payload or {}
        sources.append(
            {
                "source": payload.get("source"),
                "meeting_id": payload.get("meeting_id"),
                "meeting_title": payload.get("meeting_title"),
                "content": payload.get("content"),
                "score": point.score,
                "start_char": payload.get("start_char"),
                "end_char": payload.get("end_char"),
                "start_time": payload.get("start_time"),
                "end_time": payload.get("end_time"),
                "speakers": payload.get("speakers") or [],
            }
        )
    return sources


def answer_from_sources(query: str, sources: list[dict], config: Settings = settings) -> str:
    if not sources:
        logger.info("no retrieved sources for query=%r", query)
        return NO_INFO_MESSAGE
    if not config.groq_api_key:
        logger.warning("GROQ_API_KEY not set; returning raw source content for query=%r", query)
        return "\n\n".join(source["content"] for source in sources if source.get("content"))

    context_blocks = []
    for index, source in enumerate(sources, start=1):
        citation = []
        if source.get("meeting_title"):
            citation.append(f"meeting={source['meeting_title']}")
        if source.get("meeting_id"):
            citation.append(f"id={source['meeting_id']}")
        if source.get("speakers"):
            citation.append(f"speakers={', '.join(source['speakers'])}")
        if source.get("start_time") is not None:
            citation.append(f"start={source['start_time']:.2f}s")
        if source.get("end_time") is not None:
            citation.append(f"end={source['end_time']:.2f}s")
        block_header = f"[Source {index}] " + " | ".join(citation)
        context_blocks.append(f"{block_header}\n{source.get('content', '').strip()}")

    try:
        client = Groq(api_key=config.secret("groq_api_key"))
        response = client.chat.completions.create(
            model=config.rag_model_name,
            temperature=0.1,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer only from the provided meeting transcript context. "
                        "If the answer is not supported by the context, say exactly: "
                        f'"{NO_INFO_MESSAGE}" '
                        "When you answer, include inline citations like [Source 1]."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question:\n{query}\n\nContext:\n\n" + "\n\n".join(context_blocks),
                },
            ],
        )
    except Exception:
        logger.exception("answer generation failed for query=%r; returning raw source content", query)
        return "\n\n".join(source["content"] for source in sources if source.get("content"))
    return (response.choices[0].message.content or "").strip() or NO_INFO_MESSAGE


def query_markdown_knowledge(query: str, top_k: int = 5, meeting_ids: list[str] | None = None) -> dict:
    started_at = time.perf_counter()
    sources = retrieve_markdown_sources(query, top_k=top_k, meeting_ids=meeting_ids)
    answer = answer_from_sources(query, sources)
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    return {"answer": answer, "sources": sources, "processing_time_ms": elapsed_ms}


def query_single_meeting(meeting_id: UUID | str, query: str, top_k: int = 5) -> dict:
    return query_markdown_knowledge(query, top_k=top_k, meeting_ids=[str(meeting_id)])
