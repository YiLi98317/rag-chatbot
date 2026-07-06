"""Langfuse 打点（可选、故障安全）。

设计目标：
- 完全可选：未配置 LANGFUSE_* 环境变量时是 no-op，不引入任何行为变化。
- 故障安全：任何异常都吞掉并只记 debug 日志，绝不影响正常问答返回。
- 版本容忍：兼容 langfuse SDK v3（start_span/update_trace）与 v2（trace）。

启用方式（环境变量）：
  LANGFUSE_PUBLIC_KEY=pk-lf-...
  LANGFUSE_SECRET_KEY=sk-lf-...
  LANGFUSE_HOST=http://localhost:3000
  # 可选：让中文以原文而非 \\uXXXX 存储
  LANGFUSE_ENSURE_ASCII=false
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional

from chatbot.observability.logging import get_logger

logger = get_logger("chatbot.langfuse")

_LOCK = threading.Lock()
_CLIENT: Any = None
_INIT_DONE = False


def _get_client() -> Any:
    """惰性创建 Langfuse 客户端。未配置或导入失败返回 None（no-op）。"""
    global _CLIENT, _INIT_DONE
    if _INIT_DONE:
        return _CLIENT
    with _LOCK:
        if _INIT_DONE:
            return _CLIENT
        _INIT_DONE = True
        pk = (os.getenv("LANGFUSE_PUBLIC_KEY") or "").strip()
        sk = (os.getenv("LANGFUSE_SECRET_KEY") or "").strip()
        host = (os.getenv("LANGFUSE_HOST") or "").strip()
        if not (pk and sk and host):
            logger.info("langfuse disabled (LANGFUSE_* not fully set)")
            _CLIENT = None
            return None
        try:
            from langfuse import Langfuse  # type: ignore

            _CLIENT = Langfuse(public_key=pk, secret_key=sk, host=host)
            logger.info("langfuse enabled host=%s", host)
        except Exception:
            logger.warning("langfuse import/init failed; tracing disabled", exc_info=True)
            _CLIENT = None
        return _CLIENT


def log_qa(
    *,
    session_id: str,
    question: str,
    answer: str,
    intent: str = "",
    path: str = "",
    model: str = "",
    latency_ms: float = 0.0,
    sources: Optional[List[str]] = None,
    role: str = "",
    store_id: str = "",
    user_id: str = "",
    tags: Optional[List[str]] = None,
) -> Optional[str]:
    """把一次问答记录为 Langfuse trace。故障安全：任何异常都不外抛。

    归因：Langfuse userId 用 store_id（门店）优先，其次 user_id；role 进 tags/metadata。
    返回：Langfuse trace_id（供前端反馈挂分用），未启用/失败返回 None。
    """
    client = _get_client()
    if client is None:
        return None
    metadata: Dict[str, Any] = {
        "intent": intent,
        "path": path,
        "model": model,
        "latency_ms": round(latency_ms, 1),
    }
    if sources:
        metadata["sources"] = sources
    if role:
        metadata["role"] = role
    if store_id:
        metadata["store_id"] = store_id
    if user_id:
        metadata["user_id"] = user_id
    lf_user_id = store_id or user_id or None
    trace_tags = list(tags) if tags else []
    if intent and intent not in trace_tags:
        trace_tags.append(intent)
    if role and role not in trace_tags:
        trace_tags.append(role)
    trace_id: Optional[str] = None
    try:
        # v3 SDK: 以 span 承载，并在 trace 级别写入 session/user/input/output/tags。
        if hasattr(client, "start_span"):
            span = client.start_span(name="masanduo_qa", input=question, metadata=metadata)
            trace_id = getattr(span, "trace_id", None)
            try:
                if hasattr(span, "update"):
                    span.update(output=answer)
                if hasattr(span, "update_trace"):
                    span.update_trace(
                        session_id=session_id,
                        user_id=lf_user_id,
                        input=question,
                        output=answer,
                        tags=trace_tags,
                        metadata=metadata,
                    )
            finally:
                if hasattr(span, "end"):
                    span.end()
        # v2 SDK 回退
        elif hasattr(client, "trace"):
            t = client.trace(
                name="masanduo_qa",
                input=question,
                output=answer,
                session_id=session_id,
                user_id=lf_user_id,
                tags=trace_tags,
                metadata=metadata,
            )
            trace_id = getattr(t, "id", None)
    except Exception:
        logger.debug("langfuse log_qa failed", exc_info=True)
    return trace_id


def log_feedback(
    *,
    trace_id: str,
    value: float,
    reason: str = "",
    comment: str = "",
    tags: Optional[List[str]] = None,
) -> bool:
    """把用户反馈作为 score 挂到指定 trace。故障安全：失败返回 False，不外抛。

    value 约定：1=好评(👍)，0=差评(👎)。reason/comment 合并进 comment。
    """
    client = _get_client()
    if client is None or not trace_id:
        return False
    note = " | ".join(x for x in [reason, comment] if x) or None
    try:
        if hasattr(client, "create_score"):
            client.create_score(
                trace_id=trace_id, name="user_feedback", value=value, comment=note
            )
        elif hasattr(client, "score"):
            client.score(trace_id=trace_id, name="user_feedback", value=value, comment=note)
        else:
            return False
        return True
    except Exception:
        logger.debug("langfuse log_feedback failed", exc_info=True)
        return False
