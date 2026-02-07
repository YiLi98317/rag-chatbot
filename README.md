## Chatbot (CLI-first) — Milvus + Ollama (v0)

Deeper architecture + workflow diagrams live in `intro.md`.

---

### Tech stack

- **Language/runtime**: Python (venv)
- **CLI**: Typer + Rich
- **Vector DB**: Milvus (self-host via `pymilvus`) *(Qdrant supported as optional fallback)*
- **Models**:
  - **Embeddings**: Ollama HTTP API (`POST /api/embeddings`) *or* local SentenceTransformers (`EMBED_PROVIDER=sentence_transformers`)
  - **Generation**: Ollama HTTP API (`POST /api/generate`)
- **SQL**: SQLAlchemy (SQLite by default; MySQL supported via PyMySQL)
- **Lexical matching**: SQLite FTS5 + RapidFuzz
- **Utilities**: requests, tqdm, python-dotenv

---

### How to run

#### Requirements

- Python 3.10+ and `make`
- Ollama running locally (default `OLLAMA_BASE_URL=http://localhost:11434`)
- Milvus (local `docker compose` or local K8s)

#### Setup

1. Create `.env` in the project root:

- `VECTOR_PROVIDER=milvus`
- `MILVUS_URI=http://localhost:19530` *(Milvus server)*\n+  - or for local non-docker: `MILVUS_LITE_DB=./milvus.db` *(Milvus Lite embedded)*
- `MILVUS_DB=default`
- `MILVUS_COLLECTION=chatbot_docs`
- `OLLAMA_BASE_URL=http://localhost:11434`
- `EMBED_PROVIDER=ollama` (or `sentence_transformers`)
- `EMBED_MODEL=nomic-embed-text`
- `CHAT_MODEL=llama3.1`
- `TOP_K_DEFAULT=10`
- (optional for SQL ingest / resolver) `DB_URI=sqlite:///data/knowledge.db`

If you need to temporarily run on Qdrant instead:

- `VECTOR_PROVIDER=qdrant`
- `QDRANT_URL=http://localhost:6333`
- `QDRANT_API_KEY=`
- `QDRANT_COLLECTION=chatbot_docs`

Chinese support (recommended settings):

- `EMBED_PROVIDER=sentence_transformers`
- `EMBED_MODEL=BAAI/bge-m3`
- `CHAT_MODEL=deepseek-r1:latest` (via Ollama, optional but recommended for Chinese)
- `ZH_CHUNK_SIZE=1200`
- `ZH_CHUNK_OVERLAP=150`

2. Install:

```bash
make install
```

3. Pull models:

```bash
ollama pull nomic-embed-text
ollama pull llama3.1
```

If using DeepSeek for Chinese generation:

```bash
ollama pull deepseek-r1
```

4. Start services:

```bash
# Milvus (local, with etcd+minio)
docker compose up -d milvus etcd minio

# Ollama
ollama serve
```

#### Quickstart (Chinook sample)

```bash
. ./.venv/bin/activate
python reingest_chinook.py
make chat collection=chatbot_docs
```

Debug mode:

```bash
make chat collection=chatbot_docs DEBUG=1
```

One-off query:

```bash
make query q="Do you know the song Fly Me To The Moon?" collection=chatbot_docs
```

One-off query (debug):

```bash
make query q="Do you know the song Fly Me To The Moon?" collection=chatbot_docs args="--debug"
```

#### Ingest your own files

Put `.md` / `.txt` files under `data/` (or set `DATA_DIR`), then:

```bash
make ingest collection=chatbot_docs
```

#### Ingest from SQL

Set `DB_URI` (and optionally `SQL_TABLE`, `SQL_PK`, `SQL_UPDATED_AT`), then:

```bash
make ingest-sql args="--table knowledge --since 2025-01-01 --limit 10000 --collection chatbot_docs"
```

#### Useful checks

```bash
make smoke
```

### API server

Run the HTTP API locally:

```bash
make api
```

Endpoints:

- `GET /healthz`
- `GET /readyz`
- `POST /v1/qa` with JSON body `{ "question": "..." }`

### Docker Compose demo

```bash
docker compose up --build
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

### K8s (local cluster)

See `deploy/README.md`.
