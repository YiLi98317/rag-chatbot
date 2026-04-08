## RAG Chatbot — Milvus + DeepSeek / Ollama

[English](README.md) | 中文

更详细的架构说明和工作流图请参阅 `intro.zh.md`。

---

### 技术栈

- **语言/运行时**：Python 3.10+（venv）
- **CLI**：Typer + Rich
- **API**：FastAPI + Uvicorn
- **向量数据库**：Milvus（通过 `pymilvus` 自托管）_（Qdrant 作为可选备用方案）_
- **模型**：
  - **Embeddings**：SentenceTransformers（`BAAI/bge-m3`，默认）_或_ Ollama HTTP API（`POST /api/embeddings`）
  - **生成**：DeepSeek API（兼容 OpenAI 接口，默认）_或_ Ollama HTTP API（`POST /api/generate`）
- **SQL**：SQLAlchemy（默认 SQLite；通过 PyMySQL 支持 MySQL）
- **词汇匹配**：SQLite FTS5 + RapidFuzz
- **工具库**：requests、tqdm、python-dotenv

---

### 如何运行

#### 环境要求

- Python 3.10+ 和 `make`
- DeepSeek API 密钥（默认 LLM 提供商）

> **可选**（仅在使用本地 Ollama 替代 DeepSeek API 时需要）：
> Ollama 在本地运行（`OLLAMA_BASE_URL=http://localhost:11434`）

#### 安装配置

1. 复制示例环境变量文件并填写你的配置：

```bash
cp .env.example .env
```

关键变量（完整列表请参阅 `.env.example`）：

- `VECTOR_PROVIDER=milvus`
- `MILVUS_LITE_DB=./milvus.db` _（Milvus Lite 嵌入模式 — 本地开发无需 Docker）_
  - 或 `MILVUS_URI=http://localhost:19530` _（Milvus 服务端 — 用于部署环境）_
- `MILVUS_DB=default`
- `MILVUS_COLLECTION=chatbot_docs`
- `LLM_PROVIDER=deepseek`（或 `ollama` 用于本地推理）
- `API_KEY=sk-...` _（DeepSeek API 密钥；当 `LLM_PROVIDER=deepseek` 时必填）_
- `API_BASE_URL=https://api.deepseek.com`
- `MODEL_NAME=deepseek-chat`
- `EMBED_PROVIDER=sentence_transformers`（或 `ollama`）
- `EMBED_MODEL=BAAI/bge-m3`
- `TOP_K_DEFAULT=5`
- `ANSWER_PERSONA=phone_mom`（或 `none`）
- （可选，用于 SQL 数据导入 / 实体解析）`DB_URI=sqlite:///data/knowledge.db`

如果使用 Ollama 替代 DeepSeek 进行生成：

- `LLM_PROVIDER=ollama`
- `OLLAMA_BASE_URL=http://localhost:11434`
- `CHAT_MODEL=llama3.1`

如果需要临时切换到 Qdrant：

- `VECTOR_PROVIDER=qdrant`
- `QDRANT_URL=http://localhost:6333`
- `QDRANT_API_KEY=`
- `QDRANT_COLLECTION=chatbot_docs`

中文支持（推荐配置）：

- `EMBED_PROVIDER=sentence_transformers`
- `EMBED_MODEL=BAAI/bge-m3`
- `CHAT_MODEL=deepseek-r1:latest`（通过 Ollama，可选但推荐用于中文场景）
- `ZH_CHUNK_SIZE=1200`
- `ZH_CHUNK_OVERLAP=150`

ECS 部署（远程导入和 `deploy` 工作流所需）：

- `ECS_HOST=<你的 ECS IP>` _（ECS 服务器 IP 或主机名）_
- `ECS_USER=root` _（SSH 用户）_
- `ECS_PASSWORD=<你的密码>` _（SSH 密码）_

2. 安装依赖：

```bash
make install
```

3. **（可选）** 拉取 Ollama 模型 — 仅在 `LLM_PROVIDER=ollama` 或 `EMBED_PROVIDER=ollama` 时需要：

```bash
ollama pull nomic-embed-text   # 仅当 EMBED_PROVIDER=ollama 时
ollama pull llama3.1           # 仅当 LLM_PROVIDER=ollama 时
ollama pull deepseek-r1        # 仅当通过 Ollama 使用本地 DeepSeek 时
```

> 使用默认配置（`LLM_PROVIDER=deepseek` + `EMBED_PROVIDER=sentence_transformers` + `MILVUS_LITE_DB`）时，本地开发无需任何外部服务。Embeddings 通过 SentenceTransformers 在进程内运行，生成调用远程 DeepSeek API，Milvus Lite 将向量存储在本地文件中。Docker Compose 和 Ollama 仅在部署或显式切换提供商时才需要。

#### 本地测试

交互式聊天：

```bash
make chat collection=chatbot_docs
```

调试模式（显示 planner、resolver 和检索层的详细信息）：

```bash
make chat collection=chatbot_docs DEBUG=1
```

单次查询：

```bash
make query q="Do you know the song Fly Me To The Moon?" collection=chatbot_docs
```

单次查询（调试）：

```bash
make query q="Do you know the song Fly Me To The Moon?" collection=chatbot_docs args="--debug"
```

本地运行 HTTP API：

```bash
make api
```

---

### 数据导入

#### 本地导入

将文件放在 `data/target/` 目录下（或设置 `DATA_DIR` 为自定义路径）。支持的格式：`.txt`、`.md`、`.xlsx` / `.xls`。导入管道会自动检测文件类型和语言（中文内容使用语言感知的分块策略）。

```bash
# 导入 data/target/ 下的所有文件（从头重建集合）
DATA_DIR=data/target make ingest collection=chatbot_docs args="--recreate"

# 增量导入（追加/更新，不删除已有数据）
DATA_DIR=data/target make ingest collection=chatbot_docs
```

选项：`--chunk-size`、`--chunk-overlap`、`--embed-batch-size`、`--recreate`、`--batch-size`。

#### 七鱼客服数据导入

使用 `reingest_qiyu.py` 导入网易七鱼导出的客服聊天记录（预处理后的 16 列 xlsx 格式）。

脚本会自动清洗会话内容中的 JSON 系统消息、评价弹窗、转接提示、纯 URL 等噪音，并输出两种文档：
- **知识库文档（knowledge）**：提取客服回复中的业务知识
- **对话文档（conversation）**：保留完整的用户-客服对话上下文

```bash
# 单文件导入（全量重建，限制 1000 条测试）
python reingest_qiyu.py \
  --xlsx data/shangwu11to03.xlsx \
  --collection chatbot_docs \
  --mode both \
  --recreate \
  --max-sessions 1000 \
  --min-rounds 2

# 批量导入目录下所有 xlsx
python reingest_qiyu.py \
  --data-dir data/ \
  --collection chatbot_docs \
  --mode both \
  --recreate

# 增量导入新数据
python reingest_qiyu.py \
  --xlsx data/new_export.xlsx \
  --collection chatbot_docs \
  --mode both
```

选项：`--mode`（knowledge/conversation/both）、`--min-rounds`（过滤低质量会话）、`--max-sessions`（限制数量）、`--recreate`、`--chunk-size`、`--chunk-overlap`。

#### 部署：远程导入

ECS 上的远程导入通过 GitHub Actions 工作流（`.github/workflows/reingest-ecs.yml`）处理。

**步骤 1** — 上传本地数据到 ECS 服务器：

```bash
# 将 data/target/* 上传到 ECS 服务器的 /data/company_docs/ 目录
bash scripts/upload_data_to_ecs.sh
```

**步骤 2** — 从 GitHub Actions 界面触发 **Re-ingest ECS Data** 工作流。该工作流会：

1. 通过 SSH 连接到 ECS 服务器
2. 从 GHCR 拉取最新的 Docker 镜像
3. 在与运行中的 Milvus 实例相同的 Docker 网络中运行 `chatbot.cli.ingest` 容器
4. 通过 `workflow_dispatch` 输入支持**增量**（追加/更新）和**全量**（重建集合）模式

触发时指定数据路径（默认 `/data/company_docs`）和模式（`incremental` 或 `full`）。

---

### API 服务器

接口：

- `GET /healthz`
- `GET /readyz`
- `POST /v1/qa`，JSON 请求体 `{ "question": "..." }`
- `POST /v1/qa/stream` — Server-Sent Events 流式响应（`event: start | chunk | done | error`）

### Docker Compose（部署）

Docker Compose 技术栈用于部署（ECS），自动处理所有服务编排：

```bash
docker compose up --build
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

服务：etcd、MinIO、Milvus、Ollama（GPU，可选）、API。

### GPU 加速推理（Docker）

`docker-compose.yml` 中的 Ollama 服务已配置 NVIDIA GPU 直通。这在 `LLM_PROVIDER=ollama`（例如本地运行 `deepseek-r1`）时适用。使用 DeepSeek API（`LLM_PROVIDER=deepseek`）时，生成不需要 Ollama GPU 容器。

Embeddings 默认通过 SentenceTransformers（`BAAI/bge-m3`）运行，如果 API 容器中有 PyTorch+CUDA，则会自动利用 GPU 加速。

**主机前置条件：**

```bash
# 1. 验证 GPU 可见
nvidia-smi

# 2. 安装 NVIDIA 容器工具包（如未安装）
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# 3. 验证 Docker GPU 访问
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

**`docker compose up -d` 之后：**

```bash
# 验证 Ollama GPU 使用情况（用于聊天模型）
watch -n 0.5 nvidia-smi
```

**Embedding 基准测试：**

```bash
python scripts/bench_embed.py
# 目标：平均 < 0.8s（CPU 上约 5.5s）
# 覆盖 provider/model：--provider sentence_transformers --model BAAI/bge-m3
```

### K8s（本地集群）

参见 `deploy/README.md`。

### CI/CD

GitHub Actions 工作流位于 `.github/workflows/`：

- **test-build** — PR 时执行 lint + 构建 Docker 镜像
- **deploy** — 构建、推送到 GHCR、部署到 ECS（推送到 `main` 时触发）
- **reingest-ecs** — 触发远程数据重新导入（手动 `workflow_dispatch`）
- **ci-kind-smoke** — 启动 kind 集群并运行冒烟测试

#### GitHub 仓库密钥

CI/CD 工作流需要以下密钥（Settings → Secrets and variables → Actions）：

| 密钥                | `.env.example` 变量 | 说明                                                               |
| ------------------- | ------------------- | ------------------------------------------------------------------ |
| `API_BASE_URL`      | `API_BASE_URL`      | DeepSeek API 端点                                                  |
| `API_KEY`           | `API_KEY`           | DeepSeek API 密钥                                                  |
| `CHAT_MODEL`        | `CHAT_MODEL`        | LLM 聊天模型名称（Ollama）                                         |
| `ECS_HOST`          | `ECS_HOST`          | ECS 服务器 IP 或主机名                                             |
| `ECS_PASSWORD`      | `ECS_PASSWORD`      | ECS SSH 密码                                                       |
| `ECS_USER`          | `ECS_USER`          | ECS SSH 用户                                                       |
| `EMBED_MODEL`       | `EMBED_MODEL`       | Embedding 模型名称                                                 |
| `EMBED_PROVIDER`    | `EMBED_PROVIDER`    | Embedding 提供商（`sentence_transformers` / `ollama`）             |
| `GHCR_TOKEN`        | _（无）_            | GitHub Container Registry 个人访问令牌（需 `write:packages` 权限） |
| `LLM_PROVIDER`      | `LLM_PROVIDER`      | LLM 提供商（`deepseek` / `ollama`）                                |
| `MILVUS_COLLECTION` | `MILVUS_COLLECTION` | Milvus 集合名称                                                    |
| `MILVUS_DB`         | `MILVUS_DB`         | Milvus 数据库名称                                                  |
| `MILVUS_URI`        | `MILVUS_URI`        | Milvus 服务端 URI（部署环境）                                      |
| `MODEL_NAME`        | `MODEL_NAME`        | DeepSeek 模型名称                                                  |
| `OLLAMA_BASE_URL`   | `OLLAMA_BASE_URL`   | Ollama 服务器 URL                                                  |
| `VECTOR_PROVIDER`   | `VECTOR_PROVIDER`   | 向量数据库提供商（`milvus` / `qdrant`）                            |

基本就是两个部分，一个是本地的ingest一个是deployment的ingest。现在的话两边用的都是milvus，local是milvus lite，deployment是milvus server。但是ingest步骤基本相似。

对于local来说你需要把所有的文件放到data/target/里面，然后使用readme中local部分的command进行ingest，也就是你截图中第一个code block中的内容。但需要注意的是其中上面是recreate下面是增量更新，我现在其实全部使用的是recreate，因为文档很小。但以后随着文件增加，或者不对现有内容进行修改仅仅是添加的话可能增量更新更快速。repo里也有一些ingest脚本用于早期测试和ingest单个文件。
例如python reingest_company_xlsx.py --xlsx data/target/company.xlsx --collection chatbot_docs
我把俞提供给我的文件命名为company.xlsx然后使用这个脚本进行ingest。无论使用哪种方法都需要确保collection name和你的env对应。

对于deployment来说流程和逻辑都基本相同。但多了一步上传，也就是把需要更新或添加的文件上传到deployment。你需要把文件放入local data/target/然后运行那个上传的bash脚本，也就是截图中第二个code block内的内容。最后在github workflow中手动trigger名为reingest ECS data的workflow就可以了。它的原理和local reingest基本相同，只是把它放到了git action以便自动运行。workflow默认为recreate，后期可能会需要选择为增量，这点和local相同。

2026-10-05 to 2026-10-25 3620

2026-10-26 to 2026-11-15 2618

2026-11-16 to 2026-12-06 0739

2026-11-16 to 2026-12-06 3604

2026-12-07 to 2026-12-27 1600

2025-12-28 to 2025-01-17 2597

2025-01-18 to 2026-02-07 3587

2026-02-08 to 2026-02-28 5704

2026-03-01 to 2026-03-18 6576

11-01 to 03-19  纯商务  5366
