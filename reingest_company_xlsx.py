#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
import importlib.util
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Ensure `src/` is on sys.path so `import chatbot` works when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import pandas as pd  # type: ignore
from tqdm import tqdm  # noqa: E402

from chatbot.config import get_settings  # type: ignore  # noqa: E402
from chatbot.embeddings.provider import embed_texts  # type: ignore  # noqa: E402
from chatbot.ingest.chunking import chunk_text_en, chunk_text_zh  # type: ignore  # noqa: E402
from chatbot.retrieval.normalize import detect_lang  # type: ignore  # noqa: E402
from chatbot.vectorstore import get_vector_store  # type: ignore  # noqa: E402
from chatbot.vectorstore.base import Point  # type: ignore  # noqa: E402
from chatbot.vectorstore.ids import stable_chunk_id  # type: ignore  # noqa: E402


def _row_to_text(row: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k, v in row.items():
        if v is None:
            continue
        s = str(v).strip()
        if not s or s.lower() in {"nan", "none"}:
            continue
        parts.append(f"{k}: {s}")
    return "\n".join(parts).strip()


def _chunks_for_text(text: str, *, chunk_size: int, chunk_overlap: int) -> Tuple[str, List[str]]:
    lang = detect_lang(text)
    if lang in ("zh", "mixed"):
        return lang, chunk_text_zh(text, max_chars=chunk_size, overlap=chunk_overlap)
    return lang, chunk_text_en(text, max_chars=chunk_size, overlap=chunk_overlap)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest an Excel file into Qdrant (Company dataset).")
    parser.add_argument(
        "--xlsx",
        default="data/target/company.xlsx",
        help="Path to .xlsx or .xls file (default: data/target/company.xlsx)",
    )
    parser.add_argument("--sheet", default=None, help="Optional sheet name (default: all sheets)")
    parser.add_argument("--collection", default=None, help="Qdrant collection (default: QDRANT_COLLECTION/.env)")
    parser.add_argument("--embed-model", default=None, help="Embedding model override (default: EMBED_MODEL/.env)")
    parser.add_argument("--max-rows", type=int, default=0, help="Optional max rows to ingest (0 = all)")
    parser.add_argument("--embed-batch-size", type=int, default=32, help="Embedding batch size (default: 32)")
    parser.add_argument("--qdrant-batch-size", type=int, default=64, help="Qdrant upsert batch size (default: 64)")
    parser.add_argument("--chunk-size", type=int, default=None, help="Chunk size override (default: ZH_CHUNK_SIZE or 1200)")
    parser.add_argument("--chunk-overlap", type=int, default=None, help="Chunk overlap override (default: ZH_CHUNK_OVERLAP or 150)")
    args = parser.parse_args()

    settings = get_settings()
    collection = args.collection or settings.default_collection
    embed_model = args.embed_model or os.getenv("EMBED_MODEL") or settings.embed_model

    excel_path = (PROJECT_ROOT / args.xlsx).resolve()
    if not excel_path.exists():
        raise SystemExit(f"Excel file not found: {excel_path}")
    suffix = excel_path.suffix.lower()
    if suffix not in {".xlsx", ".xls"}:
        raise SystemExit(f"Unsupported file type: {suffix} (expected .xlsx or .xls)")

    zh_chunk_size = int(os.getenv("ZH_CHUNK_SIZE", "1200"))
    zh_chunk_overlap = int(os.getenv("ZH_CHUNK_OVERLAP", "150"))
    chunk_size = int(args.chunk_size) if args.chunk_size else zh_chunk_size
    chunk_overlap = int(args.chunk_overlap) if args.chunk_overlap else zh_chunk_overlap

    print("Re-ingesting Company Excel")
    print(f"- excel: {excel_path}")
    print(f"- sheet: {args.sheet or '(all)'}")
    print(f"- collection: {collection}")
    print(f"- embed_provider: {settings.embed_provider}")
    print(f"- embed_model: {embed_model}")
    print(f"- chunk_size/overlap: {chunk_size}/{chunk_overlap}")
    print(f"- embed_batch_size: {args.embed_batch_size} | qdrant_batch_size: {args.qdrant_batch_size}")

    store = get_vector_store(settings)

    engine: Optional[str] = None
    if suffix == ".xls":
        engine = "xlrd"
        if importlib.util.find_spec("xlrd") is None:
            raise SystemExit(
                "Reading .xls requires the 'xlrd' package. "
                "Install it with: python -m pip install xlrd"
            )
    elif suffix == ".xlsx":
        # pandas will usually pick openpyxl, but be explicit for clearer errors.
        engine = "openpyxl"

    xl = pd.ExcelFile(excel_path, engine=engine)
    sheet_names: Sequence[str]
    if args.sheet:
        sheet_names = [args.sheet]
    else:
        sheet_names = xl.sheet_names

    # Buffers for embedding/upsert.
    buffer_texts: List[str] = []
    buffer_metas: List[Dict[str, Any]] = []
    total_rows = 0
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
            store.ensure_collection(collection, vector_size)
            created_collection = True
        pts = []
        for text, vec, meta in zip(buffer_texts, vecs, buffer_metas):
            pid = stable_chunk_id(
                source=str(meta.get("source") or ""),
                table=str(meta.get("table") or ""),
                row_id=f"{meta.get('sheet')}:{meta.get('row')}",
                chunk_id=int(meta.get("chunk") or 0),
            )
            pts.append(Point(id=pid, vector=list(vec), text=text, metadata=dict(meta)))
        store.upsert(collection, points=pts, batch_size=int(args.qdrant_batch_size))
        dt = time.time() - t0
        total_chunks += len(buffer_texts)
        buffer_texts.clear()
        buffer_metas.clear()
        print(f"  flushed {len(vecs)} chunks (total_chunks={total_chunks}) in {dt:.1f}s")

    # Iterate rows
    for sheet in sheet_names:
        df = xl.parse(sheet)
        # Normalize column names to strings (keeps Chinese headers intact).
        df.columns = [str(c).strip() for c in df.columns]
        rows_iter = df.to_dict(orient="records")
        if args.max_rows and args.max_rows > 0:
            rows_iter = rows_iter[: int(args.max_rows)]
        for i, row in enumerate(tqdm(rows_iter, desc=f"sheet:{sheet}", unit="row")):
            total_rows += 1
            text = _row_to_text(row)
            if not text:
                continue
            lang, chunks = _chunks_for_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            for ci, chunk in enumerate(chunks):
                buffer_texts.append(chunk)
                buffer_metas.append(
                    {
                        "source": str(excel_path),
                        "source_type": suffix.lstrip("."),
                        "table": "Company",
                        "sheet": sheet,
                        "row": i,
                        "chunk": ci,
                        "lang": lang,
                    }
                )
                if len(buffer_texts) >= int(args.embed_batch_size) * 4:
                    flush()

    flush()
    print(f"Done. rows={total_rows} chunks={total_chunks} collection={collection}")


if __name__ == "__main__":
    main()

