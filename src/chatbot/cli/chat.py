#!/usr/bin/env python3
from __future__ import annotations

from typing import Optional

import typer
from rich import print as rprint

from chatbot.config import get_settings
from chatbot.retrieval.retriever import retrieve_top_k
from chatbot.vectorstore import get_vector_store
from chatbot.llm.ollama_chat import generate
from chatbot.rag.pipeline import build_prompt

app = typer.Typer(add_completion=False)

_NON_ANSWERS = {
    "",
    "不知道",
    "我不知道",
    "不清楚",
    "无法回答",
    "无法确定",
    "i don't know",
    "i dont know",
    "don't know",
    "dont know",
}


def _fallback_reply(prompt: str, results, coll: str) -> str:
    # Minimal always-on fallback: show what we retrieved and ask next step.
    lines = []
    lines.append("我先把检索到的内容给你（可能相关性不高）：")
    if not results:
        lines.append(f"- 当前从 {coll} 没有检索到任何上下文。")
        lines.append("你希望我怎么继续？要不要你换个说法/给一个关键词，或者我把更多数据再 ingest 进去？")
        return "\n".join(lines)
    for i, r in enumerate(results[:3], 1):
        meta = r.get("metadata", {}) or {}
        table = meta.get("table", "")
        head = (r.get("text", "") or "").replace("\n", " ").strip()
        if len(head) > 220:
            head = head[:220] + "…"
        lines.append(f"- [{i}] {table}: {head}")
    lines.append("你希望我从上面哪一条继续？还是你想限定分类/表（例如 THUCNews / Company）再查一次？")
    return "\n".join(lines)


@app.command()
def run(
    collection: Optional[str] = typer.Option(
        None, "--collection", "-c", help="Qdrant collection (defaults to QDRANT_COLLECTION)"
    ),
    embed_model: Optional[str] = typer.Option(
        None, "--embed-model", help="Ollama embedding model (default from .env)"
    ),
    chat_model: Optional[str] = typer.Option(
        None, "--chat-model", help="Ollama chat model (default from .env)"
    ),
    top_k: Optional[int] = typer.Option(None, "--top-k", help="Top-k contexts (default from .env)"),
    debug: bool = typer.Option(
        False, "--debug", help="Print retrieved contexts, scores, and prompt details"
    ),
):
    """
    Start an interactive chat loop. Type your question and press Enter. Type 'quit' or 'exit' to leave.
    """
    settings = get_settings()
    coll = collection or settings.default_collection
    emb = embed_model or getattr(settings, "embed_model", "nomic-embed-text")
    chat = chat_model or getattr(settings, "chat_model", "llama3.1")
    k = top_k if top_k is not None else getattr(settings, "default_top_k", 4)
    store = get_vector_store(settings)

    rprint(
        f"[bold]Chatbot ready[/bold]  ([cyan]{coll}[/cyan], embed=[magenta]{emb}[/magenta], chat=[green]{chat}[/green], k={k})"
    )
    rprint("Type your question and press [bold]Enter[/bold]. Type [bold]quit[/bold] to exit.")

    while True:
        try:
            prompt = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            rprint("\n[dim]Bye![/dim]")
            break
        if not prompt or prompt.lower() in {"q", "quit", "exit"}:
            rprint("[dim]Bye![/dim]")
            break

        try:
            # retrieve contexts
            results = retrieve_top_k(
                store=store,
                collection=coll,
                query=prompt,
                embed_model=emb,
                ollama_base_url=settings.ollama_base_url,
                top_k=k,
                db_uri=settings.db_uri,
                debug=debug,
            )
            # If entity resolver returned medium-confidence suggestions, show and skip LLM
            if results and (results[0].get("metadata", {}) or {}).get("resolver_decision") == "medium":
                meta = results[0]["metadata"]
                suggestions = meta.get("suggestions", []) or []
                rprint("[yellow]I found close matches. Did you mean:[/yellow]")
                for i, s in enumerate(suggestions, 1):
                    rprint(f"[dim]{i}.[/dim] {s.get('entity_type')} {s.get('name')} (id={s.get('entity_id')}) "
                           f"[dim]fuzzy={s.get('fuzzy'):.1f}[/dim]")
                rprint("[dim]Please rephrase or specify the exact one you want (e.g., 'Track 1045').[/dim]")
                continue
            # If low lexical but Qdrant had results, show closest matches and skip LLM
            if results and (results[0].get("metadata", {}) or {}).get("resolver_decision") == "low_with_qdrant":
                meta = results[0]["metadata"]
                matches = meta.get("matches", []) or []
                rprint("[yellow]Closest matches in this database:[/yellow]")
                for i, m in enumerate(matches, 1):
                    rprint(f"[dim]{i}.[/dim] {m.get('table')} {m.get('title')}")
                    head = (m.get("text_head") or "").strip()
                    if head:
                        rprint(f"[dim]    {head}[/dim]")
                rprint("[dim]Please rephrase or specify the exact one you want (e.g., 'Track 1045').[/dim]")
                continue
            contexts = [r.get("text", "") for r in results]
            prompt_text = build_prompt(prompt, contexts, debug=debug)
            if debug:
                rprint(f"[dim]Retrieved {len(results)} contexts from [cyan]{coll}[/cyan][/dim]")
                for idx, r in enumerate(results, start=1):
                    score = r.get("score")
                    src = r.get("metadata", {}) or {}
                    table = src.get("table", "")
                    title = src.get("title") or src.get("Name") or src.get("TrackId") or ""
                    text_preview = (r.get("text", "") or "").replace("\n", " ")
                    if len(text_preview) > 220:
                        text_preview = text_preview[:220] + "…"
                    rprint(f"[dim]{idx}.[/dim] score={score:.4f} {table} {title}".rstrip())
                    if text_preview:
                        rprint(f"[dim]    {text_preview}[/dim]")
                rprint(f"[dim]Prompt length: chars={len(prompt_text)}[/dim]")
            answer = generate(prompt=prompt_text, model=chat, base_url=settings.ollama_base_url)
            answer_clean = (answer or "").strip()
            if answer_clean.lower() in _NON_ANSWERS or len(answer_clean) < 2:
                answer_clean = _fallback_reply(prompt, results, coll)
            rprint(f"[bold green]assistant>[/bold green] {answer_clean}")
            if results:
                rprint("[dim]Top sources:[/dim]")
                for idx, r in enumerate(results, start=1):
                    src = r.get("metadata", {})
                    title = src.get("title") or src.get("Name") or src.get("TrackId") or ""
                    rprint(f"[dim]{idx}.[/dim] {src.get('table', '')} {title}")
        except Exception as e:
            rprint(f"[red]Error:[/red] {e}")


def main():
    app()


if __name__ == "__main__":
    main()
