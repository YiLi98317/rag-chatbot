#!/usr/bin/env python3
"""
Ingest Netease Qiyu (网易七鱼) customer service chat exports into the vector store.

Supports:
  - Single file:  --xlsx data/shangwu11to03.xlsx
  - Batch dir:    --data-dir data/
  - Output modes: --mode knowledge | conversation | both
  - Filtering:    --min-rounds 2  --max-sessions 1000
  - Recreate:     --recreate
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd  # type: ignore
from tqdm import tqdm  # noqa: E402

from chatbot.config import get_settings  # type: ignore  # noqa: E402
from chatbot.embeddings.provider import embed_texts  # type: ignore  # noqa: E402
from chatbot.ingest.chunking import chunk_text_zh  # type: ignore  # noqa: E402
from chatbot.ingest.qiyu_parser import (  # type: ignore  # noqa: E402
    parse_session,
    session_to_conversation_doc,
    session_to_knowledge_doc,
)
from chatbot.vectorstore import get_vector_store  # type: ignore  # noqa: E402
from chatbot.vectorstore.base import Point  # type: ignore  # noqa: E402
from chatbot.vectorstore.ids import stable_chunk_id  # type: ignore  # noqa: E402

CONTENT_COL = "会话内容（不包含富文本标签）"


def _iter_xlsx_files(data_dir: str) -> List[Path]:
    base = Path(data_dir)
    return sorted(p for p in base.glob("*.xlsx") if not p.name.startswith("~$"))


def _build_docs_from_row(
    row: Dict[str, Any],
    mode: str,
    chunk_size: int,
    chunk_overlap: int,
    source_path: str,
) -> List[Tuple[str, Dict[str, Any]]]:
    """Parse one Excel row -> list of (chunk_text, metadata) tuples."""
    session_id = str(row.get("会话ID", ""))
    agent_name = str(row.get("接待客服", "")).strip()
    visitor_name = str(row.get("访客用户名", "")).strip()
    rounds = int(row.get("对话回合数", 0))
    raw_content = str(row.get(CONTENT_COL, ""))

    extra_meta = {}
    for key in ("客服组ID", "分流客服组", "订单号", "产品信息", "来源", "备注"):
        val = str(row.get(key, "")).strip()
        if val and val not in ("--", "nan", "None"):
            extra_meta[key] = val

    session = parse_session(
        session_id=session_id,
        agent_name=agent_name,
        visitor_name=visitor_name,
        rounds=rounds,
        raw_content=raw_content,
        extra_metadata=extra_meta,
    )
    if session is None:
        return []

    docs: List[Tuple[str, Dict[str, Any]]] = []
    base_meta = {
        "source": source_path,
        "source_type": "qiyu",
        "session_id": session_id,
        "agent_name": agent_name,
    }

    if mode in ("knowledge", "both"):
        kb_doc = session_to_knowledge_doc(session)
        if kb_doc:
            chunks = chunk_text_zh(kb_doc, max_chars=chunk_size, overlap=chunk_overlap)
            for ci, chunk in enumerate(chunks):
                meta = {**base_meta, "mode": "knowledge", "chunk": ci}
                docs.append((chunk, meta))

    if mode in ("conversation", "both"):
        conv_doc = session_to_conversation_doc(session)
        if conv_doc:
            chunks = chunk_text_zh(conv_doc, max_chars=chunk_size, overlap=chunk_overlap)
            for ci, chunk in enumerate(chunks):
                meta = {**base_meta, "mode": "conversation", "chunk": ci}
                docs.append((chunk, meta))

    return docs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Qiyu (七鱼) chat exports into the vector store."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--xlsx", help="Path to a single .xlsx file")
    group.add_argument("--data-dir", help="Directory containing .xlsx files (batch mode)")

    parser.add_argument("--collection", default=None, help="Vector collection name")
    parser.add_argument("--embed-model", default=None, help="Embedding model override")
    parser.add_argument(
        "--mode",
        choices=["knowledge", "conversation", "both"],
        default="both",
        help="Output mode (default: both)",
    )
    parser.add_argument("--min-rounds", type=int, default=0, help="Skip sessions with fewer rounds")
    parser.add_argument("--max-sessions", type=int, default=0, help="Max sessions to process (0 = all)")
    parser.add_argument("--recreate", action="store_true", help="Recreate collection before ingest")
    parser.add_argument("--embed-batch-size", type=int, default=32, help="Embedding batch size")
    parser.add_argument("--upsert-batch-size", type=int, default=64, help="Vector upsert batch size")
    parser.add_argument("--chunk-size", type=int, default=None, help="Chunk size override")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="Chunk overlap override")
    args = parser.parse_args()

    settings = get_settings()
    collection = args.collection or settings.default_collection
    embed_model = args.embed_model or os.getenv("EMBED_MODEL") or settings.embed_model

    zh_chunk_size = int(os.getenv("ZH_CHUNK_SIZE", "1200"))
    zh_chunk_overlap = int(os.getenv("ZH_CHUNK_OVERLAP", "150"))
    chunk_size = args.chunk_size or zh_chunk_size
    chunk_overlap = args.chunk_overlap or zh_chunk_overlap

    xlsx_files: List[Path] = []
    if args.xlsx:
        p = Path(args.xlsx)
        if not p.exists():
            raise SystemExit(f"File not found: {p}")
        xlsx_files = [p]
    else:
        xlsx_files = _iter_xlsx_files(args.data_dir)
        if not xlsx_files:
            raise SystemExit(f"No .xlsx files found in {args.data_dir}")

    print("Re-ingesting Qiyu chat exports")
    print(f"  files: {len(xlsx_files)}")
    print(f"  collection: {collection} {'(recreate)' if args.recreate else ''}")
    print(f"  mode: {args.mode}")
    print(f"  min_rounds: {args.min_rounds} | max_sessions: {args.max_sessions or 'all'}")
    print(f"  embed: {settings.embed_provider} / {embed_model}")
    print(f"  chunk_size/overlap: {chunk_size}/{chunk_overlap}")

    store = get_vector_store(settings)

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

    buffer_texts: List[str] = []
    buffer_metas: List[Dict[str, Any]] = []
    total_sessions = 0
    total_chunks = 0
    skipped = 0
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
            batch_size=args.embed_batch_size,
        )
        if not created_collection:
            store.ensure_collection(collection, len(vecs[0]))
            created_collection = True

        pts: List[Point] = []
        for text, vec, meta in zip(buffer_texts, vecs, buffer_metas):
            pid = stable_chunk_id(
                source=str(meta.get("source", "")),
                table="qiyu",
                doc_id=str(meta.get("session_id", "")),
                chunk_id=int(meta.get("chunk", 0)),
                extra=str(meta.get("mode", "")),
            )
            pts.append(Point(id=pid, vector=list(vec), text=text, metadata=dict(meta)))
        store.upsert(collection, points=pts, batch_size=args.upsert_batch_size)
        dt = time.time() - t0
        total_chunks += len(buffer_texts)
        buffer_texts.clear()
        buffer_metas.clear()
        print(f"  flushed {len(vecs)} chunks (total={total_chunks}) in {dt:.1f}s")

    flush_threshold = args.embed_batch_size * 4

    for xlsx_path in xlsx_files:
        print(f"\nReading {xlsx_path.name} ...")
        df = pd.read_excel(xlsx_path, engine="openpyxl")
        df.columns = [str(c).strip() for c in df.columns]

        if CONTENT_COL not in df.columns:
            print(f"  WARNING: column '{CONTENT_COL}' not found, skipping file")
            continue

        rows = df.to_dict(orient="records")
        for row in tqdm(rows, desc=xlsx_path.stem[:30], unit="session"):
            rounds = int(row.get("对话回合数", 0))
            if rounds < args.min_rounds:
                skipped += 1
                continue

            docs = _build_docs_from_row(
                row, mode=args.mode,
                chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                source_path=str(xlsx_path),
            )
            if not docs:
                skipped += 1
                continue

            total_sessions += 1
            for text, meta in docs:
                buffer_texts.append(text)
                buffer_metas.append(meta)
                if len(buffer_texts) >= flush_threshold:
                    flush()

            if args.max_sessions and total_sessions >= args.max_sessions:
                print(f"  Reached max_sessions={args.max_sessions}, stopping.")
                break

        if args.max_sessions and total_sessions >= args.max_sessions:
            break

    flush()
    print(f"\nDone. sessions={total_sessions} chunks={total_chunks} skipped={skipped} collection={collection}")


if __name__ == "__main__":
    main()
