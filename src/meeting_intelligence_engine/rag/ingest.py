from __future__ import annotations

import argparse
from pathlib import Path

from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, SparseVectorParams, VectorParams

from meeting_intelligence_engine.config import settings
from meeting_intelligence_engine.rag.chunking import chunk_markdown_files
from meeting_intelligence_engine.rag.embeddings import dense_embed, get_qdrant_client, sparse_embed


def ensure_collection() -> None:
    client = get_qdrant_client()
    collections = {collection.name for collection in client.get_collections().collections}
    if settings.qdrant_collection not in collections:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config={"dense": VectorParams(size=settings.dense_dim, distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams()},
        )


def recreate_collection() -> None:
    client = get_qdrant_client()
    collections = {collection.name for collection in client.get_collections().collections}
    if settings.qdrant_collection in collections:
        client.delete_collection(settings.qdrant_collection)
    ensure_collection()


def delete_by_meeting_id(meeting_id: str) -> None:
    ensure_collection()
    get_qdrant_client().delete(
        collection_name=settings.qdrant_collection,
        points_selector=Filter(
            must=[FieldCondition(key="meeting_id", match=MatchValue(value=meeting_id))]
        ),
    )


def ingest_markdown(paths: list[Path], recreate: bool = False) -> int:
    chunks = chunk_markdown_files(paths)
    if recreate:
        recreate_collection()
    else:
        ensure_collection()
    points = [
        PointStruct(
            id=chunk["id"],
            vector={"dense": dense_embed(f"passage: {chunk['content']}"), "sparse": sparse_embed(chunk["content"])},
            payload=chunk,
        )
        for chunk in chunks
    ]
    if points:
        get_qdrant_client().upsert(collection_name=settings.qdrant_collection, points=points)
    return len(points)


def ingest_meeting_markdown(meeting_id: str, transcript_md_path: Path) -> int:
    delete_by_meeting_id(meeting_id)
    return ingest_markdown([transcript_md_path], recreate=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest Markdown transcripts into Qdrant.")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("data/meetings"), Path("data/md")])
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate the whole Qdrant collection.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    count = ingest_markdown(args.paths, recreate=args.recreate)
    print(f"Ingested {count} markdown chunks into {settings.qdrant_collection}")
