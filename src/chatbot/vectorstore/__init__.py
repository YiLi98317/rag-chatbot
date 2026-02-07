from __future__ import annotations

from typing import TYPE_CHECKING

from chatbot.vectorstore.base import VectorStore

if TYPE_CHECKING:
    from chatbot.settings import Settings


def get_vector_store(settings: "Settings") -> VectorStore:
    provider = (getattr(settings, "vector_provider", None) or "milvus").strip().lower()
    if provider == "qdrant":
        if not getattr(settings, "qdrant_url", None):
            raise RuntimeError("VECTOR_PROVIDER=qdrant requires QDRANT_URL.")
        from qdrant_client import QdrantClient  # type: ignore

        from chatbot.vectorstore.qdrant_store import QdrantStore

        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=120.0)
        return QdrantStore(client, base_url=settings.qdrant_url, api_key=settings.qdrant_api_key)

    # default: milvus
    from chatbot.vectorstore.milvus_store import MilvusStore

    return MilvusStore(
        uri=getattr(settings, "milvus_uri", None),
        lite_db=getattr(settings, "milvus_lite_db", None),
        db_name=settings.milvus_db,
    )


__all__ = ["get_vector_store", "VectorStore"]

