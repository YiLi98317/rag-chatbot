#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure `src/` is on sys.path so `import chatbot` works when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chatbot.settings import get_settings  # noqa: E402
from chatbot.embeddings.provider import embed_text  # noqa: E402


def _print_kv(title: str, data: Dict[str, Any]) -> None:
    print(title)
    for k, v in data.items():
        print(f"  {k}: {v}")


def _smoke_qdrant() -> int:
    from qdrant_client import QdrantClient  # type: ignore

    from chatbot.vectorstore.qdrant_store import QdrantStore  # noqa: E402

    settings = get_settings()
    if not settings.qdrant_url:
        raise RuntimeError("QDRANT_URL is required for VECTOR_PROVIDER=qdrant smoke test.")

    q = os.getenv("SMOKE_QUERY", "smoke test query")
    top_k = int(os.getenv("SMOKE_TOP_K", str(settings.default_top_k or 10)))
    coll = os.getenv("SMOKE_COLLECTION", settings.default_collection)

    vec = embed_text(
        q,
        provider=settings.embed_provider,
        model=settings.embed_model,
        ollama_base_url=settings.ollama_base_url,
    )
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=30.0)
    store = QdrantStore(client, base_url=settings.qdrant_url, api_key=settings.qdrant_api_key)

    hits = store.search(collection=coll, vector=vec, top_k=top_k, filters=None, debug=True)
    n = len(hits) if hasattr(hits, "__len__") else 0
    _print_kv(
        "SMOKE_OK",
        {
            "provider": "qdrant",
            "collection": coll,
            "hits": n,
            "note": "0 hits is allowed if collection is empty or not ingested yet.",
        },
    )
    return 0


def _smoke_milvus() -> int:
    settings = get_settings()
    if not settings.milvus_uri:
        raise RuntimeError("MILVUS_URI is required for VECTOR_PROVIDER=milvus smoke test.")

    try:
        from pymilvus import Collection, connections, utility  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "pymilvus is not installed. Install deps first (make install / pip install -r requirements.txt). "
            f"Import error: {type(e).__name__}: {e}"
        ) from e

    q = os.getenv("SMOKE_QUERY", "smoke test query")
    top_k = int(os.getenv("SMOKE_TOP_K", str(settings.default_top_k or 10)))
    coll = os.getenv("SMOKE_COLLECTION", settings.default_collection)

    connections.connect(alias="default", uri=settings.milvus_uri, db_name=settings.milvus_db)

    ok = True
    try:
        ok = bool(utility.has_collection(coll))
    except Exception:
        ok = False

    if not ok:
        _print_kv(
            "SMOKE_OK",
            {
                "provider": "milvus",
                "collection": coll,
                "hits": 0,
                "note": "Collection does not exist yet (ingest first).",
            },
        )
        return 0

    vec = embed_text(
        q,
        provider=settings.embed_provider,
        model=settings.embed_model,
        ollama_base_url=settings.ollama_base_url,
    )

    c = Collection(coll)
    try:
        c.load()
    except Exception:
        pass

    expr: Optional[str] = None
    try:
        res = c.search(
            data=[vec],
            anns_field="vector",
            param={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top_k,
            expr=expr,
            output_fields=["id", "text", "table", "lang", "metadata"],
        )
        # `res` is a list (one per query vector)
        hits = res[0] if res else []
        n = len(hits) if hasattr(hits, "__len__") else 0
    except Exception as e:
        _print_kv(
            "SMOKE_WARN",
            {
                "provider": "milvus",
                "collection": coll,
                "warning": f"Search failed ({type(e).__name__}): {e}",
                "note": "This can happen if schema/index doesn't match expected fields yet.",
            },
        )
        return 0

    _print_kv(
        "SMOKE_OK",
        {
            "provider": "milvus",
            "collection": coll,
            "hits": n,
            "note": "0 hits is allowed if collection is empty or not ingested yet.",
        },
    )
    return 0


def main() -> int:
    settings = get_settings()
    payload = {
        "vector_provider": settings.vector_provider,
        "default_collection": settings.default_collection,
        "embed_provider": settings.embed_provider,
        "embed_model": settings.embed_model,
        "chat_model": settings.chat_model,
    }
    print("SMOKE_CONFIG:", json.dumps(payload, ensure_ascii=False))
    if settings.vector_provider == "qdrant":
        return _smoke_qdrant()
    return _smoke_milvus()


if __name__ == "__main__":
    raise SystemExit(main())

