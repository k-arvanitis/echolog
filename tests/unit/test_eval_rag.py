from __future__ import annotations

import json
from pathlib import Path

from meeting_intelligence_engine.eval.rag import (
    build_rag_eval_summary,
    evaluate_rag_qa_sets,
    load_rag_qa_file,
    load_rag_qa_sets,
)


def test_load_rag_qa_file_uses_minimal_schema(tmp_path: Path) -> None:
    path = tmp_path / "ES2016b.json"
    path.write_text(
        json.dumps(
            {
                "meeting_id": "ES2016b",
                "qa_pairs": [
                    {"id": "q1", "question": "What happened?", "gold_answer": "A decision was made."},
                ],
            }
        ),
        encoding="utf-8",
    )

    qa_set = load_rag_qa_file(path)

    assert qa_set.meeting_id == "ES2016b"
    assert qa_set.qa_pairs[0].gold_answer == "A decision was made."


def test_load_rag_qa_sets_skips_combined_bundle(tmp_path: Path) -> None:
    (tmp_path / "all_meetings_qa.json").write_text("[]", encoding="utf-8")
    (tmp_path / "ES2004a.json").write_text(
        json.dumps({"meeting_id": "ES2004a", "qa_pairs": [{"id": "q1", "question": "Q", "gold_answer": "A"}]}),
        encoding="utf-8",
    )

    loaded = load_rag_qa_sets(tmp_path)

    assert len(loaded) == 1
    assert loaded[0].meeting_id == "ES2004a"


def test_evaluate_rag_qa_sets_uses_query_and_scores(monkeypatch, tmp_path: Path) -> None:
    qa_path = tmp_path / "ES2016b.json"
    qa_path.write_text(
        json.dumps(
            {
                "meeting_id": "ES2016b",
                "qa_pairs": [{"id": "q1", "question": "What happened?", "gold_answer": "The team chose X."}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "meeting_intelligence_engine.eval.rag._prepare_eval_collection",
        lambda qa_sets, config: "tmp_eval_collection",
    )
    monkeypatch.setattr(
        "meeting_intelligence_engine.eval.rag._run_rag_query",
        lambda meeting_id, question, top_k, collection_name, config: {
            "answer": "The team chose X.",
            "sources": [{"content": "The team chose X in the meeting."}],
        },
    )
    monkeypatch.setattr(
        "meeting_intelligence_engine.eval.rag._build_ragas_metrics",
        lambda _settings: {
            "faithfulness": object(),
            "answer_relevancy": object(),
            "context_precision": object(),
            "context_recall": object(),
        },
    )
    monkeypatch.setattr(
        "meeting_intelligence_engine.eval.rag._score_ragas_sample",
        lambda *args, **kwargs: {
            "faithfulness": 1.0,
            "answer_relevancy": 0.9,
            "context_precision": 0.8,
            "context_recall": 0.7,
        },
    )

    rows = evaluate_rag_qa_sets(load_rag_qa_sets(tmp_path), top_k=3)
    summary = build_rag_eval_summary(rows)

    assert len(rows) == 1
    assert rows[0].source_count == 1
    assert summary["faithfulness"] == 1.0
    assert summary["meeting_count"] == 1
