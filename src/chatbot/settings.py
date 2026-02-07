from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    # Vector store selection
    vector_provider: str  # "milvus" | "qdrant"

    # Qdrant (optional unless vector_provider=qdrant)
    qdrant_url: Optional[str]
    qdrant_api_key: Optional[str]

    # Milvus (optional unless vector_provider=milvus)
    milvus_uri: Optional[str]
    milvus_lite_db: Optional[str]
    milvus_db: str
    milvus_collection: str

    # Models / providers
    ollama_base_url: str
    embed_provider: str
    embed_model: str
    chat_model: str

    # Retrieval defaults
    default_collection: str
    default_top_k: int
    embed_dim: Optional[int]

    # Data + SQL
    data_dir: str
    db_uri: Optional[str]
    sql_table: Optional[str]
    sql_updated_at: str
    sql_pk: str

    # Feature flags for retrieval layers
    enable_query_planner: bool
    enable_legacy_trailing_trim: bool
    dev_mode: bool
    enable_bm25_layer: bool
    enable_prf_layer: bool
    enable_qexp_layer: bool

    # Observability/SLA
    obs_metrics_enabled: bool
    sla_p95_latency_ms: int
    debug_traces: bool


def _bool_env(name: str, default: str) -> bool:
    return (os.getenv(name, default) or default).strip().lower() not in {"0", "false", "no"}


def _int_env(name: str, default: str) -> int:
    v = (os.getenv(name, default) or default).strip()
    try:
        return int(v)
    except Exception:
        return int(default)


def get_settings() -> Settings:
    """
    Centralized configuration loader. Reads from `.env` + environment variables.

    v0 defaults:
    - VECTOR_PROVIDER defaults to `milvus`
    - Collection defaults to `chatbot_docs`
    """
    load_dotenv()

    vector_provider = (os.getenv("VECTOR_PROVIDER", "milvus") or "milvus").strip().lower()
    if vector_provider not in {"milvus", "qdrant"}:
        vector_provider = "milvus"

    # Qdrant
    qdrant_url = (os.getenv("QDRANT_URL") or "").strip() or None
    qdrant_api_key = (os.getenv("QDRANT_API_KEY") or "").strip() or None

    # Milvus
    # NOTE: `pymilvus` loads `.env` on import and expects MILVUS_URI to be a http(s) endpoint.
    # For Milvus Lite (local file DB), use MILVUS_LITE_DB instead.
    milvus_uri = (os.getenv("MILVUS_URI") or "").strip() or None
    milvus_lite_db = (os.getenv("MILVUS_LITE_DB") or "").strip() or None
    milvus_db = (os.getenv("MILVUS_DB", "default") or "default").strip() or "default"
    milvus_collection = (os.getenv("MILVUS_COLLECTION", "chatbot_docs") or "chatbot_docs").strip() or "chatbot_docs"

    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    default_collection = (
        (os.getenv("MILVUS_COLLECTION") or "").strip()
        or (os.getenv("QDRANT_COLLECTION") or "").strip()
        or "chatbot_docs"
    )
    # Prefer TOP_K_DEFAULT but keep TOP_K for backward compatibility
    default_top_k = _int_env("TOP_K_DEFAULT", os.getenv("TOP_K", "10") or "10")

    embed_dim: Optional[int] = None
    raw_dim = (os.getenv("EMBED_DIM") or "").strip()
    if raw_dim:
        try:
            embed_dim = int(raw_dim)
        except Exception:
            embed_dim = None

    # Determine project root (two levels up from this file: src/chatbot/)
    project_root = Path(__file__).resolve().parents[2]
    default_data_dir = str(project_root / "data")
    data_dir = os.getenv("DATA_DIR", default_data_dir)

    db_uri = os.getenv("DB_URI")  # e.g., sqlite:///data/knowledge.db
    if not db_uri:
        # Convenience: allow MySQL config via MYSQL_* env vars (matches reingest_chinook_mysql.py).
        mysql_user = os.getenv("MYSQL_USER")
        mysql_password = os.getenv("MYSQL_PASSWORD")
        mysql_db = os.getenv("MYSQL_DB")
        mysql_host = os.getenv("MYSQL_HOST", "localhost")
        mysql_port = os.getenv("MYSQL_PORT", "3306")
        if mysql_user and mysql_password and mysql_db:
            # URL-encode username/password to be safe.
            u = quote_plus(str(mysql_user))
            p = quote_plus(str(mysql_password))
            db_uri = f"mysql+pymysql://{u}:{p}@{mysql_host}:{mysql_port}/{mysql_db}?charset=utf8mb4"

    sql_table = os.getenv("SQL_TABLE")
    sql_updated_at = os.getenv("SQL_UPDATED_AT", "updated_at")
    sql_pk = os.getenv("SQL_PK", "id")

    embed_provider = (os.getenv("EMBED_PROVIDER", "ollama") or "ollama").strip().lower()
    if embed_provider not in {"ollama", "sentence_transformers"}:
        embed_provider = "ollama"
    embed_model = os.getenv("EMBED_MODEL", "nomic-embed-text")
    chat_model = os.getenv("CHAT_MODEL", "llama3.1")

    enable_query_planner = _bool_env("ENABLE_QUERY_PLANNER", "true")
    enable_legacy_trailing_trim = _bool_env("ENABLE_LEGACY_TRAILING_TRIM", "false")
    dev_mode = _bool_env("CHATBOT_DEV_MODE", "false")
    enable_bm25_layer = _bool_env("ENABLE_BM25_LAYER", "true")
    enable_prf_layer = _bool_env("ENABLE_PRF_LAYER", "true")
    enable_qexp_layer = _bool_env("ENABLE_QEXP_LAYER", "true")

    obs_metrics_enabled = _bool_env("OBS_METRICS_ENABLED", "true")
    sla_p95_latency_ms = _int_env("SLA_P95_LATENCY_MS", "1500")
    debug_traces = _bool_env("DEBUG_TRACES", "0")

    # Provider-specific requirements (fail fast with actionable messages)
    if vector_provider == "milvus" and not (milvus_uri or milvus_lite_db):
        raise RuntimeError(
            "VECTOR_PROVIDER=milvus but neither MILVUS_URI nor MILVUS_LITE_DB is set. "
            "Set MILVUS_URI (e.g. http://localhost:19530) for a server, or set MILVUS_LITE_DB (e.g. ./milvus.db) for Milvus Lite."
        )
    if vector_provider == "qdrant" and not qdrant_url:
        raise RuntimeError(
            "VECTOR_PROVIDER=qdrant but QDRANT_URL is not set. "
            "Set QDRANT_URL (e.g. http://localhost:6333) or switch VECTOR_PROVIDER=milvus."
        )

    return Settings(
        vector_provider=vector_provider,
        qdrant_url=qdrant_url,
        qdrant_api_key=qdrant_api_key,
        milvus_uri=milvus_uri,
        milvus_lite_db=milvus_lite_db,
        milvus_db=milvus_db,
        milvus_collection=milvus_collection,
        ollama_base_url=ollama_base_url,
        embed_provider=embed_provider,
        embed_model=embed_model,
        chat_model=chat_model,
        default_collection=default_collection,
        default_top_k=default_top_k,
        embed_dim=embed_dim,
        data_dir=data_dir,
        db_uri=db_uri,
        sql_table=sql_table,
        sql_updated_at=sql_updated_at,
        sql_pk=sql_pk,
        enable_query_planner=enable_query_planner,
        enable_legacy_trailing_trim=enable_legacy_trailing_trim,
        dev_mode=dev_mode,
        enable_bm25_layer=enable_bm25_layer,
        enable_prf_layer=enable_prf_layer,
        enable_qexp_layer=enable_qexp_layer,
        obs_metrics_enabled=obs_metrics_enabled,
        sla_p95_latency_ms=sla_p95_latency_ms,
        debug_traces=debug_traces,
    )

