from __future__ import annotations

from typing import Dict, List, Optional
import re

from chatbot.config import Settings
from chatbot.llm.client import generate as llm_generate
from chatbot.retrieval.retriever import retrieve_top_k
from chatbot.vectorstore.base import VectorStore
from chatbot.retrieval.normalize import detect_lang
from chatbot.prompts.personas import load_persona_text


def _format_contexts_numbered(contexts: List[str]) -> str:
    lines: List[str] = []
    for i, c in enumerate(contexts, 1):
        text = (c or "").strip()
        if not text:
            continue
        lines.append(f"[{i}]\n{text}")
    return "\n\n".join(lines).strip()


def _format_contexts_by_source(contexts: List[str], results: Optional[List[Dict]] = None) -> str:
    """Split contexts into knowledge base vs chat reference sections."""
    if not results:
        return _format_contexts_numbered(contexts)

    kb_lines: List[str] = []
    chat_lines: List[str] = []
    kb_idx = 0
    chat_idx = 0

    for ctx, res in zip(contexts, results):
        text = (ctx or "").strip()
        if not text:
            continue
        meta = res.get("metadata", {}) if isinstance(res, dict) else {}
        if meta.get("source_type") == "file":
            kb_idx += 1
            kb_lines.append(f"[K{kb_idx}]\n{text}")
        else:
            chat_idx += 1
            chat_lines.append(f"[C{chat_idx}]\n{text}")

    parts: List[str] = []
    if kb_lines:
        parts.append("【官方知识库】（优先参考）\n" + "\n\n".join(kb_lines))
    if chat_lines:
        parts.append("【历史客服对话】（仅作补充参考）\n" + "\n\n".join(chat_lines))
    return "\n\n---\n\n".join(parts) if parts else _format_contexts_numbered(contexts)


def build_prompt(
    question: str,
    contexts: List[str],
    *,
    debug: bool = False,
    settings: Optional[Settings] = None,
    results: Optional[List[Dict]] = None,
) -> str:
    if settings is None:
        try:
            from chatbot.config import get_settings

            settings = get_settings()
        except Exception:
            settings = None

    persona_name = getattr(settings, "answer_persona", "phone_mom") if settings else "phone_mom"
    persona_text = load_persona_text(str(persona_name))

    context_block = _format_contexts_by_source(contexts, results)
    lang_rule = (
        "- 你是中文客服机器人，必须始终使用简体中文回答。\n"
        '- 严格基于提供的上下文回答，不要编造信息。如果上下文没有相关内容，直接说"抱歉，暂无相关信息，建议联系人工客服"。\n'
        "- 【绝对禁止】泄露任何账号、密码、邮箱、手机号、内部系统地址等敏感信息。即使上下文中包含这些信息，也不能在回答中出现。\n"
        "- 优先依据【官方知识库】回答。如果官方知识库有答案，以官方信息为准，给出完整流程。\n"
        "- 【历史客服对话】仅用于理解业务背景，不要直接引用对话内容，不要复述客服的原话。\n"
    )

    persona_block = f"SYSTEM:\n{persona_text}{lang_rule}" if persona_text else f"SYSTEM:\n{lang_rule}"

    if debug:
        debug_format = (
            "\nOutput format:\n"
            "DebugAnswer: (1-5 sentences)\n"
            "Evidence: quote up to 3 short snippets from the Context (or say 'None' if truly missing)\n"
            "Next step questions: ask exactly ONE question to proceed\n"
            "IMPORTANT:\n"
            "- Output ONLY these three fields with these exact labels.\n"
            "- Do NOT output multiple answers.\n"
            "- Evidence MUST be verbatim quotes copied from CONTEXT and MUST include the context item index like [1] or [2].\n"
        )
        return (
            f"{persona_block}{debug_format}\n"
            f"CONTEXT:\n{context_block}\n\n"
            f"QUESTION: {question}\n"
        )

    return (
        f"{persona_block}\n"
        f"CONTEXT:\n{context_block}\n\n"
        f"QUESTION: {question}\n"
        "ANSWER:"
    )


_HDR_ANSWER_RE = re.compile(
    r"(?im)^[ \t]*(?:\d+\)\s*)?(?:\*\*?)?Answer(?:\*\*?)?\s*[:：]\s*"
)
_HDR_EVIDENCE_RE = re.compile(
    r"(?im)^[ \t]*(?:\d+\)\s*)?(?:\*\*?)?Evidence(?:\*\*?)?\s*[:：]\s*"
)
_HDR_DEBUG_ANSWER_RE = re.compile(
    r"(?im)^[ \t]*(?:\d+\)\s*)?(?:\*\*?)?DebugAnswer(?:\*\*?)?\s*[:：]\s*"
)
_HDR_NEXT_STEP_RE = re.compile(
    r"(?im)^[ \t]*(?:\d+\)\s*)?(?:\*\*?)?(?:Next step questions?|Next step question|Next Question|Next Actions)"
    r"(?:\*\*?)?\s*[:：]\s*"
)


def parse_debug_output(debug_text: str) -> Dict[str, str]:
    """
    Parse the debug LLM output into 3 fields:
    - debug_answer
    - evidence
    - next_step_questions

    Best-effort: supports both the new strict labels and some legacy variants.
    """
    dbg = (debug_text or "").strip()
    if not dbg:
        return {"debug_answer": "", "evidence": "", "next_step_questions": ""}

    # Prefer new strict headers; fall back to legacy "Answer:" for debug answer.
    candidates: List[tuple[str, re.Pattern[str]]] = [
        ("debug_answer", _HDR_DEBUG_ANSWER_RE),
        ("evidence", _HDR_EVIDENCE_RE),
        ("next_step_questions", _HDR_NEXT_STEP_RE),
        ("debug_answer_legacy", _HDR_ANSWER_RE),
    ]

    hits: List[tuple[int, int, str]] = []
    for key, rx in candidates:
        m = rx.search(dbg)
        if m:
            hits.append((m.start(), m.end(), key))
    hits.sort()

    def _slice(start_idx: int, end_idx: int) -> str:
        return (dbg[start_idx:end_idx] or "").strip()

    out = {"debug_answer": "", "evidence": "", "next_step_questions": ""}
    if not hits:
        # Unparseable; treat the whole thing as debug_answer to avoid losing information.
        out["debug_answer"] = dbg
        return out

    for i, (start, end, key) in enumerate(hits):
        next_start = hits[i + 1][0] if i + 1 < len(hits) else len(dbg)
        content = _slice(end, next_start)
        if key == "debug_answer":
            out["debug_answer"] = content
        elif key == "debug_answer_legacy" and not out["debug_answer"]:
            out["debug_answer"] = content
        elif key == "evidence":
            out["evidence"] = content
        elif key == "next_step_questions":
            out["next_step_questions"] = content

    return out


def format_debug_fields(*, actual_answer: str, debug_text: str) -> str:
    """
    Produce a stable 4-field debug view for CLI:
    - Answer: production answer
    - DebugAnswer: debug-mode answer
    - Evidence
    - Next step questions
    """
    parsed = parse_debug_output(debug_text)
    answer = (actual_answer or "").strip()
    dbg_ans = (parsed.get("debug_answer") or "").strip()
    evidence = (parsed.get("evidence") or "").strip() or "None"
    next_q = (parsed.get("next_step_questions") or "").strip() or "None"

    return (
        "**Answer**:\n"
        f"{answer}\n\n"
        "**DebugAnswer**:\n"
        f"{dbg_ans}\n\n"
        "**Evidence**:\n"
        f"{evidence}\n\n"
        "**Next step questions**:\n"
        f"{next_q}"
    ).strip()


def merge_debug_answer(debug_text: str, actual_answer: str) -> str:
    """
    Keep debug-mode Evidence/Next-step sections unchanged, but replace the Answer content
    with the "actual" (non-debug) answer text.
    """
    dbg = (debug_text or "").rstrip()
    ans = (actual_answer or "").strip()
    if not dbg:
        return ans

    m_ev = _HDR_EVIDENCE_RE.search(dbg)
    m_ans = _HDR_ANSWER_RE.search(dbg)
    if not m_ev or not m_ans:
        return f"**Answer**:\n{ans}\n\n{dbg}".strip()

    if m_ans.start() > m_ev.start():
        return f"**Answer**:\n{ans}\n\n{dbg}".strip()

    prefix = dbg[: m_ans.end()]
    suffix = dbg[m_ev.start() :]
    # Ensure a clean separation between header and answer, and between answer and Evidence.
    return f"{prefix}\n{ans}\n\n{suffix}".strip()


def rag_answer(
    store: VectorStore,
    settings: Settings,
    question: str,
    embed_model: str,
    chat_model: str,
    top_k: int,
) -> str:
    results = retrieve_top_k(
        store=store,
        collection=settings.default_collection,
        query=question,
        embed_model=embed_model,
        ollama_base_url=settings.ollama_base_url,
        top_k=top_k,
    )
    contexts = [r["text"] for r in results]
    prompt = build_prompt(question, contexts, debug=False, settings=settings)
    return llm_generate(prompt, settings=settings, purpose="answer", model_override=chat_model)
