from __future__ import annotations

import typer
from rich import print as rprint
from sqlalchemy import create_engine
from tqdm import tqdm

from chatbot.config import get_settings
from chatbot.embeddings.provider import embed_text
from chatbot.sql.reader import select_rows
from chatbot.sql.row_to_doc import row_to_text, doc_id
from chatbot.vectorstore import get_vector_store
from chatbot.vectorstore.base import Point
from chatbot.retrieval.normalize import detect_lang

app = typer.Typer(add_completion=False)


@app.command()
def ingest_sql(
    table: str = typer.Option(None, "--table", "-t", help="Source table name"),
    since: str = typer.Option(None, "--since", help="ISO date/time for incremental sync"),
    where: str = typer.Option(None, "--where", help="Additional SQL WHERE clause (use carefully)"),
    limit: int = typer.Option(None, "--limit", help="Max rows to process"),
    collection: str = typer.Option(None, "--collection", "-c", help="Vector collection name"),
    embed_model: str = typer.Option(
        "nomic-embed-text", "--embed-model", help="Ollama embedding model"
    ),
    recreate: bool = typer.Option(False, "--recreate", help="Recreate collection before ingest"),
    pk_col: str = typer.Option(
        None, "--pk-col", help="Primary key column name (overrides SQL_PK from .env)"
    ),
    updated_at_col: str = typer.Option(
        None, "--updated-at-col", help="Updated-at column (overrides SQL_UPDATED_AT from .env)"
    ),
    batch_size: int = typer.Option(128, "--batch-size", help="Batch size for vector upsert"),
):
    """
    Ingest rows from a SQL database into the configured vector store using deterministic IDs and incremental sync.
    """
    settings = get_settings()
    db_uri = settings.db_uri
    if not db_uri:
        raise typer.BadParameter(
            "DB_URI is not set. Configure it in your .env (e.g. mysql+pymysql://user:pass@host:3306/db), "
            "or set MYSQL_HOST, MYSQL_PORT, MYSQL_DB, MYSQL_USER, MYSQL_PASSWORD so DB_URI can be derived."
        )

    table_name = table or settings.sql_table
    if not table_name:
        raise typer.BadParameter("Table name is required (--table) or set SQL_TABLE in .env.")

    collection_name = collection or settings.default_collection
    pk_name = pk_col or settings.sql_pk
    updated_at_name = updated_at_col or settings.sql_updated_at
    rprint(
        f"[bold]SQL ingest[/bold] from [cyan]{db_uri}[/cyan] table [bold]{table_name}[/bold] into [bold]{collection_name}[/bold]"
    )
    rprint(f"[dim]PK: {pk_name}   Updated-at: {updated_at_name or '(none)'}[/dim]")

    engine = create_engine(db_uri)
    rows = list(
        select_rows(
            engine=engine,
            table=table_name,
            pk_col=pk_name,
            updated_at_col=updated_at_name,
            since=since,
            where=where,
            limit=limit,
        )
    )
    if not rows:
        rprint("[yellow]No rows matched the criteria.[/yellow]")
        raise typer.Exit(code=0)

    points = []
    first_vec_dim: Optional[int] = None
    for row in tqdm(rows, desc="Embedding rows"):
        text = row_to_text(table_name, row)
        lang = detect_lang(text)
        emb = embed_text(
            text,
            provider=settings.embed_provider,
            model=embed_model,
            ollama_base_url=settings.ollama_base_url,
        )
        pk_value = row[pk_name]
        updated_at_value = row.get(updated_at_name, "")
        pid = doc_id(table_name, pk_value, updated_at_value)
        meta = {
            "table": table_name,
            "pk": pk_value,
            "updated_at": str(updated_at_value),
            "source": f"db:{table_name}:{pk_value}",
            "lang": lang,
            "source_type": "sql",
        }
        vec = list(emb)
        if first_vec_dim is None:
            first_vec_dim = len(vec)
        points.append(Point(id=pid, vector=vec, text=text, metadata=meta))

    if not points:
        rprint("[yellow]No rows produced vector points.[/yellow]")
        raise typer.Exit(code=0)

    vector_size = first_vec_dim or len(points[0].vector)

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

    store.ensure_collection(collection_name, vector_size)
    rprint("Uploading to vector store...")
    store.upsert(collection_name, points=points, batch_size=int(batch_size))
    rprint("[green]SQL ingestion completed.[/green]")


def main():
    app()


if __name__ == "__main__":
    main()
