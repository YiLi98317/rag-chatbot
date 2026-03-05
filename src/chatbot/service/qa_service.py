from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from chatbot.llm.client import generate as llm_generate, generate_with_metrics
from chatbot.observability.logging import get_logger
from chatbot.rag.pipeline import build_prompt
from chatbot.retrieval.retriever import retrieve_top_k
from chatbot.settings import Settings, get_settings
from chatbot.vectorstore import get_vector_store


logger = get_logger("chatbot.qa_service")


@dataclass(frozen=True)
class QaResult:
    answer: str
    citations: List[Dict[str, Any]]
    trace_id: str
    retrieval: Optional[Dict[str, Any]] = None
    performance_metrics: Optional[Dict[str, Any]] = None


def answer_question(
    question: str,
    *,
    top_k: Optional[int] = None,
    filters: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    settings: Optional[Settings] = None,
    debug_traces: bool = False,
) -> QaResult:
    """
    Shared entrypoint for CLI and API.

    v0: wraps existing pipeline (embed->retrieve->prompt->generate) without rewriting logic.
    """
    s = settings or get_settings()
    store = get_vector_store(s)
    trace_id = str(uuid.uuid4())

    k = int(top_k) if top_k is not None else int(getattr(s, "default_top_k", 10) or 10)

    logger.info(
        "qa_request trace_id=%s provider=%s k=%s session_id=%s",
        trace_id,
        getattr(s, "vector_provider", ""),
        k,
        session_id or "",
    )

    # Retrieval with optional performance metrics
    retrieval_metrics: Dict[str, Any] = {}
    results = retrieve_top_k(
        store=store,
        collection=s.default_collection,
        query=question,
        embed_model=s.embed_model,
        ollama_base_url=s.ollama_base_url,
        top_k=k,
        db_uri=s.db_uri,
        debug=bool(debug_traces),
        filters_override=filters,
        out_metrics=retrieval_metrics,
    )

    contexts = [r.get("text", "") for r in results]
    t_prompt_start = time.perf_counter()
    prompt = build_prompt(question, contexts, debug=False)
    t_prompt_build_s = time.perf_counter() - t_prompt_start

    answer, usage_dict, t_llm_total_s, t_llm_first_token_s = generate_with_metrics(
        prompt, settings=s
    )

    t_post_start = time.perf_counter()
    citations: List[Dict[str, Any]] = []
    for r in results:
        meta = r.get("metadata", {}) or {}
        citations.append(
            {
                "source": meta.get("source"),
                "table": meta.get("table"),
                "pk": meta.get("pk"),
                "score": r.get("score"),
                "title": meta.get("title") or meta.get("Name") or meta.get("TrackId"),
            }
        )
    t_postprocess_s = time.perf_counter() - t_post_start

    performance_metrics: Optional[Dict[str, Any]] = {
        "t_embed_query_s": retrieval_metrics.get("t_embed_query_s", 0.0),
        "t_retrieve_s": retrieval_metrics.get("t_retrieve_s", 0.0),
        "t_rerank_s": retrieval_metrics.get("t_rerank_s"),
        "t_prompt_build_s": t_prompt_build_s,
        "t_llm_first_token_s": t_llm_first_token_s,
        "t_llm_total_s": t_llm_total_s,
        "t_postprocess_s": t_postprocess_s,
        "query_length_chars": retrieval_metrics.get("query_length_chars", len(question)),
        "context_count": retrieval_metrics.get("context_count", len(contexts)),
        "prompt_length_chars": len(prompt),
        "prompt_tokens": usage_dict.get("prompt_tokens") if usage_dict else None,
        "completion_tokens": usage_dict.get("completion_tokens") if usage_dict else None,
        "total_tokens": usage_dict.get("total_tokens") if usage_dict else None,
    }

    logger.info(
        "qa_latency trace_id=%s retrieval_s=%.2f llm_s=%.2f total_s=%.2f",
        trace_id,
        retrieval_metrics.get("t_embed_query_s", 0) + retrieval_metrics.get("t_retrieve_s", 0),
        t_llm_total_s,
        retrieval_metrics.get("t_embed_query_s", 0) + retrieval_metrics.get("t_retrieve_s", 0) + t_llm_total_s + t_prompt_build_s + t_postprocess_s,
    )

    retrieval_debug: Optional[Dict[str, Any]] = None
    if debug_traces:
        retrieval_debug = {
            "top_k": k,
            "collection": s.default_collection,
            "hits": [
                {
                    "score": r.get("score"),
                    "metadata": r.get("metadata", {}),
                    "text_head": (r.get("text", "") or "").replace("\n", " ")[:240],
                }
                for r in results[: min(k, 10)]
            ],
        }

    return QaResult(
        answer=(answer or "").strip(),
        citations=citations,
        trace_id=trace_id,
        retrieval=retrieval_debug,
        performance_metrics=performance_metrics,
    )

