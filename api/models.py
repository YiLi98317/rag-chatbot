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


class QaResponse(BaseModel):
    answer: str
    citations: List[Citation]
    trace_id: str
    retrieval: Optional[Dict[str, Any]] = None

