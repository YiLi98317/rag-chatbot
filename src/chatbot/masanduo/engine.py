"""编排入口：route → compute → (红线固定 / chat 回落 RAG / 否则 polish)。

挂件唯一公开 API：respond(message, session_id, surname, settings) -> str。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import List, Optional

from chatbot.masanduo import compute as compute_mod
from chatbot.masanduo import ecommerce as ecommerce_mod
from chatbot.masanduo import replies
from chatbot.masanduo.extract import extract_model
from chatbot.masanduo.polish import polish, polish_chat, polish_with_context
from chatbot.masanduo.router import is_smalltalk, route
from chatbot.masanduo.session import get_state, save_turn, update_state
from chatbot.observability.logging import get_logger
from chatbot.settings import Settings, get_settings

logger = get_logger("chatbot.masanduo")


@dataclass
class QaOutput:
    """结构化回答契约。answer 保持与旧版一致；其余为附加观测/前端字段。"""
    answer: str
    sources: List[str] = field(default_factory=list)
    confidence: str = "high"          # high | medium | low
    need_human: bool = False
    trace_id: Optional[str] = None
    intent: str = ""
    path: str = ""


_EMPTY_MSG = "老板，您说点啥我好帮您干活～"


def respond(
    message: str,
    *,
    session_id: str = "default",
    surname: str = "",
    role: str = "",
    store_id: str = "",
    user_id: str = "",
    settings: Optional[Settings] = None,
) -> str:
    """向后兼容入口：返回话术字符串（内部调用 respond_full）。"""
    return respond_full(
        message, session_id=session_id, surname=surname, role=role,
        store_id=store_id, user_id=user_id, settings=settings,
    ).answer


def respond_full(
    message: str,
    *,
    session_id: str = "default",
    surname: str = "",
    role: str = "",
    store_id: str = "",
    user_id: str = "",
    settings: Optional[Settings] = None,
) -> QaOutput:
    """处理一条消息，返回结构化 QaOutput（answer + sources/confidence/need_human/trace_id）。

    单出口集中记日志 + Langfuse 打点。role/store_id/user_id 仅用于观测归因，不影响回答。
    """
    msg = (message or "").strip()
    if not msg:
        return QaOutput(answer=_EMPTY_MSG, confidence="high", need_human=False)

    s = settings or get_settings()
    t0 = time.perf_counter()
    state = get_state(session_id)
    last_intent = state.get("last_intent", "")

    intent = route(msg, last_intent)
    model = extract_model(msg)

    # 容量追问：上轮在查回收/置换且记了旧机，这轮只补容量
    cap = re.match(r"^(\d+)\s*[Gg]$", msg)
    if cap and last_intent in ("buyback", "composite") and state.get("old_device"):
        update_state(session_id, old_device=f"{state['old_device']} {cap.group(1)}G")

    path = intent  # 实际走的路径标签，便于排查
    sources: list = []  # RAG 回落时命中的知识库来源（仅用于观测）
    try:
        # 红线 / 人工 / 已下线功能 / 电商素材：固定文案或纯文本，不进 LLM
        if intent == "套机风险":
            reply = replies.taoji_reply(surname)
            update_state(session_id, last_intent="套机风险")
        elif intent == "监管机":
            reply = replies.jianguan_reply(surname)
            update_state(session_id, last_intent="监管机")
        elif intent == "human_agent":
            reply = replies.HUMAN_AGENT_REPLY
            update_state(session_id, last_intent="human_agent")
        elif intent == "poster":
            reply = replies.POSTER_DISABLED_REPLY
            update_state(session_id, last_intent="poster")
        elif intent == "ecommerce":
            reply = ecommerce_mod.flow_ecommerce_assets(
                product_name=model or "",
                selling_points=msg if len(msg) > 3 else "",
            )
            update_state(session_id, last_intent="ecommerce")
        elif intent == "chat":
            clarify = _maybe_clarify(msg, model, last_intent)
            if clarify:
                reply, path = clarify, "chat:clarify"
            elif is_smalltalk(msg):
                reply = polish_chat(msg, session_id=session_id, surname=surname, settings=s)
                path = "chat:smalltalk"
            else:
                reply = _rag_fallback(msg, session_id, surname, s, sources_out=sources)
                path = "chat:rag"
            update_state(session_id, last_intent="chat")
        else:
            # 业务意图：确定性计算 → 润色
            result = compute_mod.compute(msg, session_id, intent, model)
            if result.get("error"):
                logger.warning(
                    "masanduo compute_error session=%s intent=%s err=%s",
                    session_id, intent, result["error"],
                )
                reply, path = result["error"], f"{intent}:error"
            else:
                real_intent = result.get("intent", intent)
                if real_intent == "chat":
                    reply = _rag_fallback(msg, session_id, surname, s, sources_out=sources)
                    path = "chat:rag(compute)"
                else:
                    reply = polish(
                        msg, result, real_intent,
                        session_id=session_id, surname=surname, settings=s,
                    )
                    path = real_intent
    except Exception:
        logger.exception(
            "masanduo_error session=%s intent=%s q=%r", session_id, intent, msg[:80]
        )
        raise

    save_turn(session_id, msg, reply)
    dt_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "masanduo_qa session=%s path=%s ms=%.0f q=%r a=%r",
        session_id, path, dt_ms, msg[:60], (reply or "")[:80],
    )
    confidence, need_human = _confidence_and_handoff(intent, path, sources)
    trace_id = _trace_qa(
        session_id, msg, reply, intent, path, model, dt_ms,
        sources=sources, role=role, store_id=store_id, user_id=user_id,
    )
    return QaOutput(
        answer=reply, sources=list(sources), confidence=confidence,
        need_human=need_human, trace_id=trace_id, intent=intent, path=path,
    )


def _confidence_and_handoff(intent: str, path: str, sources: list) -> tuple[str, bool]:
    """由命中路径/来源派生 confidence 与 need_human（简单可解释规则）。"""
    if path.endswith(":error"):
        return "low", True
    if intent == "human_agent":
        return "high", True
    if path.startswith("chat:rag"):
        return ("medium", False) if sources else ("low", True)
    # 红线固定文案 / 业务确定性计算 / 闲聊澄清：视为高置信
    return "high", False


def _trace_qa(
    session_id: str,
    msg: str,
    reply: str,
    intent: str,
    path: str,
    model: str,
    dt_ms: float,
    *,
    sources: Optional[list] = None,
    role: str = "",
    store_id: str = "",
    user_id: str = "",
) -> Optional[str]:
    """把本轮问答上报 Langfuse，返回 trace_id。故障安全：任何异常都不影响正常返回。"""
    try:
        from chatbot.observability.langfuse_tracing import log_qa

        return log_qa(
            session_id=session_id,
            question=msg,
            answer=reply or "",
            intent=intent,
            path=path,
            model=model,
            latency_ms=dt_ms,
            sources=sources or None,
            role=role,
            store_id=store_id,
            user_id=user_id,
        )
    except Exception:
        logger.debug("trace_qa failed", exc_info=True)
        return None


def _maybe_clarify(msg: str, model: str, last_intent: str) -> str:
    stripped = msg.strip()
    if len(stripped) > 6:
        return ""
    is_digit = stripped.isdigit() and 1 <= int(stripped) <= 20
    if (model or is_digit) and last_intent not in ("buyback", "rental", "composite"):
        what = model or stripped
        return f"老板，你想了解{what}的什么？回收价、参数配置、库存？说清楚我好帮你查~"
    return ""


def _rag_fallback(
    msg: str,
    session_id: str,
    surname: str,
    settings: Settings,
    sources_out: Optional[list] = None,
) -> str:
    """未命中业务意图时：用 RAG 只做检索，再统一用马三多 SOUL 口吻润色。

    这样既保留知识库依据，又不会出现 RAG 自带 phone_mom 人设导致的语气割裂。
    检索失败则降级为纯闲聊（仍是 SOUL 口吻）。
    sources_out 若提供，则填入本次命中的知识库来源名（仅用于观测）。
    """
    results: list = []
    try:
        results = _retrieve_results(msg, settings)
    except Exception:
        results = []
    if sources_out is not None:
        for r in results:
            meta = r.get("metadata", {}) or {}
            name = meta.get("source") or meta.get("title") or meta.get("Name")
            if name and str(name) not in sources_out:
                sources_out.append(str(name))
    contexts = [r.get("text", "") for r in results]
    try:
        return polish_with_context(
            msg, contexts, session_id=session_id, surname=surname, settings=settings
        )
    except Exception:
        return polish_chat(msg, session_id=session_id, surname=surname, settings=settings)


def _retrieve_results(msg: str, settings: Settings) -> list:
    """复用现有 RAG 的检索层（返回带 metadata 的原始结果，供取上下文与来源）。"""
    from chatbot.retrieval.retriever import retrieve_top_k
    from chatbot.vectorstore import get_vector_store

    store = get_vector_store(settings)
    k = int(getattr(settings, "default_top_k", 5) or 5)
    results = retrieve_top_k(
        store=store,
        collection=settings.default_collection,
        query=msg,
        embed_model=settings.embed_model,
        ollama_base_url=settings.ollama_base_url,
        top_k=k,
        db_uri=settings.db_uri,
    )
    return results
