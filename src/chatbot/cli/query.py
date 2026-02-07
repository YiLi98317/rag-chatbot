from __future__ import annotations

import typer
from rich import print as rprint

from dataclasses import replace
from chatbot.config import get_settings
from chatbot.rag.pipeline import rag_answer, build_prompt
from chatbot.vectorstore import get_vector_store
from chatbot.retrieval.retriever import retrieve_top_k
from chatbot.llm.ollama_chat import generate

app = typer.Typer(add_completion=False)


@app.command()
def query(
    question: str = typer.Argument(..., help="Your question"),
    collection: str = typer.Option(None, "--collection", "-c", help="Qdrant collection name"),
    embed_model: str = typer.Option(
        None, "--embed-model", help="Embedding model (defaults to EMBED_MODEL/.env)"
    ),
    chat_model: str = typer.Option(None, "--chat-model", help="Chat model (defaults to CHAT_MODEL/.env)"),
    top_k: int = typer.Option(4, "--top-k", help="Number of passages to retrieve"),
    debug: bool = typer.Option(
        False, "--debug", help="Print retrieved contexts, scores, and prompt details"
    ),
):
    """
    Query with a simple RAG pipeline: retrieve -> prompt -> generate.
    """
    settings = get_settings()
    # Default models to settings (respects .env)
    embed_model = embed_model or settings.embed_model
    chat_model = chat_model or settings.chat_model
    if collection:
        # Override default collection at runtime
        settings = replace(settings, default_collection=collection)
    store = get_vector_store(settings)
    rprint(f"[bold]Question:[/bold] {question}")
    if debug:
        results = retrieve_top_k(
            store=store,
            collection=settings.default_collection,
            query=question,
            embed_model=embed_model,
            ollama_base_url=settings.ollama_base_url,
            top_k=top_k,
            db_uri=settings.db_uri,
            debug=debug,
        )
        rprint(
            f"[dim]Retrieved {len(results)} contexts from [cyan]{settings.default_collection}[/cyan][/dim]"
        )
        contexts = []
        for idx, r in enumerate(results, start=1):
            contexts.append(r.get("text", ""))
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
        prompt_text = build_prompt(question, contexts, debug=True)
        rprint(f"[dim]Prompt length: chars={len(prompt_text)}[/dim]")
        answer = generate(prompt=prompt_text, model=chat_model, base_url=settings.ollama_base_url)
    else:
        answer = rag_answer(
            store=store,
            settings=settings,
            question=question,
            embed_model=embed_model,
            chat_model=chat_model,
            top_k=top_k,
        )
    rprint("\n[bold green]Answer[/bold green]:")
    rprint(answer)


def main():
    app()


if __name__ == "__main__":
    main()
