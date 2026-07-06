# 03 · 运行手册（Runbook）

> ⚠️ 以下命令**大部分未在本次审计中实际执行**（本轮为只读审计）。命令来自 `Makefile`、`README.zh.md`、`本地启动指南.md`，风险项已标注。首次运行请逐条验证。

## 环境前提

- ✅ 需要 Python **3.10+**（`.venv` 已是 3.12）。⚠️ **本机系统 `python3` 实测为 3.9.6**，`make install` 里的 `python3 -m venv` 会用系统 python 建 3.9 的 venv，可能导致依赖或运行不兼容。**建议显式用 3.10+ 的解释器建 venv**，或复用现有 `.venv`。
- DeepSeek API Key（默认 LLM）或本地 Ollama（可选）。

## 安装依赖

```bash
cd rag-chatbot
make install          # = python3 -m venv .venv && pip install -r requirements.txt
```

⚠️ 风险：
- 依赖含 `torch` / `transformers` / `sentence-transformers`，安装体积大、耗时长；首次用 `BAAI/bge-m3` 需下载约 2GB 模型。
- 若系统 python 为 3.9，先手动建 3.10+ venv：`python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`（推测命令，按本机实际解释器名调整）。

## 配置 `.env`

```bash
cp .env.example .env    # 若尚无 .env
```

⚠️ **文档间存在矛盾**（需以实际 `.env` 为准）：
- `README.zh.md` / `.env.example`：默认 `LLM_PROVIDER=deepseek` + `EMBED_PROVIDER=sentence_transformers` + `BAAI/bge-m3`。
- `本地启动指南.md`：描述 `.env` 为全本地 Ollama 模式（`qwen3-embedding` / `qwen3:8b`）。
- 实测当前 `.env` 中存在一个 `sk-` 开头的 key（见 `docs/04-known-problems.md` 安全项）。

关键变量（完整见 `.env.example`）：`VECTOR_PROVIDER=milvus`、`MILVUS_LITE_DB=./milvus.db`、`MILVUS_COLLECTION=chatbot_docs`、`LLM_PROVIDER`、`API_KEY`、`API_BASE_URL=https://api.deepseek.com`、`MODEL_NAME=deepseek-chat`、`EMBED_PROVIDER`、`EMBED_MODEL`、`ANSWER_PERSONA=phone_mom`。

## 导入知识库（ingest）

```bash
# 全量重建（文档小，当前默认用这个）
DATA_DIR=data/target make ingest collection=chatbot_docs args="--recreate"

# 增量（追加/更新）
DATA_DIR=data/target make ingest collection=chatbot_docs
```

七鱼客服数据（可选增强，别加 `--recreate` 以免覆盖知识库）：

```bash
python reingest_qiyu.py --xlsx data/shangwu11to03.xlsx --collection chatbot_docs --mode both --max-sessions 100 --min-rounds 2
```

⚠️ ingest 需要 embedding 模型可用（本地 ST 或 Ollama），且 `MILVUS_LITE_DB` 可写。

## 本地测试（CLI）

```bash
make chat collection=chatbot_docs            # 交互式
make chat collection=chatbot_docs DEBUG=1    # 显示 planner/检索详情
make query q="怎么锁机" collection=chatbot_docs
```

## 本地启动 HTTP API

```bash
make api    # = uvicorn api.app:app --reload --port 8000
# 健康检查
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
# 问答（走 masanduo 引擎）
curl -X POST http://localhost:8000/v1/qa -H "Content-Type: application/json" -d '{"question":"16pm回收多少"}'
```

## 测试 / 评测

```bash
make smoke                 # scripts/smoke.py 冒烟
make eval_ablate           # 检索消融（bm25/prf/qexp），⚠️ 需要 DB_URI 和 eval/golden.jsonl
make ci_gate               # scripts/ci_eval_gate.sh
```

⚠️ **评测现状**：`eval/runner.py` 依赖 `eval/golden.jsonl`，该文件**当前缺失**，会直接输出 `NO_GOLDEN=1` 并跳过。且只评检索 recall@k / mrr，不评答案质量。`tests/` 里多为 Qdrant 手动脚本 + 少量单测，无统一 `pytest` 绿灯基线（待确认）。

## 构建 / 容器 / K8s（存在但线上未必在用）

```bash
make docker-build && make docker-run     # 本地 docker
make compose-up                          # docker compose（etcd/MinIO/Milvus/Ollama/API）
# k8s（kind/k3d 本地）：make k8s-dev-up 等，见 Makefile 与 deploy/README.md
```

## 线上部署（⚠️ 生产，未经用户同意勿执行）

- 实际线上：ECS `47.110.33.91`，systemd 服务 `ragchatbot`，Uvicorn 端口 80。
- 部署脚本 `deploy_masanduo.sh`：备份 → scp `masanduo` 子包 + `api/app.py` → `systemctl restart` → 冒烟。
- 排错：`systemctl status ragchatbot` / `journalctl -u ragchatbot -n 50`。
- 回滚：服务器上有 `api/app.py.bak.*`，拷回再 restart。

> 本轮审计不执行任何以上生产命令。仅记录。
