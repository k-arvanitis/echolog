from __future__ import annotations

import argparse
from pathlib import Path

from meeting_intelligence_engine.eval.rag import (
    RAGMeetingQASet,
    RAGEvaluationRow,
    build_rag_eval_summary,
    evaluate_rag_qa_sets,
    load_rag_qa_sets,
    write_rag_eval_json,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate per-meeting RAG answers with fixed QA pairs and RAGAS.")
    parser.add_argument("--qa-dir", type=Path, default=Path("eval/rag_qa"))
    parser.add_argument("--meeting-id", action="append", dest="meeting_ids", default=[])
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--limit", type=int, default=None, help="Limit total QA pairs for a smoke run.")
    parser.add_argument("--json", type=Path, default=Path("eval/results/rag_eval_results.json"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    qa_sets = load_rag_qa_sets(args.qa_dir, meeting_ids=args.meeting_ids or None)
    if not qa_sets:
        raise SystemExit("No QA files found for the selected meetings.")
    if args.limit is not None:
        remaining = max(0, args.limit)
        limited_sets: list[RAGMeetingQASet] = []
        for qa_set in qa_sets:
            if remaining <= 0:
                break
            clipped = qa_set.qa_pairs[:remaining]
            if clipped:
                limited_sets.append(RAGMeetingQASet(meeting_id=qa_set.meeting_id, qa_pairs=clipped))
                remaining -= len(clipped)
        qa_sets = limited_sets

    partial_rows: list[RAGEvaluationRow] = []
    partial_path = args.json.with_suffix(args.json.suffix + ".partial")

    def progress(event: dict) -> None:
        if event["event"] == "start":
            print(
                f"[{event['index']}/{event['total']}] {event['meeting_id']} {event['qa_id']} start: {event['question']}",
                flush=True,
            )
            return

        row = event["row"]
        partial_rows.append(row)
        partial_summary = build_rag_eval_summary(partial_rows)
        write_rag_eval_json(partial_summary, partial_path)
        print(
            f"[{event['index']}/{event['total']}] {event['meeting_id']} {event['qa_id']} done "
            f"faithfulness={row.faithfulness} answer_relevancy={row.answer_relevancy} "
            f"context_precision={row.context_precision} context_recall={row.context_recall}",
            flush=True,
        )

    rows = evaluate_rag_qa_sets(qa_sets, top_k=args.top_k, progress_callback=progress)
    summary = build_rag_eval_summary(rows)
    write_rag_eval_json(summary, args.json)
    partial_path.unlink(missing_ok=True)

    print(f"meetings={summary['meeting_count']} questions={summary['question_count']}")
    print(f"faithfulness={summary['faithfulness']}")
    print(f"answer_relevancy={summary['answer_relevancy']}")
    print(f"context_precision={summary['context_precision']}")
    print(f"context_recall={summary['context_recall']}")
    print(f"saved={args.json}")


if __name__ == "__main__":
    main()
