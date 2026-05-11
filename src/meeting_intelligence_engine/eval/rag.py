from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from groq import Groq

from meeting_intelligence_engine import prompts
from meeting_intelligence_engine.config import Settings, settings
from meeting_intelligence_engine.rag.chunking import chunk_markdown_files
from meeting_intelligence_engine.rag.embeddings import dense_embed, get_qdrant_client, sparse_embed
from meeting_intelligence_engine.rag.query import build_meeting_filter


@dataclass
class RAGQAPair:
    id: str
    question: str
    gold_answer: str


@dataclass
class RAGMeetingQASet:
    meeting_id: str
    qa_pairs: list[RAGQAPair]


@dataclass
class RAGEvaluationRow:
    meeting_id: str
    qa_id: str
    question: str
    gold_answer: str
    predicted_answer: str
    retrieved_contexts: list[str]
    source_count: int
    faithfulness: float | None
    answer_relevancy: float | None
    context_precision: float | None
    context_recall: float | None


def meeting_transcript_md_path(meeting_id: str, config: Settings = settings) -> Path:
    return config.data_dir / "meetings" / meeting_id / "transcript" / "transcript.md"


def load_rag_qa_file(path: Path) -> RAGMeetingQASet:
    payload = json.loads(path.read_text())
    meeting_id = str(payload["meeting_id"])
    qa_pairs = [
        RAGQAPair(
            id=str(item["id"]),
            question=str(item["question"]).strip(),
            gold_answer=str(item["gold_answer"]).strip(),
        )
        for item in payload["qa_pairs"]
    ]
    return RAGMeetingQASet(meeting_id=meeting_id, qa_pairs=qa_pairs)


def load_rag_qa_sets(qa_dir: Path, meeting_ids: list[str] | None = None) -> list[RAGMeetingQASet]:
    selected = set(meeting_ids or [])
    result = []
    for path in sorted(qa_dir.glob("*.json")):
        if path.name == "all_meetings_qa.json":
            continue
        qa_set = load_rag_qa_file(path)
        if selected and qa_set.meeting_id not in selected:
            continue
        result.append(qa_set)
    return result


def _eval_collection_name(qa_sets: list[RAGMeetingQASet], config: Settings) -> str:
    ordered = "-".join(sorted(qa_set.meeting_id for qa_set in qa_sets))
    suffix = abs(hash(ordered)) % 10_000_000
    return f"{config.qdrant_collection}_rag_eval_{suffix}"


def _prepare_eval_collection(qa_sets: list[RAGMeetingQASet], config: Settings) -> str:
    from qdrant_client.models import Distance, PointStruct, SparseVectorParams, VectorParams

    collection_name = _eval_collection_name(qa_sets, config)
    client = get_qdrant_client()
    collections = {collection.name for collection in client.get_collections().collections}
    if collection_name in collections:
        client.delete_collection(collection_name)

    client.create_collection(
        collection_name=collection_name,
        vectors_config={"dense": VectorParams(size=config.dense_dim, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams()},
    )

    paths = [meeting_transcript_md_path(qa_set.meeting_id, config) for qa_set in qa_sets]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing transcript markdown for evaluation: {', '.join(missing)}")

    chunks = chunk_markdown_files(paths)
    points = [
        PointStruct(
            id=chunk["id"],
            vector={"dense": dense_embed(f"passage: {chunk['content']}"), "sparse": sparse_embed(chunk["content"])},
            payload=chunk,
        )
        for chunk in chunks
    ]
    if points:
        client.upsert(collection_name=collection_name, points=points)
    return collection_name


TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def _rerank_sources(question: str, sources: list[dict], keep: int = 10) -> list[dict]:
    query_tokens = _tokenize(question)
    ranked: list[tuple[float, dict]] = []
    for index, source in enumerate(sources):
        content = str(source.get("content", ""))
        content_tokens = _tokenize(content)
        overlap = len(query_tokens & content_tokens)
        density = overlap / max(1, len(query_tokens))
        base_score = float(source.get("score") or 0.0)
        position_bonus = max(0.0, 1.0 - (index * 0.03))
        combined = (density * 3.0) + base_score + position_bonus
        ranked.append((combined, source))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [source for _score, source in ranked[:keep]]


def _answer_from_eval_sources(question: str, sources: list[dict], config: Settings) -> str:
    if not sources:
        return prompts.NO_INFO_MESSAGE
    if not config.groq_api_key:
        return "\n\n".join(source["content"] for source in sources if source.get("content"))

    context_blocks = []
    for index, source in enumerate(sources, start=1):
        context_blocks.append(f"[Source {index}]\n{str(source.get('content', '')).strip()}")

    client = Groq(api_key=config.secret("groq_api_key"))
    response = client.chat.completions.create(
        model=config.rag_model_name,
        temperature=0,
        messages=[
            {"role": "system", "content": prompts.RAG_EVAL_ANSWER_SYSTEM},
            {
                "role": "user",
                "content": f"Question:\n{question}\n\nContext:\n\n" + "\n\n".join(context_blocks),
            },
        ],
    )
    return (response.choices[0].message.content or "").strip() or prompts.NO_INFO_MESSAGE


def _run_rag_query(
    meeting_id: str,
    question: str,
    top_k: int,
    collection_name: str,
    config: Settings,
) -> dict[str, Any]:
    from qdrant_client.models import Fusion, FusionQuery, Prefetch

    client = get_qdrant_client()
    query_filter = build_meeting_filter([meeting_id])
    candidate_limit = max(50, top_k * 10)
    result = client.query_points(
        collection_name=collection_name,
        prefetch=[
            Prefetch(
                query=dense_embed(f"query: {question}"), using="dense", limit=candidate_limit, filter=query_filter
            ),
            Prefetch(query=sparse_embed(question), using="sparse", limit=candidate_limit, filter=query_filter),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=candidate_limit,
        with_payload=True,
    )
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
    reranked_sources = _rerank_sources(question, sources, keep=max(10, top_k * 2))
    answer_sources = reranked_sources[:top_k]
    return {"answer": _answer_from_eval_sources(question, answer_sources, config=config), "sources": answer_sources}


def _build_ragas_metrics(config: Settings) -> dict[str, Any]:
    try:
        from langchain_ollama import OllamaEmbeddings
        from langchain_openai import ChatOpenAI
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import AnswerRelevancy, ContextPrecision, ContextRecall, Faithfulness
    except ImportError as exc:
        raise RuntimeError("RAG evaluation requires optional dependencies. Run `uv sync --extra eval`.") from exc

    if not config.openai_api_key:
        raise RuntimeError("RAG evaluation judge requires OPENAI_API_KEY.")

    ragas_llm = LangchainLLMWrapper(
        ChatOpenAI(model=config.rag_eval_judge_model, temperature=0, api_key=config.secret("openai_api_key"))
    )
    ragas_embeddings = LangchainEmbeddingsWrapper(OllamaEmbeddings(model=config.dense_model))
    return {
        "faithfulness": Faithfulness(llm=ragas_llm),
        "answer_relevancy": AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embeddings),
        "context_precision": ContextPrecision(llm=ragas_llm),
        "context_recall": ContextRecall(llm=ragas_llm),
    }


def _score_ragas_sample(
    question: str, gold_answer: str, predicted_answer: str, contexts: list[str], metrics: dict[str, Any]
) -> dict[str, float | None]:
    if not contexts:
        return {
            "faithfulness": None,
            "answer_relevancy": None,
            "context_precision": None,
            "context_recall": None,
        }

    from ragas.dataset_schema import SingleTurnSample

    sample = SingleTurnSample(
        user_input=question,
        response=predicted_answer,
        retrieved_contexts=contexts,
        reference=gold_answer,
    )

    scores: dict[str, float | None] = {}
    for key, metric in metrics.items():
        try:
            scores[key] = float(metric.single_turn_score(sample))
        except Exception:
            scores[key] = None
    return scores


def evaluate_rag_qa_sets(
    qa_sets: list[RAGMeetingQASet],
    top_k: int = 3,
    config: Settings = settings,
    progress_callback: Any | None = None,
) -> list[RAGEvaluationRow]:
    collection_name = _prepare_eval_collection(qa_sets, config)
    metrics = _build_ragas_metrics(config)
    rows: list[RAGEvaluationRow] = []
    total = sum(len(qa_set.qa_pairs) for qa_set in qa_sets)
    completed = 0

    for qa_set in qa_sets:
        for qa in qa_set.qa_pairs:
            completed += 1
            if progress_callback:
                progress_callback(
                    {
                        "event": "start",
                        "index": completed,
                        "total": total,
                        "meeting_id": qa_set.meeting_id,
                        "qa_id": qa.id,
                        "question": qa.question,
                    }
                )

            result = _run_rag_query(
                qa_set.meeting_id,
                qa.question,
                top_k=top_k,
                collection_name=collection_name,
                config=config,
            )
            contexts = [
                str(source.get("content", "")).strip() for source in result.get("sources", []) if source.get("content")
            ]
            scores = _score_ragas_sample(
                qa.question,
                qa.gold_answer,
                str(result.get("answer", "")).strip(),
                contexts,
                metrics,
            )
            row = RAGEvaluationRow(
                meeting_id=qa_set.meeting_id,
                qa_id=qa.id,
                question=qa.question,
                gold_answer=qa.gold_answer,
                predicted_answer=str(result.get("answer", "")).strip(),
                retrieved_contexts=contexts,
                source_count=len(result.get("sources", [])),
                faithfulness=scores["faithfulness"],
                answer_relevancy=scores["answer_relevancy"],
                context_precision=scores["context_precision"],
                context_recall=scores["context_recall"],
            )
            rows.append(row)

            if progress_callback:
                progress_callback(
                    {
                        "event": "done",
                        "index": completed,
                        "total": total,
                        "meeting_id": qa_set.meeting_id,
                        "qa_id": qa.id,
                        "question": qa.question,
                        "row": row,
                    }
                )
    return rows


def build_rag_eval_summary(rows: list[RAGEvaluationRow]) -> dict[str, Any]:
    def avg(values: list[float | None]) -> float | None:
        usable = [value for value in values if value is not None]
        return statistics.fmean(usable) if usable else None

    return {
        "prompt_version": prompts.PROMPT_VERSION,
        "question_count": len(rows),
        "meeting_count": len({row.meeting_id for row in rows}),
        "faithfulness": avg([row.faithfulness for row in rows]),
        "answer_relevancy": avg([row.answer_relevancy for row in rows]),
        "context_precision": avg([row.context_precision for row in rows]),
        "context_recall": avg([row.context_recall for row in rows]),
        "rows": [asdict(row) for row in rows],
    }


def write_rag_eval_json(summary: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
