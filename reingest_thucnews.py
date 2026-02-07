#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Ensure `src/` is on sys.path so `import chatbot` works when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from qdrant_client import QdrantClient  # noqa: E402
from tqdm import tqdm  # noqa: E402

from chatbot.config import get_settings  # type: ignore  # noqa: E402
from chatbot.embeddings.provider import embed_texts  # type: ignore  # noqa: E402
from chatbot.ingest.chunking import chunk_text_en, chunk_text_zh  # type: ignore  # noqa: E402
from chatbot.retrieval.normalize import detect_lang  # type: ignore  # noqa: E402
from chatbot.vectorstore import get_vector_store  # type: ignore  # noqa: E402
from chatbot.vectorstore.base import Point  # type: ignore  # noqa: E402
from chatbot.vectorstore.ids import stable_chunk_id  # type: ignore  # noqa: E402


def _iter_sample_jsonl(path: Path, *, max_docs: int) -> Iterable[Tuple[int, str, str]]:
    """
    Yields (doc_id, label, text) from a THUCNews sample jsonl.
    Expected record shape: {"id": int, "label": str, "text": str}
    """
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            try:
                doc_id = int(rec.get("id"))
            except Exception:
                continue
            label = str(rec.get("label", "unknown"))
            text = str(rec.get("text", "")).strip()
            if not text:
                continue
            if doc_id >= max_docs:
                # Our sharder writes ids 0..N-1; this is a simple cap.
                break
            yield (doc_id, label, text)


def _chunks_for_doc(text: str, *, chunk_size: int, chunk_overlap: int) -> Tuple[str, List[str]]:
    lang = detect_lang(text)
    if lang in ("zh", "mixed"):
        return lang, chunk_text_zh(text, max_chars=chunk_size, overlap=chunk_overlap)
    return lang, chunk_text_en(text, max_chars=chunk_size, overlap=chunk_overlap)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-ingest a small THUCNews sample into Qdrant.")
    parser.add_argument(
        "--sample-jsonl",
        default="data/THUCNews/sample_2000/train.sample.jsonl",
        help="Path to sample jsonl (default: data/THUCNews/sample_2000/train.sample.jsonl)",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=2000,
        help="Max docs from the sample to ingest (default: 2000)",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Qdrant collection name (default: QDRANT_COLLECTION/.env or settings.default_collection)",
    )
    parser.add_argument(
        "--embed-model",
        default=None,
        help="Embedding model override (default: EMBED_MODEL/.env)",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate the collection before ingest",
    )
    parser.add_argument(
        "--embed-batch-size",
        type=int,
        default=32,
        help="Batch size for embedding calls (default: 32)",
    )
    parser.add_argument(
        "--qdrant-batch-size",
        type=int,
        default=32,
        help="Batch size for Qdrant upsert (default: 32)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Chunk size override (defaults to ZH_CHUNK_SIZE for zh, else 800)",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=None,
        help="Chunk overlap override (defaults to ZH_CHUNK_OVERLAP for zh, else 150)",
    )
    args = parser.parse_args()

    if args.max_docs <= 0:
        raise SystemExit("--max-docs must be > 0")

    settings = get_settings()
    collection = args.collection or settings.default_collection
    embed_model = args.embed_model or os.getenv("EMBED_MODEL") or settings.embed_model

    sample_path = PROJECT_ROOT / args.sample_jsonl
    if not sample_path.exists():
        raise SystemExit(f"Sample jsonl not found: {sample_path}")

    # Defaults: keep zh-friendly sizes unless caller overrides.
    zh_chunk_size = int(os.getenv("ZH_CHUNK_SIZE", "1200"))
    zh_chunk_overlap = int(os.getenv("ZH_CHUNK_OVERLAP", "150"))
    default_chunk_size = int(args.chunk_size) if args.chunk_size else zh_chunk_size
    default_chunk_overlap = int(args.chunk_overlap) if args.chunk_overlap else zh_chunk_overlap

    print("Re-ingesting THUCNews sample")
    print(f"- sample: {sample_path}")
    print(f"- max_docs: {args.max_docs}")
    print(f"- collection: {collection} {'(recreate)' if args.recreate else ''}")
    print(f"- embed_provider: {settings.embed_provider}")
    print(f"- embed_model: {embed_model}")
    print(f"- chunk_size/overlap: {default_chunk_size}/{default_chunk_overlap}")
    print(f"- embed_batch_size: {args.embed_batch_size} | qdrant_batch_size: {args.qdrant_batch_size}")

    store = get_vector_store(settings)

    # Stream docs → chunks → embed → upsert (bounded memory, visible progress).
    buffer_texts: List[str] = []
    buffer_metas: List[Dict[str, Any]] = []
    total_docs = 0
    total_chunks = 0
    created_collection = False

    def flush() -> None:
        nonlocal created_collection, total_chunks
        if not buffer_texts:
            return
        t0 = time.time()
        vecs = embed_texts(
            buffer_texts,
            provider=settings.embed_provider,
            model=embed_model,
            ollama_base_url=settings.ollama_base_url,
            batch_size=int(args.embed_batch_size),
        )
        if not created_collection:
            vector_size = len(vecs[0])
            if args.recreate:
                if settings.vector_provider == "qdrant":
                    try:
                        store.client.delete_collection(collection_name=collection)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                else:
                    try:
                        from pymilvus import utility  # type: ignore

                        if utility.has_collection(collection):
                            utility.drop_collection(collection)
                    except Exception:
                        pass
            store.ensure_collection(collection, vector_size)
            created_collection = True

        pts = []
        for text, vec, meta in zip(buffer_texts, vecs, buffer_metas):
            pid = stable_chunk_id(
                source=str(meta.get("source") or ""),
                table=str(meta.get("table") or ""),
                doc_id=str(meta.get("doc_id") or ""),
                chunk_id=int(meta.get("chunk") or 0),
            )
            pts.append(Point(id=pid, vector=list(vec), text=text, metadata=dict(meta)))
        store.upsert(collection, points=pts, batch_size=int(args.qdrant_batch_size))
        dt = time.time() - t0
        total_chunks += len(buffer_texts)
        buffer_texts.clear()
        buffer_metas.clear()
        print(f"  flushed {len(vecs)} chunks (total_chunks={total_chunks}) in {dt:.1f}s")

    # We can’t know total chunks without a pre-pass; show doc-level progress instead.
    for doc_id, label, text in tqdm(_iter_sample_jsonl(sample_path, max_docs=args.max_docs), total=args.max_docs):
        total_docs += 1
        lang, chunks = _chunks_for_doc(text, chunk_size=default_chunk_size, chunk_overlap=default_chunk_overlap)
        for ci, chunk in enumerate(chunks):
            buffer_texts.append(chunk)
            buffer_metas.append(
                {
                    "source": str(sample_path),
                    "source_type": "thucnews",
                    "table": "THUCNews",
                    "doc_id": doc_id,
                    "chunk": ci,
                    "label": label,
                    "lang": lang,
                }
            )
            if len(buffer_texts) >= int(args.embed_batch_size) * 4:
                # Keep embedding batches a bit larger than the internal batch size, but still bounded.
                flush()

    flush()
    print(f"Done. docs={total_docs} chunks={total_chunks} collection={collection}")


if __name__ == "__main__":
    main()

