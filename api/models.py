from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class QaRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    filters: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None


class Citation(BaseModel):
    source: Optional[str] = None
    table: Optional[str] = None
    pk: Optional[Any] = None
    score: Optional[float] = None
    title: Optional[str] = None


class PerformanceMetrics(BaseModel):
    """Per-stage timings and counts for the RAG pipeline."""

    t_embed_query_s: float = 0.0
    t_retrieve_s: float = 0.0
    t_rerank_s: Optional[float] = None
    t_prompt_build_s: float = 0.0
    t_llm_first_token_s: Optional[float] = None
    t_llm_total_s: float = 0.0
    t_postprocess_s: float = 0.0
    query_length_chars: int = 0
    context_count: int = 0
    prompt_length_chars: int = 0
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class QaResponse(BaseModel):
    answer: str
    citations: List[Citation]
    trace_id: str
    retrieval: Optional[Dict[str, Any]] = None
    performance_metrics: Optional[PerformanceMetrics] = None

