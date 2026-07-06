# 01 · 当前状态（Current State）

> 所有结论基于实际读到的文件。推测项已标注。

## 技术栈（✅ 依据 `requirements.txt` / `README.zh.md` / 源码）

| 层 | 技术 | 备注 |
|---|---|---|
| 语言/运行时 | Python | `.venv` 为 3.12；README 要求 3.10+；**系统 `python3` 实测为 3.9.6**（不能直接用系统 python 跑） |
| Web API | FastAPI 0.128.1 + Uvicorn 0.40.0 | `api/app.py` |
| CLI | Typer + Rich | `src/chatbot/cli/` + 根目录 `chatbot` 包装脚本 |
| 向量库 | Milvus（`pymilvus==2.5.16`） | 本地 Milvus Lite = `./milvus.db`（约 7MB）；部署用 Milvus Server。Qdrant 为已弃用备选 |
| Embedding | SentenceTransformers `BAAI/bge-m3`（默认）/ Ollama | `torch` + `transformers` 为重依赖 |
| 生成 LLM | DeepSeek API（`deepseek-chat`，OpenAI 兼容）/ Ollama | `settings.py` 默认 `llm_provider=deepseek` |
| SQL | SQLAlchemy（SQLite 默认 / MySQL via PyMySQL） | 用于实体解析、部分数据导入 |
| 词法检索 | SQLite FTS5 + RapidFuzz | `src/chatbot/retrieval/bm25.py`、`lexical.py` |

## 目录结构（✅ 排除 `.venv`/`.git`）

```
rag-chatbot/
├── api/                      # FastAPI 服务（app.py 入口, models.py）
├── src/chatbot/
│   ├── cli/                  # Typer CLI: chat / query / ingest / ingest_sql
│   ├── service/qa_service.py # CLI+API 共享的问答入口（answer_question / _stream）
│   ├── rag/pipeline.py       # 构建 prompt
│   ├── retrieval/            # 检索层: retriever/bm25/prf/query_expansion/query_planner...
│   ├── vectorstore/          # milvus_store / qdrant_store / base
│   ├── embeddings/           # st_embedder / ollama / provider
│   ├── llm/                  # client / deepseek_chat / ollama_chat
│   ├── ingest/               # loader / chunking / dedup / qiyu_parser
│   ├── sql/, planning/       # SQL 读取与意图
│   ├── observability/        # logging / metrics / writer（写 traces jsonl）
│   ├── prompts/personas.py   # phone_mom 等人设
│   ├── settings.py           # 统一配置（读 .env）
│   └── masanduo/             # ★ 马三多工作流（线上生效）
├── masanduo_624/             # ★ 同事的独立原始版本（server.py 2424 行 + 自带 admin/chat_ui/knowledge）
├── eval/                     # runner.py + metrics.py（检索评测，缺 golden.jsonl）
├── scripts/                  # 部署/冒烟/基准/数据上传等脚本
├── tests/                    # 少量测试 + qdrant 手动脚本
├── traces/                   # metrics-*.jsonl（运行指标）
├── data/                     # 知识库源文件（target/知识库.md 等，git 忽略）
├── deploy/, k8s/             # 部署清单
├── reingest_*.py             # 各类一次性/历史数据导入脚本
├── Dockerfile, docker-compose.yml, Makefile
├── deploy_masanduo.sh        # 一键 scp 部署到 ECS（含硬编码线上 IP）
└── *.md（多份中英文档，见 docs 说明）
```

## 入口文件（✅）

- **HTTP API**：`api/app.py`（`uvicorn api.app:app`）。手动把 `src/` 加入 `sys.path`。
  - `GET /healthz`、`GET /readyz`
  - `POST /v1/qa` → **走 masanduo 引擎** `chatbot.masanduo.respond`
  - `POST /v1/qa/stream` → 走**原始 RAG** `answer_question_stream`（SSE）
- **CLI**：根目录 `chatbot` 脚本 → `python -m chatbot.cli.chat`；或 `make chat` / `make query` / `make api` / `make ingest`。

## 主要模块与业务流程（✅）

- **通用 RAG**：`qa_service.answer_question` → 检索 top-k（`retriever`）→ `build_prompt` → LLM 生成 → 返回答案+citations+性能指标。
- **马三多工作流**（`src/chatbot/masanduo/engine.respond`）：
  1. `router.route` 关键词路由出意图；
  2. 红线/人工/已下线/电商 → 固定或纯文本回复（不进 LLM）；
  3. 闲聊 → 快速人设 / 或回落 RAG 检索 + SOUL 口吻润色；
  4. 业务意图 → `compute.compute` 确定性计算 → `polish` LLM 润色。
- **会话状态**：`session.py`，纯内存 dict（`_STATE`/`_HISTORY`/`_TOUCHED`），TTL 2h，每会话保留 10 轮。**进程重启即丢，不能多实例，无持久化问答日志。**

## 前端（❓ 推测）

- 无独立前端源码在本仓库主线；`masanduo_624/chat_ui/index.html` 与 `admin/index.html` 是同事版本自带的静态页。
- liuc.md 提到「前端 AiChat 调 `/v1/qa`」，**前端代码不在本仓库**（推测在 `pc_sjmm` 等其它仓库）。待确认。

## 数据库 / 数据

- 向量：`milvus.db`（Milvus Lite 本地文件）；collection 默认 `chatbot_docs`。
- 关系型：SQLite / MySQL（可选，用于 SQL 数据源与实体解析），非核心必需。
- 知识库源文件：`data/target/知识库.md`（676 行）、`办单流程与常见问题解答.csv`、`data/shangwu11to03.xlsx`（七鱼客服记录）。`data/` 被 gitignore。

## 部署方式（✅ 2026-07-03 实机 SSH 只读核查 `47.110.33.91`）

**服务器规格**
- 阿里云 Linux 3（Anolis），x86_64，内核 5.10；已运行 143 天。
- 16 vCPU / 58GB RAM（空闲充裕）；磁盘 315G，用 80G，剩 222G（27%）。
- **GPU：NVIDIA A10（24GB）**，驱动 570 / CUDA 12.8。当前约 14.7GB 被 RAG 进程占用（conda `rag` 环境 python3.12，即 bge-m3 embedding 常驻 GPU），util 0% 空闲。

**实际在跑的（关键：存在两套并行栈）**
1. ✅ **线上生效 = systemd `ragchatbot.service`**：conda `/root/miniconda3/envs/rag`（py3.12）跑 `uvicorn api.app:app --host 0.0.0.0 --port 80`，自 6/18 运行。**它用的是 Milvus Lite**（本地文件 `/root/ragchatbot/milvus.db`，**758MB**，含已导入的知识库向量），由 `milvus_lite` 子进程加载。**前端 `pc_sjmm` 打的就是这个（80 端口）。**
2. ⚠️ **一套 docker compose 栈同时在跑但基本闲置**：容器 `rag-milvus-1`(v2.5.5)、`rag-etcd-1`、`rag-minio-1`、`rag-ollama-1` 均 Up 2–4 个月；而 `rag_api` 容器状态是 **Created（从未启动）**。**即：完整的 Milvus Server 栈在空转，但线上 API 并不用它**（线上用的是 Milvus Lite 文件）。此外主机上还另有一个 `/bin/ollama serve` 进程（与 ollama 容器重复）。
- 结论修正：**docker 实际是开着的**（`docker.service` running + 5 个容器），与「只用 systemd、没开 docker」的印象不符——只是**线上 API 没用到 docker 那套**。

**部署/更新方式**：`deploy_masanduo.sh` scp 覆盖 `masanduo` 子包 + `api/app.py` → `systemctl restart ragchatbot`。
**k8s/**、`.github/workflows/`：未见在该机使用（无 k8s 运行痕迹）。
**宝塔**：✅ 2026-07-03 已安装宝塔面板 **9.0.0（当前最新代正式版，无需重装）**，面板端口 `28934`，路径 `/2526da89`，安全组已放行 28934，用户已能登录。首登"绑定"提示=账号绑定/访问限制，属正常，建议保留 IP 限制不取消。安装**未影响线上**：`ragchatbot` 仍 active，`/healthz`、`/v1/qa` 实测正常。安装副作用：**firewalld 被启用**（public zone 已放行 20/21/22/80/443/28934/39000-40000）。⚠️ 尚未用 nginx 做反代（uvicorn 仍直占 80，反代迁移为后续单独步骤）。
**对外端口**：22（sshd）、80（uvicorn RAG）、28934（宝塔面板）、3000（Langfuse，待安全组放行）。⚠️ 80 端口日志可见大量公网扫描/攻击探测。

**Langfuse（会话维护+评分后台）** ✅ 2026-07-03 已在该机 docker 自托管：
- 目录 `/root/langfuse/`（`docker-compose.yml` + `.env`，官方 v3 栈：langfuse-web/worker + postgres + clickhouse + redis + minio）。
- 访问：`http://47.110.33.91:3000`（需在阿里云安全组放行 3000，建议限来源 IP）。登录/项目密钥见服务器 `/root/langfuse/.env`（勿外传）。
- 预置：org=ShouJiMaMa、project=masanduo-rag（已带 public/secret key，供 RAG 打点用）；已 `AUTH_DISABLE_SIGNUP=true`。
- ⚠️ 运维坑：宝塔启用 firewalld(nftables) 会打断 docker 新建网络的容器间转发，需 `systemctl restart docker` 让其重建 `docker` firewalld 区（已处理；重启机器后若 docker 早于 firewalld 启动需复查）。
