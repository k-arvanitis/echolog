from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


class QueryRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = Field(
        description="Natural-language question to answer from meeting transcripts"
    )
    top_k: int = Field(default=5, ge=1, le=10, description="Number of transcript chunks to retrieve")
    meeting_ids: list[str] | None = Field(
        default=None, description="Optional list of meeting IDs to restrict retrieval to"
    )


class RetentionRequest(BaseModel):
    retention_days: int | None = Field(
        description="Days to retain this meeting from now; null or <= 0 disables automatic expiry"
    )
