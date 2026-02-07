from __future__ import annotations

import typer
from rich import print as rprint
from tqdm import tqdm

from chatbot.config import get_settings
from chatbot.embeddings.provider import embed_texts
from chatbot.ingest.loader import load_and_chunk
from chatbot.vectorstore import get_vector_store
from chatbot.vectorstore.base import Point
from chatbot.vectorstore.ids import stable_chunk_id

app = typer.Typer(add_completion=False)


@app.command()
def ingest(
    collection: str = typer.Option(None, "--collection", "-c", help="Vector collection name"),
    chunk_size: int = typer.Option(800, "--chunk-size", help="Characters per chunk"),
    chunk_overlap: int = typer.Option(
        150, "--chunk-overlap", help="Characters overlap between chunks"
    ),
    model: str = typer.Option("nomic-embed-text", "--model", "-m", help="Ollama embedding model"),
    embed_batch_size: int = typer.Option(
        32, "--embed-batch-size", help="Embedding batch size (default: 32)"
    ),
    recreate: bool = typer.Option(False, "--recreate", help="Recreate collection before ingest"),
    batch_size: int = typer.Option(128, "--batch-size", help="Batch size for vector upsert"),
):
    """
    Ingest files into the configured vector store: load -> chunk -> embed -> upsert.
    """
    settings = get_settings()
    collection_name = collection or settings.default_collection
    data_dir = settings.data_dir
    rprint(f"[bold]Ingesting from[/bold] {data_dir} into collection [bold]{collection_name}[/bold]")

    # Load and chunk documents
    docs = load_and_chunk(data_dir, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    if not docs:
        rprint("[yellow]No documents found to ingest.[/yellow]")
        raise typer.Exit(code=0)

    store = get_vector_store(settings)

    if recreate:
        if settings.vector_provider == "qdrant":
            try:
                store.client.delete_collection(collection_name=collection_name)  # type: ignore[attr-defined]
            except Exception:
                pass
        else:
            try:
                from pymilvus import utility  # type: ignore

                if utility.has_collection(collection_name):
                    utility.drop_collection(collection_name)
            except Exception:
                pass

    # Stream docs -> embed -> upsert so long ingests show progress and avoid huge memory spikes.
    total = len(docs)
    rprint(f"Embedding {total} chunks with model: {model} (provider={settings.embed_provider})")

    created = False
    buffer_texts = []
    buffer_metas = []

    def flush() -> int:
        nonlocal created
        if not buffer_texts:
            return 0
        vecs = embed_texts(
            buffer_texts,
            provider=settings.embed_provider,
            model=model,
            ollama_base_url=settings.ollama_base_url,
            batch_size=int(embed_batch_size),
        )
        if not created:
            store.ensure_collection(collection_name, len(vecs[0]))
            created = True

        pts = []
        for text, vec, meta in zip(buffer_texts, vecs, buffer_metas):
            src = str((meta or {}).get("source") or "")
            chunk_id = int((meta or {}).get("chunk") or 0)
            pid = stable_chunk_id(source=src, chunk_id=chunk_id, table=(meta or {}).get("table"))
            pts.append(Point(id=pid, vector=list(vec), text=text, metadata=dict(meta or {})))

        store.upsert(collection_name, points=pts, batch_size=int(batch_size))
        n = len(buffer_texts)
        buffer_texts.clear()
        buffer_metas.clear()
        return n

    # `embed_texts` will internally batch, but we buffer so we can show visible progress + chunked upserts.
    target_buffer = max(int(embed_batch_size) * 4, 64)
    done = 0
    for d in tqdm(docs, desc="ingest", unit="chunk"):
        buffer_texts.append(d["text"])
        buffer_metas.append(d["metadata"])
        if len(buffer_texts) >= target_buffer:
            done += flush()
            if done and done % (target_buffer * 5) == 0:
                rprint(f"[dim]progress: {done}/{total} chunks embedded+upserted[/dim]")

    done += flush()
    rprint("[green]Ingestion completed.[/green]")


def main():
    app()


if __name__ == "__main__":
    main()
