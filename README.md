## RAG Chatbot — Milvus + DeepSeek / Ollama

English | [中文](README.zh.md)

Deeper architecture + workflow diagrams live in `intro.md`.

---

### Tech stack

- **Language/runtime**: Python 3.10+ (venv)
- **CLI**: Typer + Rich
- **API**: FastAPI + Uvicorn
- **Vector DB**: Milvus (self-host via `pymilvus`) *(Qdrant supported as optional fallback)*
- **Models**:
  - **Embeddings**: SentenceTransformers (`BAAI/bge-m3`, default) *or* Ollama HTTP API (`POST /api/embeddings`)
  - **Generation**: DeepSeek API (OpenAI-compatible, default) *or* Ollama HTTP API (`POST /api/generate`)
- **SQL**: SQLAlchemy (SQLite by default; MySQL supported via PyMySQL)
- **Lexical matching**: SQLite FTS5 + RapidFuzz
- **Utilities**: requests, tqdm, python-dotenv

---

### How to run

#### Requirements

- Python 3.10+ and `make`
- DeepSeek API key (default LLM provider)

> **Optional** (only if you want to use local Ollama instead of DeepSeek API):
> Ollama running locally (`OLLAMA_BASE_URL=http://localhost:11434`)

#### Setup

1. Copy the example env and fill in your values:

```bash
cp .env.example .env
```

Key variables (see `.env.example` for the full list):

- `VECTOR_PROVIDER=milvus`
- `MILVUS_LITE_DB=./milvus.db` *(Milvus Lite embedded — no Docker needed for local dev)*
  - or `MILVUS_URI=http://localhost:19530` *(Milvus server — used in deployment)*
- `MILVUS_DB=default`
- `MILVUS_COLLECTION=chatbot_docs`
- `LLM_PROVIDER=deepseek` (or `ollama` for local inference)
- `API_KEY=sk-...` *(DeepSeek API key; required when `LLM_PROVIDER=deepseek`)*
- `API_BASE_URL=https://api.deepseek.com`
- `MODEL_NAME=deepseek-chat`
- `EMBED_PROVIDER=sentence_transformers` (or `ollama`)
- `EMBED_MODEL=BAAI/bge-m3`
- `TOP_K_DEFAULT=5`
- `ANSWER_PERSONA=phone_mom` (or `none`)
- (optional for SQL ingest / resolver) `DB_URI=sqlite:///data/knowledge.db`

If using Ollama for generation instead of DeepSeek:

- `LLM_PROVIDER=ollama`
- `OLLAMA_BASE_URL=http://localhost:11434`
- `CHAT_MODEL=llama3.1`

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

ECS deployment (required for remote ingestion and `deploy` workflow):

- `ECS_HOST=<your-ecs-ip>` *(ECS server IP or hostname)*
- `ECS_USER=root` *(SSH user)*
- `ECS_PASSWORD=<your-password>` *(SSH password)*

2. Install:

```bash
make install
```

3. **(Optional)** Pull Ollama models — only needed when `LLM_PROVIDER=ollama` or `EMBED_PROVIDER=ollama`:

```bash
ollama pull nomic-embed-text   # only if EMBED_PROVIDER=ollama
ollama pull llama3.1           # only if LLM_PROVIDER=ollama
ollama pull deepseek-r1        # only if using local DeepSeek via Ollama
```

> With the default configuration (`LLM_PROVIDER=deepseek` + `EMBED_PROVIDER=sentence_transformers` + `MILVUS_LITE_DB`), no external services are needed for local development. Embeddings run in-process via SentenceTransformers, generation calls the remote DeepSeek API, and Milvus Lite stores vectors in a local file. Docker Compose and Ollama are only needed for deployment or if you explicitly switch providers.

#### Local testing

Interactive chat:

```bash
make chat collection=chatbot_docs
```

Debug mode (shows planner, resolver, and retrieval layer details):

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

Run the HTTP API locally:

```bash
make api
```

---

### Ingestion

#### Local ingestion

Place your files under `data/target/` (or set `DATA_DIR` to a custom path). Supported formats: `.txt`, `.md`, `.xlsx` / `.xls`. The ingest pipeline automatically detects file type and language (Chinese content uses language-aware chunking).

```bash
# Ingest everything in data/target/ (recreate collection from scratch)
DATA_DIR=data/target make ingest collection=chatbot_docs args="--recreate"

# Incremental ingest (append/upsert without dropping existing data)
DATA_DIR=data/target make ingest collection=chatbot_docs
```

Options: `--chunk-size`, `--chunk-overlap`, `--embed-batch-size`, `--recreate`, `--batch-size`.

#### Deployment: remote ingestion

Remote ingestion on ECS is handled by a GitHub Actions workflow (`.github/workflows/reingest-ecs.yml`).

**Step 1** — Upload local data to the ECS server:

```bash
# Uploads data/target/* to the ECS server at /data/company_docs/
bash scripts/upload_data_to_ecs.sh
```

**Step 2** — Trigger the **Re-ingest ECS Data** workflow from the GitHub Actions UI. The workflow:

1. SSHes into the ECS server
2. Pulls the latest Docker image from GHCR
3. Runs `chatbot.cli.ingest` inside a container on the same Docker network as the running Milvus instance
4. Supports **incremental** (append/upsert) and **full** (recreate collection) modes via `workflow_dispatch` inputs

Specify the data path (default `/data/company_docs`) and mode (`incremental` or `full`) when dispatching.

---

### API server

Endpoints:

- `GET /healthz`
- `GET /readyz`
- `POST /v1/qa` with JSON body `{ "question": "..." }`
- `POST /v1/qa/stream` — Server-Sent Events streaming response (`event: start | chunk | done | error`)

### Docker Compose (deployment)

The Docker Compose stack is used for deployment (ECS) and handles all service orchestration automatically:

```bash
docker compose up --build
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

Services: etcd, MinIO, Milvus, Ollama (GPU, optional), API.

### GPU-accelerated inference (Docker)

The `docker-compose.yml` Ollama service is configured for NVIDIA GPU passthrough. This is relevant when `LLM_PROVIDER=ollama` (e.g. running `deepseek-r1` locally). When using DeepSeek API (`LLM_PROVIDER=deepseek`), the Ollama GPU container is not required for generation.

Embeddings run via SentenceTransformers (`BAAI/bge-m3`) by default and will benefit from GPU if PyTorch+CUDA is available in the API container.

**Host prerequisites:**

```bash
# 1. Verify GPU is visible
nvidia-smi

# 2. Install NVIDIA container toolkit (if not already)
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# 3. Verify Docker GPU access
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

**After `docker compose up -d`:**

```bash
# Verify Ollama GPU usage (for chat model)
watch -n 0.5 nvidia-smi
```

**Embedding benchmark:**

```bash
python scripts/bench_embed.py
# Target: avg < 0.8s (down from ~5.5s on CPU)
# Override provider/model: --provider sentence_transformers --model BAAI/bge-m3
```

### K8s (local cluster)

See `deploy/README.md`.

### CI/CD

GitHub Actions workflows in `.github/workflows/`:

- **test-build** — lint + build Docker image on PR
- **deploy** — build, push to GHCR, deploy to ECS (triggers on push to `main`)
- **reingest-ecs** — trigger remote data re-ingestion (manual `workflow_dispatch`)
- **ci-kind-smoke** — spin up a kind cluster and run smoke tests

#### GitHub repository secrets

The CI/CD workflows require the following secrets (Settings → Secrets and variables → Actions):

| Secret | `.env.example` variable | Description |
|---|---|---|
| `API_BASE_URL` | `API_BASE_URL` | DeepSeek API endpoint |
| `API_KEY` | `API_KEY` | DeepSeek API key |
| `CHAT_MODEL` | `CHAT_MODEL` | LLM chat model name (Ollama) |
| `ECS_HOST` | `ECS_HOST` | ECS server IP or hostname |
| `ECS_PASSWORD` | `ECS_PASSWORD` | ECS SSH password |
| `ECS_USER` | `ECS_USER` | ECS SSH user |
| `EMBED_MODEL` | `EMBED_MODEL` | Embedding model name |
| `EMBED_PROVIDER` | `EMBED_PROVIDER` | Embedding provider (`sentence_transformers` / `ollama`) |
| `GHCR_TOKEN` | *(none)* | GitHub Container Registry PAT (`write:packages` scope) |
| `LLM_PROVIDER` | `LLM_PROVIDER` | LLM provider (`deepseek` / `ollama`) |
| `MILVUS_COLLECTION` | `MILVUS_COLLECTION` | Milvus collection name |
| `MILVUS_DB` | `MILVUS_DB` | Milvus database name |
| `MILVUS_URI` | `MILVUS_URI` | Milvus server URI (deployment) |
| `MODEL_NAME` | `MODEL_NAME` | DeepSeek model name |
| `OLLAMA_BASE_URL` | `OLLAMA_BASE_URL` | Ollama server URL |
| `VECTOR_PROVIDER` | `VECTOR_PROVIDER` | Vector DB provider (`milvus` / `qdrant`) |
