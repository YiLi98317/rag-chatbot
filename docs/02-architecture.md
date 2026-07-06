# 02 · 架构现状（不美化版）

> 目标：如实描述现有架构，包括混乱之处。不假装它清晰。

## 高层数据流

```
客户端(前端 AiChat，不在本仓库)
        │  POST /v1/qa {question, session_id?}
        ▼
api/app.py  ── /v1/qa ──► chatbot.masanduo.respond()   ← 线上主路径
        │                    │
        │                    ├─ router.route()  关键词意图路由（秒级，无 LLM）
        │                    │      ├ 红线(套机/监管机) ─► replies.py 固定文案
        │                    │      ├ human/poster/ecommerce ─► 固定或模板文本
        │                    │      ├ 业务意图 ─► compute.compute()(确定性计算) ─► polish()(LLM润色)
        │                    │      └ chat/未命中 ─► _rag_fallback() ─► 检索 + SOUL 口吻润色
        │                    ▼
        │                 session.py（纯内存多轮状态）
        │
        └── /v1/qa/stream ──► qa_service.answer_question_stream()  ← 原始 RAG，SSE
                                   检索 top-k ─► build_prompt ─► LLM 流式生成
```

**⚠️ 架构裂缝 1**：`/v1/qa`（马三多）和 `/v1/qa/stream`（原始 RAG）走的是**两套不同逻辑**，人设、检索、prompt 都不一致。非流式=马三多，流式=旧 RAG。

## 通用 RAG 检索层（`src/chatbot/retrieval/`）

`retrieve_top_k` 之上叠了多层可选检索增强，均由 `settings` 特性开关控制：

- `query_planner`（`ENABLE_QUERY_PLANNER`，默认开）——LLM 查询改写/规划
- `bm25`（FTS5，`ENABLE_BM25_LAYER`）
- `prf`（伪相关反馈，`ENABLE_PRF_LAYER`）
- `query_expansion`（`ENABLE_QEXP_LAYER`）
- `entity_resolver` / `normalize` / `decompose`

向量检索走 `vectorstore`（Milvus 主，Qdrant 弃用备选），embedding 走 `embeddings`（SentenceTransformers bge-m3 或 Ollama）。

**⚠️ 架构复杂度**：检索层堆叠层数多，理解成本高。是否所有层都在线上启用、是否都有收益，**待评测确认**（当前无 golden set，见 known-problems）。

## 马三多工作流（`src/chatbot/masanduo/`）

单一公开 API：`respond(message, session_id, surname, settings) -> str`。

| 文件 | 职责 |
|---|---|
| `engine.py` | 编排入口：route → compute → 固定/回落/润色 |
| `router.py` | 关键词意图路由（红线优先 → 复合推演 → 各业务意图 → chat 兜底） |
| `compute.py` | 确定性业务计算（回收价/租机方案/复合推演等） |
| `polish.py` | 用 SOUL 人设润色（polish / polish_chat / polish_with_context） |
| `replies.py` | 红线/人工/下线功能的固定文案 |
| `session.py` | 纯内存多轮状态 |
| `extract.py` | 机型/俗称抽取 |
| `data.py` / `knowledge/*.json` | 库存、回收价、平台规则等结构化数据 |
| `ecommerce.py` / `tools.py` / `persona.py` / `cli.py` | 电商素材、工具、人设、命令行 |

设计意图（合理）：**确定性数字用代码算，语气用 LLM 润色**，红线用固定文案不进 LLM。这与用户「规则约束 + 检索引用 + 转人工」的思路一致。

## 依赖与配置

- 配置集中在 `settings.py`（`get_settings()` 读 `.env`，返回 frozen dataclass）。这是**做得好的地方**：单一配置入口、fail-fast 校验。
- 依赖较重：`torch` + `transformers` + `sentence-transformers`（embedding），冷启动/安装慢。

## 数据与状态

- 向量数据：`milvus.db`（本地）/ Milvus Server（线上）。
- 会话状态：内存，进程内。**无数据库持久化**。
- 运行指标：`observability/metrics.py` → `writer.write_trace_line` → `traces/metrics-YYYYMMDD.jsonl`（仅 query/latency/lang，字段很薄，且部分 `token_usage=null`）。
- 结构化业务数据：`masanduo/knowledge/*.json` 与 `masanduo_624/knowledge/*.json`**重复两份**。

## 重复 / 并行代码（⚠️ 重点）

- `src/chatbot/masanduo/`（集成版，线上生效） vs `masanduo_624/`（同事独立版，`server.py` 2424 行，自带 admin/chat_ui/knowledge）——**功能重叠、不同步、双份知识 JSON**。
- 根目录多个 `reingest_*.py`（chinook / chinook_mysql / company_xlsx / qiyu / thucnews）：部分是早期测试/教程数据（chinook、thucnews），与手机租赁业务无关，属历史遗留。
- 多份说明文档（`README.md`/`README.zh.md`/`intro*.md`/`本地启动指南.md`/`部署与使用指南.md`/`知识库建设指南.md`/`API上线指南.md`/`liuc.md`/`同事给的.md`）——信息分散、可能相互矛盾。

## 与「后台维护+评分」目标的架构差距

现状缺三块（用户目标需要）：
1. **会话持久化**：把每次问答（问题/角色/检索命中/回答/是否转人工/耗时）落库，而非只在内存 + 薄 traces。
2. **评分/评测后台**：`eval/` 只有检索 recall@k / mrr，且 `golden.jsonl` 缺失；没有答案质量评分、人工评分界面、LLM 裁判。
3. **角色/权限与引用来源**：SOUL 里有「不编造/转人工」约束，但没有结构化的 `sources`/`confidence`/`need_human` 输出契约。

## 更新（2026-07-04）：结构化契约 + 反馈 + 知识库治理

- 已补**结构化输出契约**：`engine.respond_full()` → `QaOutput{answer, sources, confidence, need_human, trace_id, intent, path}`；`/v1/qa` 追加可选字段并返回 Langfuse 真实 `trace_id`。`respond()` 保持返回字符串向后兼容。
- 已补**用户反馈闭环**：新增 `POST /v1/feedback` → `log_feedback` 写 Langfuse score；前端 `pc_sjmm/AiChat_v3.0` 加富反馈组件（待发版）。
- 已补**知识库治理**：`loader.py` 解析 frontmatter（保留 `source_type=file`）；`知识库.md` 拆入 `data/knowledge/`；线上切换用独立 `milvus_v2.db` + `.env` 一行切换（可回滚）。详见 `docs/09`、`docs/12`。
