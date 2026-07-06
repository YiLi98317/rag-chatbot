# 04 · 已知问题（Known Problems）

> 分级：🔴 高危 / 🟠 中 / 🟡 低。每项标注证据来源与「确定/推测」。

## 🔴 安全风险

1. **🔴 密钥可能进过 git 历史（需轮换）**
   - 证据：`liuc.md` 明确记录「同事原 `masanduo_624` 里那个明文 DeepSeek 密钥 `sk-da10cc...` 已进过 git，建议去 DeepSeek 后台吊销重发」。
   - 现状：当前工作区 `masanduo_624/` 未再 grep 到 `sk-`（推测已从当前文件移除，但**历史 commit 仍可能存在**，未在本轮深挖 git 历史）。
   - 建议（待用户执行）：轮换 DeepSeek Key；确认后再考虑历史清理（本轮不动）。

2. **🔴 生产服务器暴露面**
   - 证据：`liuc.md`「服务器是 root + 弱口令直连公网，80 直连」。
   - 建议：换密钥登录、关 80 直连、上反代/防火墙。（运维决策，待确认）

3. **🟠 部署脚本与文档把线上 IP/路径硬编码并提交 git**
   - 证据：`deploy_masanduo.sh`（已被 git 跟踪）内含 `root@47.110.33.91`、`/root/ragchatbot`；`liuc.md` 同样含 IP。
   - 影响：仓库一旦外泄即暴露线上入口。

4. **🟡 `.env` 含真实 key 但已被 gitignore**
   - 证据：`.gitignore` 忽略 `.env`；`grep` 到 `.env` 内有 `sk-`。当前未被跟踪，风险可控，但需确保历史中从未提交过。

## 🔴/🟠 架构 & 可维护性

5. **🔴 会话状态纯内存，无持久化（与用户目标冲突）**
   - 证据：`src/chatbot/masanduo/session.py` 用进程内 dict，TTL 2h，重启即丢，多实例不共享。
   - 影响：用户想做的「后台维护会话 + 评分」**无数据可维护**——问答历史没有落库（仅 `traces/*.jsonl` 有极薄的 query/latency）。这是最大功能缺口。

6. **🟠 两套马三多并存、不同步（双源真相）**
   - 证据：`src/chatbot/masanduo/`（线上生效） vs `masanduo_624/`（同事独立版 `server.py` 2424 行 + 自带 admin/chat_ui/knowledge）；`knowledge/*.json` 双份。
   - 影响：改一处不同步另一处，知识数据易漂移。哪份权威**待确认**（当前 `/v1/qa` 走 `src` 版）。

7. **🟠 两个问答端点逻辑分叉**
   - 证据：`api/app.py` 中 `/v1/qa` 走 masanduo，`/v1/qa/stream` 走原始 RAG（`answer_question_stream`），人设/检索/prompt 不一致。
   - 影响：行为不一致，测试与维护成本高。

8. **🟠 历史/教程数据脚本与业务混杂**
   - 证据：根目录 `reingest_chinook.py`、`reingest_chinook_mysql.py`、`reingest_thucnews.py` 是音乐库/新闻分类教程数据，与手机租赁无关；`reingest_company_xlsx.py`、`reingest_qiyu.py` 才是业务相关。
   - 影响：新人/AI 难分辨哪些是真业务路径。（本轮不删，仅记录）

9. **🟡 文档过多且互相矛盾**
   - 证据：`README.md`/`README.zh.md`/`intro*.md`/`本地启动指南.md`/`部署与使用指南.md`/`知识库建设指南.md`/`API上线指南.md`/`liuc.md`/`同事给的.md`。其中 `.env` 默认值在 README（deepseek+ST）与本地启动指南（ollama+qwen3）之间不一致。

## 🟠 启动 / 构建 / 运行风险

10. **🟠 Python 版本不一致**
    - 证据：系统 `python3`=3.9.6，`.venv`=3.12，README 要求 3.10+。`make install` 用系统 python 建 venv 可能建出 3.9 环境导致失败。

11. **🟠 重依赖冷启动慢**
    - 证据：`requirements.txt` 含 `torch`/`transformers`/`sentence-transformers`；bge-m3 首次下载约 2GB。CI/新环境构建慢、易超时。

12. **🟡 检索层堆叠复杂、收益未验证**
    - 证据：`retrieval/` 有 planner/bm25/prf/qexp/decompose/entity_resolver 多层，全靠 env 开关。无 golden set 无法判断各层是否有正收益。

## 🔴 评测缺失（与用户目标强相关）

13. **🔴 没有可用的答案评测体系**
    - 证据：`eval/runner.py` 只做检索 recall@k/mrr，且依赖的 `eval/golden.jsonl` **缺失**（运行即 `NO_GOLDEN`）。无答案质量评分、无 LLM 裁判、无人工评分界面、无禁用话术自动检查。
    - 影响：用户要的「benchmark / 评分后台」目前是零基础。

## 类型 / 测试

14. **🟡 无强类型保障、测试稀疏**
    - 证据：`pyproject.toml` 只配了 ruff + pyright extraPaths，无 mypy 严格模式；`tests/` 多为 Qdrant 手动脚本，缺业务单测与统一 pytest 基线。

## 🔴 新增安全项（2026-07-03）

20. **🔴 线上 DeepSeek API Key 明文存在于备份文件**
    - 位置：本地备份 `server-backup-.../config/env.server` 第 10 行（`sk-3c2f…`，已脱敏不复述）。这是**当前线上生效的 key**。
    - 该备份目录位于 workspace（本身是 git 仓库）内，⚠️ 切勿 `git add`/提交/外发。建议轮换该 key，并把备份目录加入根 `.gitignore` 或移到仓库外。

## 🟡 路由质量（经 Langfuse 观测发现，2026-07-03）

21. **🟡 关键词路由存在误判**
    - 实例：「你们平台碎屏保怎么理赔」被 `router.route` 判为 `buyback`（应为售后/质保/规则类）。
    - 原因：`router.py` 是纯关键词优先级匹配，缺乏语义理解，边界问题易误判。
    - 价值：这类问题现在能在 Langfuse trace 的 `intent/path` 看到，是评测→改进的典型闭环样本（可先用规则补关键词，或后续引入意图分类）。本轮仅记录，不改路由。

## 用户确认问题（2026-07-03 已答复）

- Q1 ✅ 权威版本 = `src/chatbot/masanduo/`；`masanduo_624/` 是无用备份，可冻结（本轮不删）。
- Q2 ✅ 线上只用 systemd + scp，未开 docker/k8s。
- Q3 ✅ `.env` 线上 ≈ DeepSeek API + 服务器模型。
- Q4 ✅ key 泄露由用户在生产环境自行更换，本项目不处理。
- Q5 ✅ 评分 = 人工 + LLM 结合，目的做好知识库（非微调）。
- Q6 ✅ 前端在 `pc_sjmm/src/pages/AiChat_v3.0/index.jsx`。

## 新增：服务器实机核查发现（2026-07-03 SSH 只读，🔴/🟠）

16. **🔴 抹机前必须先备份不可再生数据**
    - 线上真实 KB 向量在 `/root/ragchatbot/milvus.db`（**758MB，Milvus Lite 文件**），本地副本只有 7MB（不是同一份）。还有 `/root/ragchatbot/.env`（473B，线上配置）、`traces/`（今日仍在写）、`api.log`。
    - ⚠️ 一旦重装系统这些会全丢。重装/装宝塔前**先 scp 下载备份**（尤其 `milvus.db` 与 `.env`）。

17. **🟠 两套向量栈并存、资源浪费、真相分裂**
    - 线上 API 用 Milvus **Lite（文件）**；同时 docker 里跑着完整 Milvus **Server** 栈（etcd+minio+milvus+ollama）却没被线上使用，`rag_api` 容器从未启动。
    - 主机 `/bin/ollama serve` 与 `rag-ollama-1` 容器重复。
    - 影响：常年空转吃内存/GPU 显存，且"到底连哪个 Milvus"容易误判。重装是清理良机。

18. **🔴 公网暴露面（复述并实证）**
    - 80 端口直接对公网，日志实测有持续攻击探测；22 端口 root 可登、密码本轮被明文传输。
    - 建议（用户自理）：装反代/防火墙、80 不直连、换密钥登录、轮换密码。

19. **🟡 A10 GPU 未被充分利用**
    - A10（24GB）目前仅承载 bge-m3 embedding（~14.7GB）。这台配置足以本地跑 Qwen 系列 LLM / 自托管 Langfuse（docker 已就绪）。

## 新增：前端集成缺口（由代码确认，🟠）

15. **🟠 前端未传 `session_id`，无多轮 / 无用户角色归因**
    - 证据：`pc_sjmm/src/pages/AiChat_v3.0/index.jsx` 只 `POST {question}`，硬编码 `http://47.110.33.91/v1/qa`（明文 HTTP）。
    - 影响：① 后端每条消息新建 `api-<uuid>`，`session.py` 的多轮记忆实际用不上；② 无法把问答/评分归因到用户、角色（加盟商/店员/客服）、门店；③ 用户想要的「按角色返回不同答案」「按会话维护+评分」缺前端配合。
    - 备注：`/v1/qa` 已支持可选 `session_id`，属前端小改（但本轮不改代码，仅记录）。
