"""编排入口：route → compute → (红线固定 / chat 回落 RAG / 否则 polish)。

挂件唯一公开 API：respond(message, session_id, surname, settings) -> str。
"""

from __future__ import annotations

import re
import time
from typing import Optional

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


def respond(
    message: str,
    *,
    session_id: str = "default",
    surname: str = "",
    settings: Optional[Settings] = None,
) -> str:
    """处理一条消息，返回马三多话术。

    单出口集中记日志：每条请求记录命中路径(path)、耗时、问句与回答预览，
    便于事后用 journalctl 排查（命中了哪个意图、是否回落 RAG、是否报错）。
    """
    msg = (message or "").strip()
    if not msg:
        return "老板，您说点啥我好帮您干活～"

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
                reply = _rag_fallback(msg, session_id, surname, s)
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
                    reply = _rag_fallback(msg, session_id, surname, s)
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
    return reply


def _maybe_clarify(msg: str, model: str, last_intent: str) -> str:
    stripped = msg.strip()
    if len(stripped) > 6:
        return ""
    is_digit = stripped.isdigit() and 1 <= int(stripped) <= 20
    if (model or is_digit) and last_intent not in ("buyback", "rental", "composite"):
        what = model or stripped
        return f"老板，你想了解{what}的什么？回收价、参数配置、库存？说清楚我好帮你查~"
    return ""


def _rag_fallback(msg: str, session_id: str, surname: str, settings: Settings) -> str:
    """未命中业务意图时：用 RAG 只做检索，再统一用马三多 SOUL 口吻润色。

    这样既保留知识库依据，又不会出现 RAG 自带 phone_mom 人设导致的语气割裂。
    检索失败则降级为纯闲聊（仍是 SOUL 口吻）。
    """
    contexts: list = []
    try:
        contexts = _retrieve_contexts(msg, settings)
    except Exception:
        contexts = []
    try:
        return polish_with_context(
            msg, contexts, session_id=session_id, surname=surname, settings=settings
        )
    except Exception:
        return polish_chat(msg, session_id=session_id, surname=surname, settings=settings)


def _retrieve_contexts(msg: str, settings: Settings) -> list:
    """复用现有 RAG 的检索层（只取上下文，不用它的 prompt/人设）。"""
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
    return [r.get("text", "") for r in results]
