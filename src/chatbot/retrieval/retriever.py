from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import asdict
import json

from chatbot.embeddings.provider import embed_text
from chatbot.vectorstore.base import VectorStore
from chatbot.retrieval.lexical import normalize_query, lexical_lookup
from chatbot.retrieval.entity_resolver import resolve_entity
from chatbot.retrieval.bm25 import search_bm25_as_dicts
from chatbot.retrieval.prf import apply_prf_bm25
from chatbot.retrieval.query_expansion import apply_qexp_bm25
from chatbot.sql.row_to_doc import row_to_text
from pathlib import Path
from chatbot.retrieval.query_planner import plan_query, deterministic_fallback_plan, QueryPlan
import time
from chatbot.observability.metrics import MetricsRecorder
from chatbot.retrieval.normalize import detect_lang


def retrieve_top_k(
    store: VectorStore,
    collection: str,
    query: str,
    embed_model: str,
    ollama_base_url: str,
    top_k: int = 4,
    db_uri: Optional[str] = None,
    debug: bool = False,
    filters_override: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    # 0) Query Planner
    try:
        from chatbot.config import get_settings
        settings = get_settings()
    except Exception:
        settings = None
    query_lang = detect_lang(query)
    recorder: Optional[MetricsRecorder] = None
    if settings and getattr(settings, "obs_metrics_enabled", False):
        recorder = MetricsRecorder()
        recorder.start(query, lang=query_lang)
    supported_tables = [
        "THUCNews",
        "Company",
        "Track",
        "Album",
        "Artist",
        "Customer",
        "Employee",
        "Invoice",
        "InvoiceLine",
        "Playlist",
        "Genre",
        "MediaType",
    ]
    if settings:
        enable_planner = getattr(settings, "enable_query_planner", True)
    else:
        enable_planner = False
    if debug:
        try:
            print("PLANNER_CONFIG:")
            print("  enable_llm:", bool(enable_planner))
            if settings:
                print("  llm_provider:", getattr(settings, "llm_provider", ""))
                print("  model_name:", getattr(settings, "model_name", ""))
                print("  ollama_base_url:", getattr(settings, "ollama_base_url", ""))
        except Exception:
            pass
    if settings:
        plan: QueryPlan = plan_query(
            raw_query=query,
            settings=settings,
            supported_tables=supported_tables,
            enable_llm=enable_planner,
            debug=debug,
        )
    else:
        plan = deterministic_fallback_plan(query, supported_tables)
    if debug:
        try:
            print("QUERY_PLAN:")
            print(json.dumps(asdict(plan), indent=2))
        except Exception:
            pass
    if debug:
        try:
            # Derive base_text consistent with planner post-processing
            if plan.intent == "entity_lookup" and plan.entity_candidates:
                base_text = plan.entity_candidates[0]
            else:
                base_text = plan.lexical_query or query
            print("PIPELINE_LOG:")
            print("  lang:", query_lang)
            print("  user_input_raw:", repr(getattr(plan, "user_input_raw", query)))
            print("  normalized_query:", repr(getattr(plan, "query_normalized", "")))
            print("  fts_query_primary:", repr(getattr(plan, "query_for_fts_primary", "")))
            print("  fts_query_fallback:", repr(getattr(plan, "query_for_fts_fallback", "")))
            print("  fuzzy_query_used:", repr(getattr(plan, "query_for_fuzzy", getattr(plan, 'fuzzy_candidate', ''))))
            print("  vector_query_used:", repr(plan.vector_query or plan.vector_query_clean or query))
        except Exception:
            pass

    # Resolve DB URI if not provided
    resolved_db_uri: Optional[str] = db_uri
    if not resolved_db_uri:
        try:
            from chatbot.config import get_settings

            settings = get_settings()
            if settings.db_uri:
                resolved_db_uri = settings.db_uri
            else:
                # Best-effort fallback to bundled Chinook SQLite if present
                default_sqlite = Path(settings.data_dir) / "chinook" / "Chinook_Sqlite.sqlite"
                if default_sqlite.exists():
                    resolved_db_uri = f"sqlite:///{default_sqlite}"
        except Exception:
            resolved_db_uri = None

    # Semantic query selection
    if plan.intent == "entity_lookup":
        semantic_query = plan.vector_query or query
    else:
        semantic_query = plan.vector_query_clean or plan.vector_query or query
    used_lexical = False
    if resolved_db_uri:
        try:
            # New resolver
            t_resolver_start = time.time()
            res = resolve_entity(
                db_uri=resolved_db_uri,
                query=query,
                lexical_query=plan.lexical_query or query,
                lexical_tokens=getattr(plan, "lexical_tokens", None) or None,
                intent=getattr(plan, "intent", None),
                preferred_tables=plan.preferred_tables or None,
                # Provide explicit variants for improved control
                normalized_query=getattr(plan, "query_normalized", "") or None,
                fts_query_primary=getattr(plan, "query_for_fts_primary", "") or None,
                fts_query_fallback=getattr(plan, "query_for_fts_fallback", "") or None,
                fuzzy_query=getattr(plan, "query_for_fuzzy", "") or getattr(plan, "fuzzy_candidate", "") or None,
                limit=50,
                debug=debug,
            )
            t_resolver_end = time.time()
            decision = res.get("decision", "low")
            hits = res.get("hits", []) or []
            primary_candidate = res.get("primary_candidate") or ""
            if debug:
                try:
                    print("RESOLVER_RESULT:")
                    print("  decision:", decision)
                    print("  hits:", len(hits))
                    if hits:
                        top = hits[0]
                        print(
                            "  top:",
                            f"{top.get('entity_type')}:{top.get('entity_id')} "
                            f"name={top.get('name')!r} fuzzy={top.get('fuzzy'):.1f}",
                        )
                except Exception:
                    pass
            if recorder is not None:
                recorder.record_level(
                    level="L0_RESOLVER",
                    t_start=t_resolver_start,
                    t_end=t_resolver_end,
                    candidates_out=len(hits),
                    stop_reason=str(decision),
                )
            if decision == "low" and (plan.vector_query or primary_candidate):
                # Use planner vector query, else normalized candidate for Qdrant fallback
                if plan.intent == "entity_lookup":
                    semantic_query = plan.vector_query or primary_candidate
                else:
                    semantic_query = plan.vector_query_clean or plan.vector_query or primary_candidate
                if debug:
                    print(f"FALLBACK_SEMANTIC_QUERY: {semantic_query!r}")
                # Before falling back to Qdrant, attempt lexical BM25-based fallbacks (L1-L3).
                # These layers are English-centric; skip them for zh/mixed.
                if query_lang == "en":
                    # L1: BM25 directly on the primary/fallback phrase
                    try:
                        bm25_phase_query = (plan.lexical_query or primary_candidate or query) or query
                        t_bm25_start = time.time()
                        bm25_hits = search_bm25_as_dicts(
                            db_uri=resolved_db_uri,
                            query=bm25_phase_query,
                            entity_types=res.get("entity_types") or None,
                            limit=max(top_k, 10),
                        )
                        t_bm25_end = time.time()
                        if recorder is not None:
                            recorder.record_level(
                                level="L1_BM25",
                                t_start=t_bm25_start,
                                t_end=t_bm25_end,
                                candidates_out=len(bm25_hits),
                            )
                        if bm25_hits:
                            if debug:
                                print(f"BM25_FALLBACK_USED: {len(bm25_hits)} hits")
                            if recorder is not None:
                                recorder.end_and_write()
                            return bm25_hits[:top_k]
                    except Exception as e:
                        if debug:
                            print(f"BM25_FALLBACK_ERROR: {e}")
                    # L2: PRF (Rocchio-like) expansion then BM25
                    try:
                        t_prf_start = time.time()
                        prf_hits = apply_prf_bm25(
                            db_uri=resolved_db_uri,
                            query=bm25_phase_query,
                            entity_types=res.get("entity_types") or None,
                            seed_k=10,
                            expansion_tokens=5,
                            top_k=max(top_k, 10),
                        )
                        t_prf_end = time.time()
                        if recorder is not None:
                            recorder.record_level(
                                level="L2_PRF",
                                t_start=t_prf_start,
                                t_end=t_prf_end,
                                candidates_out=len(prf_hits),
                            )
                        if prf_hits:
                            if debug:
                                print(f"PRF_FALLBACK_USED: {len(prf_hits)} hits")
                            if recorder is not None:
                                recorder.end_and_write()
                            return prf_hits[:top_k]
                    except Exception as e:
                        if debug:
                            print(f"PRF_FALLBACK_ERROR: {e}")
                    # L3: Deterministic query expansion then BM25
                    try:
                        t_qexp_start = time.time()
                        qexp_hits = apply_qexp_bm25(
                            db_uri=resolved_db_uri,
                            query=bm25_phase_query,
                            entity_types=res.get("entity_types") or None,
                            top_k=max(top_k, 10),
                        )
                        t_qexp_end = time.time()
                        if recorder is not None:
                            recorder.record_level(
                                level="L3_QEXP",
                                t_start=t_qexp_start,
                                t_end=t_qexp_end,
                                candidates_out=len(qexp_hits),
                            )
                        if qexp_hits:
                            if debug:
                                print(f"QEXP_FALLBACK_USED: {len(qexp_hits)} hits")
                            if recorder is not None:
                                recorder.end_and_write()
                            return qexp_hits[:top_k]
                    except Exception as e:
                        if debug:
                            print(f"QEXP_FALLBACK_ERROR: {e}")
            if decision == "high" and hits:
                used_lexical = True
                if debug:
                    print("LEXICAL_DECISION: used_resolver=true level=high fallback_qdrant=false")
                # Fetch rows and construct contexts
                # Build simple fetch by table & pk
                from sqlalchemy import create_engine, text as sql_text

                engine = create_engine(resolved_db_uri)
                results: List[Dict] = []
                with engine.begin() as conn:
                    for h in hits[:top_k]:
                        table = h["entity_type"]
                        pk_name = "TrackId" if table == "Track" else "AlbumId" if table == "Album" else "ArtistId"
                        pk_val = int(h["entity_id"])
                        row = None
                        for r in conn.execute(sql_text(f"SELECT * FROM {table} WHERE {pk_name} = :id LIMIT 1"), {"id": pk_val}):
                            row = dict(r._mapping)
                            break
                        if not row:
                            continue
                        text_val = row_to_text(table, row)
                        metadata = {
                            "table": table,
                            "pk": pk_val,
                            "title": h.get("name"),
                            "source": f"db:{table}:{pk_val}",
                        }
                        if table == "Track":
                            for k in ("TrackId", "Name", "Composer", "AlbumId", "GenreId"):
                                if k in row:
                                    metadata[k] = row[k]
                        elif table == "Album":
                            for k in ("AlbumId", "Title"):
                                if k in row:
                                    metadata[k] = row[k]
                        elif table == "Artist":
                            for k in ("ArtistId", "Name"):
                                if k in row:
                                    metadata[k] = row[k]
                        results.append({"text": text_val, "score": float(h.get("final", 0.0)), "metadata": metadata})
                return results
            elif decision == "medium" and hits:
                used_lexical = True
                if debug:
                    print("LEXICAL_DECISION: used_resolver=true level=medium fallback_qdrant=false")
                # Return top suggestions as contexts for the chat layer to prompt user
                suggestions = hits[:3]
                summary_lines = []
                for s in suggestions:
                    summary_lines.append(f"{s['entity_type']} {s['name']} (id={s['entity_id']})")
                summary_text = "Close matches found:\n" + "\n".join(f"- {x}" for x in summary_lines)
                return [
                    {
                        "text": summary_text,
                        "score": float(suggestions[0].get("final", 0.0)),
                        "metadata": {
                            "resolver_decision": "medium",
                            "suggestions": suggestions,
                        },
                    }
                ]
            else:
                if debug:
                    print("LEXICAL_DECISION: used_resolver=false level=low fallback_qdrant=true")
        except Exception as e:
            if debug:
                print(f"LEXICAL_ERROR: {e}. Falling back to Qdrant.")
                try:
                    print("RESOLVER_RESULT:")
                    print("  decision:", "error")
                    print("  hits:", 0)
                except Exception:
                    pass
                try:
                    print("LEXICAL_DECISION: used_resolver=false level=error fallback_qdrant=true")
                except Exception:
                    pass
    else:
        if debug:
            print("LEXICAL_INFO: No DB URI resolved; skipping lexical lookup, using Qdrant.")

    # 1) Log A — the exact text being embedded for retrieval
    if debug:
        print("QDRANT_QUERY_TEXT:", repr(semantic_query))
        try:
            print("QDRANT_QUERY_LEN:", len(semantic_query))
            print("QDRANT_QUERY_HEAD:", semantic_query[:200])
        except Exception:
            pass

    t_vec_start = time.time()
    provider = "ollama"
    try:
        if settings and getattr(settings, "embed_provider", None):
            provider = str(getattr(settings, "embed_provider", "ollama"))
    except Exception:
        provider = "ollama"
    query_vec = embed_text(
        semantic_query,
        provider=provider,
        model=embed_model,
        ollama_base_url=ollama_base_url,
    )

    # 2) Log B — embedding vector sanity
    if debug:
        try:
            dim = len(query_vec) if hasattr(query_vec, "__len__") else None
            norm = (sum(x * x for x in query_vec) ** 0.5) if dim else None
            print("EMBED_DIM:", dim)
            print("EMBED_NORM:", norm)
        except Exception:
            pass

    # Build generic vector-store filters from planner (v0: table/lang only)
    filters: Optional[Dict[str, Any]] = None
    table_filter: Optional[Dict[str, Any]] = None
    lang_filter: Optional[Dict[str, Any]] = None
    try:
        query_lang = detect_lang(query)

        tables = []
        if isinstance(plan.filters.get("table"), list):
            tables = [t for t in plan.filters.get("table", []) if isinstance(t, str)]
        if tables:
            table_filter = {"table": tables}

        if query_lang == "en":
            lang_filter = {"lang": ["en", "mixed"]}
        elif query_lang == "zh":
            lang_filter = {"lang": ["zh", "mixed"]}
        else:
            lang_filter = None

        if table_filter and lang_filter:
            filters = {**table_filter, **lang_filter}
        else:
            filters = table_filter or lang_filter
    except Exception:
        filters = None
    if filters_override and isinstance(filters_override, dict):
        # v0: merge supported keys (table/lang) into the computed filter.
        merged = dict(filters or {})
        for k in ("table", "lang"):
            v = filters_override.get(k)
            if isinstance(v, list) and v:
                merged[k] = v
        filters = merged or filters
    if debug:
        print("VECTOR_FILTERS_APPLIED:", bool(filters))

    scored = store.search(
        collection=collection,
        vector=query_vec,
        top_k=max(top_k, 10),
        filters=filters,
        debug=debug,
    )
    # If we applied a table filter and got nothing, retry without the table filter.
    # This prevents "wrong table schema" (e.g. Chinook tables) from blocking retrieval
    # in corpora like THUCNews where payload.table differs.
    if (not scored) and table_filter is not None:
        retry_filters = lang_filter  # keep language routing if present
        if debug:
            try:
                print("VECTOR_FILTER_FALLBACK: dropped table filter (0 results)")
                print("VECTOR_FILTERS_RETRY_APPLIED:", bool(retry_filters))
            except Exception:
                pass
        scored = store.search(
            collection=collection,
            vector=query_vec,
            top_k=max(top_k, 10),
            filters=retry_filters,
            debug=debug,
        )
    t_vec_end = time.time()
    if recorder is not None:
        recorder.record_level(
            level="L4_VECTOR",
            t_start=t_vec_start,
            t_end=t_vec_end,
            candidates_out=len(scored) if hasattr(scored, "__len__") else 0,
        )

    # 3) Log C — raw vector results before any reranking/MMR
    if debug:
        try:
            print("VECTOR_RAW_TOP10:")
            for i, sp in enumerate((scored or [])[:10], 1):
                meta = getattr(sp, "metadata", {}) or {}
                pid = getattr(sp, "id", None)
                score = float(getattr(sp, "score", 0.0))
                table = meta.get("table")
                pk = meta.get("pk")
                text = getattr(sp, "text", "") or ""
                text_head = (text or "").replace("\n", " ")[:200]
                print(i, pid, f"{score:.4f}", "table=", table, "pk=", pk)
                print("   text_head:", text_head)
        except Exception:
            pass

    # If resolver was low but vector retrieval produced results, return a UX-oriented message
    if not used_lexical and scored:
        try:
            # Only use the "closest matches" UX for Chinook-like entity tables.
            # For document corpora (e.g. THUCNews, Company), return the actual text contexts instead.
            CHINOOK_TABLES = {
                "Track",
                "Album",
                "Artist",
                "Customer",
                "Employee",
                "Invoice",
                "InvoiceLine",
                "Playlist",
                "Genre",
                "MediaType",
            }
            top3 = []
            for sp in (scored or [])[:3]:
                meta = getattr(sp, "metadata", {}) or {}
                top3.append(
                    {
                        "table": meta.get("table"),
                        "title": meta.get("title") or meta.get("Name") or meta.get("TrackId") or "",
                        "pk": meta.get("pk"),
                        "score": float(getattr(sp, "score", 0.0)),
                        "text_head": (getattr(sp, "text", "") or "").replace("\n", " ")[:200],
                    }
                )
            tables = {m.get("table") for m in top3 if m.get("table")}
            any_title = any((m.get("title") or "").strip() for m in top3)
            if not (tables and tables.issubset(CHINOOK_TABLES) and any_title):
                raise RuntimeError("skip_low_with_qdrant_for_document_corpora")
            summary_lines = []
            for m in top3:
                summary_lines.append(f"{m.get('table')} {m.get('title')}")
            summary_text = "Closest matches in this database:\n" + "\n".join(f"- {x}" for x in summary_lines)
            out = [
                {
                    "text": summary_text,
                    "score": float(top3[0].get("score", 0.0)),
                    "metadata": {
                        "resolver_decision": "low_with_qdrant",
                        "matches": top3,
                    },
                }
            ]
            if recorder is not None:
                recorder.end_and_write()
            return out
        except Exception:
            pass

    results: List[Dict] = []
    for sp in (scored or [])[:top_k]:
        results.append(
            {
                "text": getattr(sp, "text", "") or "",
                "score": float(getattr(sp, "score", 0.0)),
                "metadata": getattr(sp, "metadata", {}) or {},
            }
        )
    if recorder is not None:
        recorder.end_and_write()
    return results
