from __future__ import annotations

from typing import List

from chatbot.config import Settings
from chatbot.llm.ollama_chat import generate
from chatbot.retrieval.retriever import retrieve_top_k
from chatbot.vectorstore.base import VectorStore
from chatbot.retrieval.normalize import detect_lang


def build_prompt(question: str, contexts: List[str], *, debug: bool = False) -> str:
    separator = "\n\n----\n\n"
    context_block = separator.join(contexts)
    lang = detect_lang(question)
    if lang == "en":
        lang_rule = "Answer in English."
    elif lang == "zh":
        lang_rule = "Answer in Chinese."
    else:
        lang_rule = "If the question mixes English and Chinese, prefer Chinese in the answer."

    if debug:
        # Debug mode: force a consistent, inspectable format (Answer/Evidence/Next step).
        instructions = (
            "You are a helpful assistant.\n"
            "- Use the provided context as the only source of truth.\n"
            "- ALWAYS reply with something helpful.\n"
            "- NEVER reply with 'I don't know' / '不知道' / '无法回答'.\n"
            "- If the context is insufficient or only partially relevant, say what you can infer and what is missing.\n"
            f"- {lang_rule}\n\n"
            "Output format:\n"
            "1) Answer: (1–5 sentences)\n"
            "2) Evidence: quote up to 3 short snippets from the Context (or say 'None' if truly missing)\n"
            "3) Next step question: ask exactly ONE question to proceed\n"
        )
        return f"{instructions}\nContext:\n{context_block}\n\nQuestion: {question}\n"

    # Normal mode: answer naturally; if insufficient context, ask a single follow-up question.
    instructions = (
        "You are a helpful assistant. Answer using ONLY the context.\n"
        "- NEVER reply with 'I don't know' / '不知道' / '无法回答'.\n"
        "- If the context is insufficient, be honest and ask ONE follow-up question to proceed.\n"
        f"- {lang_rule}\n"
    )
    return f"{instructions}\n\nContext:\n{context_block}\n\nQuestion: {question}\nAnswer:"


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
    prompt = build_prompt(question, contexts, debug=False)
    return generate(prompt=prompt, model=chat_model, base_url=settings.ollama_base_url)
