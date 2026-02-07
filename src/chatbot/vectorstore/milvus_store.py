from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
import json

from chatbot.vectorstore.base import FilterDict, Hit, Point
from chatbot.vectorstore.milvus_filters import build_expr


@dataclass
class _SchemaConfig:
    id_max_len: int = 128
    text_max_len: int = 8192
    table_max_len: int = 128
    lang_max_len: int = 32


class MilvusStore:
    def __init__(self, *, uri: Optional[str], lite_db: Optional[str], db_name: str = "default") -> None:
        # For Milvus Lite (local), pass `lite_db=./milvus.db` and keep `MILVUS_URI` unset or a valid http URI.
        self._uri = (uri or "").strip() or None
        self._lite_db = (lite_db or "").strip() or None
        if not (self._uri or self._lite_db):
            raise ValueError("MilvusStore requires uri or lite_db.")
        self._db_name = db_name or "default"
        self._client = None
        self._schema_cfg = _SchemaConfig()

    def _connect(self) -> None:
        if self._client is not None:
            return
        # IMPORTANT: PyMilvus imports `dotenv` and reads `MILVUS_URI` from `.env` at import time.
        # That env var MUST be a valid http(s) endpoint (or empty), otherwise import fails.
        from pymilvus import MilvusClient  # type: ignore

        if self._lite_db:
            # Milvus Lite: uri is a local DB file path
            self._client = MilvusClient(self._lite_db)
        else:
            # Milvus server: uri is http(s) endpoint
            self._client = MilvusClient(uri=self._uri, db_name=self._db_name)

    def healthcheck(self) -> bool:
        try:
            self._connect()
            assert self._client is not None
            _ = self._client.list_collections()
            return True
        except Exception:
            return False

    def ensure_collection(self, collection: str, dim: int) -> None:
        self._connect()
        from pymilvus import DataType  # type: ignore

        assert self._client is not None
        name = collection
        if not name:
            raise ValueError("collection is required")
        dim = int(dim)
        if dim <= 0:
            raise ValueError("dim must be > 0")

        if self._client.has_collection(name):
            # Validate dim; drop & recreate if mismatch (v0 behavior, similar to QdrantStore)
            try:
                desc = self._client.describe_collection(name)
                fields = (desc or {}).get("fields", []) or []
                cur_dim = None
                for f in fields:
                    if f.get("name") == "vector":
                        cur_dim = int((f.get("params") or {}).get("dim") or dim)
                        break
                if cur_dim is not None and cur_dim != dim:
                    self._client.drop_collection(name)
            except Exception:
                pass

        if not self._client.has_collection(name):
            schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=self._schema_cfg.id_max_len)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dim)
            schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=self._schema_cfg.text_max_len)
            schema.add_field(field_name="metadata", datatype=DataType.JSON)
            schema.add_field(field_name="table", datatype=DataType.VARCHAR, max_length=self._schema_cfg.table_max_len)
            schema.add_field(field_name="lang", datatype=DataType.VARCHAR, max_length=self._schema_cfg.lang_max_len)

            index_params = self._client.prepare_index_params()
            # Milvus Lite (local embedded) supports only FLAT/IVF_FLAT/AUTOINDEX.
            # Milvus server supports HNSW (preferred for v0).
            if self._lite_db:
                index_params.add_index(
                    field_name="vector",
                    index_type="AUTOINDEX",
                    metric_type="COSINE",
                    params={},
                )
            else:
                index_params.add_index(
                    field_name="vector",
                    index_type="HNSW",
                    metric_type="COSINE",
                    params={"M": 16, "efConstruction": 200},
                )

            self._client.create_collection(
                collection_name=name,
                schema=schema,
                index_params=index_params,
            )

        try:
            self._client.load_collection(name)
        except Exception:
            pass

    def upsert(self, collection: str, points: Sequence[Point], *, batch_size: int = 512) -> None:
        if not points:
            return
        self._connect()
        assert self._client is not None
        try:
            self._client.load_collection(collection)
        except Exception:
            pass

        bs = max(1, int(batch_size))
        for i in range(0, len(points), bs):
            batch = points[i : i + bs]
            data = []
            for p in batch:
                meta = dict(p.metadata or {})
                data.append(
                    {
                        "id": str(p.id),
                        "vector": list(map(float, p.vector)),
                        "text": str(p.text or ""),
                        "metadata": meta,
                        "table": str(meta.get("table") or ""),
                        "lang": str(meta.get("lang") or ""),
                    }
                )
            self._client.upsert(collection_name=collection, data=data)

        try:
            self._client.flush(collection_name=collection)
        except Exception:
            pass

    def search(
        self,
        collection: str,
        vector: Sequence[float],
        *,
        top_k: int,
        filters: Optional[FilterDict] = None,
        debug: bool = False,
    ) -> List[Hit]:
        self._connect()
        assert self._client is not None
        try:
            self._client.load_collection(collection)
        except Exception:
            pass

        expr = build_expr(filters)
        # Search params differ by index type; keep minimal defaults for Milvus Lite.
        params = {"metric_type": "COSINE", "params": ({ } if self._lite_db else {"ef": 128})}

        res = self._client.search(
            collection_name=collection,
            data=[list(map(float, vector))],
            anns_field="vector",
            limit=int(top_k),
            filter=expr,
            # Primary key is returned separately; request only non-PK fields.
            output_fields=["text", "metadata", "table", "lang"],
            search_params=params,
        )

        hits: List[Hit] = []
        # PyMilvus MilvusClient may return:
        # - list[list[dict]] (one list per query vector)
        # - list[dict] (already flattened for a single query vector)
        # - SearchResult / HybridHits objects (Milvus Lite)
        rows_any: List[Any] = []
        try:
            first = res[0]  # type: ignore[index]
            try:
                rows_any = list(first)  # HybridHits is iterable
            except Exception:
                # Sometimes first is already list-like
                rows_any = first if isinstance(first, list) else []
        except Exception:
            try:
                rows_any = list(res)  # type: ignore[arg-type]
            except Exception:
                rows_any = []

        for h in rows_any or []:
            try:
                pid = None
                score_f = 0.0
                txt = ""
                meta: Dict[str, Any] = {}

                def _read(obj: Any, key: str) -> Any:
                    if obj is None:
                        return None
                    if isinstance(obj, dict):
                        return obj.get(key)
                    # Some PyMilvus objects expose dict-like access
                    if hasattr(obj, "get"):
                        try:
                            return obj.get(key)  # type: ignore[call-arg]
                        except Exception:
                            pass
                    if hasattr(obj, "__getitem__"):
                        try:
                            return obj[key]  # type: ignore[index]
                        except Exception:
                            pass
                    try:
                        return getattr(obj, key)
                    except Exception:
                        return None

                if isinstance(h, dict):
                    # Dict hit: {id, score/distance, entity:{...}}
                    pid = h.get("id")
                    entity = h.get("entity") or {}
                    if not isinstance(entity, dict):
                        entity = {}
                    txt = str(entity.get("text") or h.get("text") or "")
                    meta_val = entity.get("metadata") if "metadata" in entity else h.get("metadata")
                    meta = dict(meta_val or {}) if isinstance(meta_val, dict) else {}
                    table = entity.get("table") if "table" in entity else h.get("table")
                    lang = entity.get("lang") if "lang" in entity else h.get("lang")
                    if table is not None:
                        meta.setdefault("table", table)
                    if lang is not None:
                        meta.setdefault("lang", lang)
                    score = h.get("score", None)
                    if score is None:
                        score = h.get("distance", None)
                    try:
                        score_f = float(score) if score is not None else 0.0
                    except Exception:
                        score_f = 0.0
                else:
                    # Object hit (HybridHit): has attrs like id, score/distance, entity
                    entity = getattr(h, "entity", None)
                    if entity is None:
                        # Some versions use `.fields` or direct getters
                        entity = getattr(h, "fields", None)
                    pid = _read(h, "id") or getattr(h, "id", None)
                    txt = str(_read(entity, "text") or _read(h, "text") or "")

                    meta_val = _read(entity, "metadata")
                    if meta_val is None:
                        meta_val = _read(h, "metadata")
                    if isinstance(meta_val, dict):
                        meta = dict(meta_val)
                    elif isinstance(meta_val, str) and meta_val.strip():
                        try:
                            parsed = json.loads(meta_val)
                            meta = dict(parsed) if isinstance(parsed, dict) else {}
                        except Exception:
                            meta = {}
                    else:
                        meta = {}

                    table = _read(entity, "table")
                    lang = _read(entity, "lang")
                    if table is None:
                        table = _read(h, "table")
                    if lang is None:
                        lang = _read(h, "lang")
                    if table is not None:
                        meta.setdefault("table", table)
                    if lang is not None:
                        meta.setdefault("lang", lang)

                    score = getattr(h, "score", None)
                    if score is None:
                        score = getattr(h, "distance", None)
                    try:
                        score_f = float(score) if score is not None else 0.0
                    except Exception:
                        score_f = 0.0

                hits.append(
                    Hit(
                        id=str(pid or ""),
                        score=score_f,
                        text=txt,
                        metadata=meta,
                    )
                )
            except Exception:
                continue

        if debug:
            try:
                shape = type(res).__name__
                head = None
                try:
                    head = type(res[0]).__name__  # type: ignore[index]
                except Exception:
                    head = None
                len_res = None
                len_head = None
                try:
                    len_res = len(res)  # type: ignore[arg-type]
                except Exception:
                    len_res = None
                try:
                    len_head = len(res[0])  # type: ignore[index,arg-type]
                except Exception:
                    len_head = None
                print(
                    "MILVUS_SEARCH_DEBUG:",
                    {
                        "expr": expr,
                        "k": int(top_k),
                        "out": len(hits),
                        "shape": shape,
                        "head": head,
                        "len": len_res,
                        "len0": len_head,
                    },
                )
            except Exception:
                pass
        return hits

