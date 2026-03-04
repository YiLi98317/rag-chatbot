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


def build_prompt(
    question: str,
    contexts: List[str],
    *,
    debug: bool = False,
    settings: Optional[Settings] = None,
) -> str:
    if settings is None:
        try:
            from chatbot.config import get_settings

            settings = get_settings()
        except Exception:
            settings = None

    persona_name = getattr(settings, "answer_persona", "phone_mom") if settings else "phone_mom"
    persona_text = load_persona_text(str(persona_name))

    context_block = _format_contexts_numbered(contexts)
    lang = detect_lang(question)
    if lang == "en":
        lang_rule = "Answer in English."
    elif lang == "zh":
        lang_rule = "Answer in Chinese."
    else:
        lang_rule = "If the question mixes English and Chinese, prefer Chinese in the answer."

    grounding_rules = (
        "SYSTEM_GROUNDING_RULES:\n"
        "- You MUST answer using ONLY the provided CONTEXT.\n"
        "- If CONTEXT contains a general process/workflow relevant to the question, you MUST provide that process as numbered steps.\n"
        "- If the question is about a specific model/version but CONTEXT only has general process, answer with the general process and explicitly note which model-specific details are missing.\n"
        "- If the question asks for a specific model/version/condition but CONTEXT only has general info, clearly state what specific details are missing.\n"
        "- Only if CONTEXT is truly irrelevant or missing (no relevant general process and no relevant facts), say: \"我在现有资料中没有看到相关信息\" and ask ONE follow-up question.\n"
        "- Do NOT fabricate product features, steps, prices, policies, or any official claims.\n"
        f"- {lang_rule}\n"
    )

    if debug:
        # Debug mode: force a consistent, inspectable format (DebugAnswer/Evidence/Next step questions).
        instructions = (
            "SYSTEM:\n"
            "You are a helpful assistant.\n"
            "- Always be truthful and grounded.\n"
            "- If CONTEXT is insufficient, say what is missing and ask ONE follow-up question.\n\n"
            "Output format:\n"
            "DebugAnswer: (1-5 sentences)\n"
            "Evidence: quote up to 3 short snippets from the Context (or say 'None' if truly missing)\n"
            "Next step questions: ask exactly ONE question to proceed\n"
            "IMPORTANT:\n"
            "- Output ONLY these three fields with these exact labels.\n"
            "- Do NOT output multiple answers.\n"
            "- Evidence MUST be verbatim quotes copied from CONTEXT and MUST include the context item index like [1] or [2].\n"
        )
        persona_block = f"SYSTEM_PERSONA:\n{persona_text}\n" if persona_text else ""
        return (
            f"{persona_block}{grounding_rules}\n"
            f"{instructions}\n"
            f"CONTEXT:\n{context_block}\n\n"
            f"QUESTION: {question}\n"
        )

    # Normal mode: answer naturally; if insufficient context, ask a single follow-up question.
    persona_block = f"SYSTEM_PERSONA:\n{persona_text}\n" if persona_text else ""
    instructions = (
        "SYSTEM:\n"
        "You are a helpful assistant.\n"
        "- Provide clear, actionable steps when possible.\n"
        "- If the context is insufficient, be honest and ask ONE follow-up question to proceed.\n"
    )
    return (
        f"{persona_block}{grounding_rules}\n"
        f"{instructions}\n"
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
