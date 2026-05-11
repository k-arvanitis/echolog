from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from meeting_intelligence_engine.api.deps import get_session, require_api_key
from meeting_intelligence_engine.api.schemas import QueryRequest
from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.rag.query import query_markdown_knowledge, query_single_meeting
from meeting_intelligence_engine.services.meetings import get_meeting

router = APIRouter(tags=["query"], dependencies=[Depends(require_api_key)])


def _require_rag_enabled() -> None:
    if not settings.rag_enabled:
        raise HTTPException(status_code=503, detail="RAG is disabled")


@router.post("/query")
def query_all_meetings(body: QueryRequest) -> dict:
    _require_rag_enabled()
    return query_markdown_knowledge(body.query, top_k=body.top_k, meeting_ids=body.meeting_ids)


@router.post("/knowledge/query")
def query_knowledge(body: QueryRequest) -> dict:
    _require_rag_enabled()
    return query_markdown_knowledge(body.query, top_k=body.top_k, meeting_ids=body.meeting_ids)


@router.post("/meetings/{meeting_id}/query")
def query_one_meeting(meeting_id: UUID, body: QueryRequest, session: Session = Depends(get_session)) -> dict:
    _require_rag_enabled()
    try:
        get_meeting(session, meeting_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return query_single_meeting(meeting_id, body.query, top_k=body.top_k)
