from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class QaRequest(BaseModel):
    question: str = Field(..., min_length=1)
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    filters: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None
    # 观测归因（可选，仅用于 Langfuse，不影响回答）
    role: Optional[str] = None
    store_id: Optional[str] = None
    user_id: Optional[str] = None


class Citation(BaseModel):
    source: Optional[str] = None
    table: Optional[str] = None
    pk: Optional[Any] = None
    score: Optional[float] = None
    title: Optional[str] = None


class PerformanceMetrics(BaseModel):
    """Per-stage timings and counts for the RAG pipeline."""

    planner_skipped: bool = False
    t_query_plan_s: float = 0.0
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
    # 结构化契约（可选，前端旧解析只用 answer，不受影响）
    sources: Optional[List[str]] = None
    confidence: Optional[str] = None
    need_human: Optional[bool] = None


class FeedbackRequest(BaseModel):
    trace_id: str = Field(..., min_length=1)
    value: int = Field(..., ge=0, le=1)  # 1=👍 0=👎
    reason: Optional[str] = None
    comment: Optional[str] = None
    session_id: Optional[str] = None


class FeedbackResponse(BaseModel):
    ok: bool

