from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from meeting_intelligence_engine.rag.chunking import chunk_markdown_files, recursive_chunks
from meeting_intelligence_engine.rag.query import query_markdown_knowledge, query_single_meeting


def test_recursive_chunks_overlaps_and_keeps_text() -> None:
    text = "First sentence. " * 80
    chunks = recursive_chunks(text, chunk_size=300, overlap=50)

    assert len(chunks) > 1
    assert chunks[0][0].startswith("First sentence")
    assert chunks[1][1] < chunks[0][2]


def test_chunk_markdown_files_discovers_md_only(tmp_path: Path) -> None:
    md = tmp_path / "meeting.md"
    md.write_text("# Meeting\n\n[00:00:00.000 --> 00:00:05.000] Jason Somerville: hello world " * 20, encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("ignore", encoding="utf-8")

    chunks = chunk_markdown_files([tmp_path], chunk_size=200, overlap=20)

    assert chunks
    assert all(chunk["source"].endswith("meeting.md") for chunk in chunks)
    assert all("speakers" in chunk for chunk in chunks)
    assert any("Jason Somerville" in chunk["speakers"] for chunk in chunks)


def test_query_markdown_knowledge_uses_hybrid_search(monkeypatch) -> None:
    point = MagicMock()
    point.score = 0.9
    point.payload = {"source": "meeting.md", "content": "Relevant transcript chunk", "start_char": 0, "end_char": 10}
    client = MagicMock()
    client.query_points.return_value = MagicMock(points=[point])

    monkeypatch.setattr("meeting_intelligence_engine.rag.query.dense_embed", lambda _query: [0.1] * 768)
    monkeypatch.setattr("meeting_intelligence_engine.rag.query.sparse_embed", lambda _query: MagicMock())
    monkeypatch.setattr("meeting_intelligence_engine.rag.query.get_qdrant_client", lambda: client)
    monkeypatch.setattr("meeting_intelligence_engine.rag.query.answer_from_sources", lambda _query, _sources: "Answer")

    result = query_markdown_knowledge("what happened?")

    assert result["answer"] == "Answer"
    assert result["sources"][0]["source"] == "meeting.md"
    assert client.query_points.called


def test_query_single_meeting_passes_meeting_filter(monkeypatch) -> None:
    captured = {}

    def fake_query(query: str, top_k: int = 5, meeting_ids=None):
        captured["query"] = query
        captured["top_k"] = top_k
        captured["meeting_ids"] = meeting_ids
        return {"answer": "ok", "sources": [], "processing_time_ms": 1}

    monkeypatch.setattr("meeting_intelligence_engine.rag.query.query_markdown_knowledge", fake_query)
    result = query_single_meeting("1234", "what happened", top_k=3)

    assert result["answer"] == "ok"
    assert captured["meeting_ids"] == ["1234"]
