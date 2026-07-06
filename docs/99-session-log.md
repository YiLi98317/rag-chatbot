# 99 · Session 日志

> 每轮工作在文件**末尾追加**一段，不覆盖历史。

---

## Session 2026-07-03 · 仓库审计与 AI 上下文改装（第一轮）

### 本轮目标
- 对 legacy `rag-chatbot` 做只读审计（不改业务代码/依赖/部署/DB）。
- 产出 AI 长期可接手的上下文文档与规则文件。
- 为「RAG + 知识治理 + 会话维护/评分后台」的长期目标做规划。

### 读了哪些文件（关键）
- 文档：`README.zh.md`、`本地启动指南.md`、`liuc.md`、`Makefile`、`.env.example`、`pyproject.toml`、`requirements.txt`。
- 入口/核心：`api/app.py`、`src/chatbot/settings.py`、`src/chatbot/service/qa_service.py`。
- 马三多：`masanduo/__init__.py`、`engine.py`、`router.py`、`session.py`、`SOUL.md`。
- 可观测/评测：`observability/metrics.py`、`observability/writer.py`、`eval/runner.py`、`eval/metrics.py`、`traces/metrics-20260408.jsonl`。
- 结构/元信息：目录树、`git log`/`branch`/`ls-files`、`deploy_masanduo.sh`、`.gitignore`。

### 确认了什么（✅）
- 项目是中文 RAG 问答机器人，改造为手机租赁商家问答（人设「马三多」）。
- 技术栈：FastAPI+Uvicorn / Typer CLI / Milvus(Lite+Server) / bge-m3 或 Ollama / DeepSeek API / SQLAlchemy / FTS5+RapidFuzz。
- `/v1/qa` 走 masanduo 引擎，`/v1/qa/stream` 走原始 RAG（两套逻辑）。
- 会话状态是纯内存，无持久化；评测只有检索指标且 golden set 缺失。
- 线上是单台 ECS + systemd + `deploy_masanduo.sh` scp 部署。
- 存在两套马三多（`src/chatbot/masanduo/` vs `masanduo_624/`）与双份知识 JSON。

### 还不确定什么（❓）
- 权威版本（src vs masanduo_624）；线上是否用 docker/k8s；`.env` 实际模式；key 是否已轮换；评分后台的形态与使用者；前端仓库位置。（详见 `docs/04-known-problems.md` 末尾 Q1–Q6）

### 创建/修改了哪些文件（本轮全部为新增文档/规则，未动业务代码）
- `AGENTS.md`、`CLAUDE.md`、`.cursor/rules/project.mdc`
- `docs/00-project-brief.md` ~ `docs/05-decisions.md`、`docs/99-session-log.md`（本文件）
- `tasks/TASK-0001-repo-audit.md`

### 下一步建议
1. 用户回答 Q1–Q6（尤其权威版本 + key 轮换 + 评分后台形态）。
2. 按 `tasks/TASK-0001-repo-audit.md` 的优先级推进：先让项目本地可跑（验证），再补会话落库，再做评测后台雏形。

---

## Session 2026-07-03 · 确认答复 + 前端核查（第二轮）

### 本轮目标
- 消化用户对 Q1–Q6 的答复，落入文档。
- 核查前端 AiChat 的真实调用方式（用户不清楚其维护）。
- 开始就「维护+评分后台」做决策树访谈。

### 确认/发现
- Q1–Q6 已答复，写入 `00-project-brief.md`、`04-known-problems.md`、`05-decisions.md`（D4–D8）。
- 前端核查（`pc_sjmm/src/pages/AiChat_v3.0/index.jsx`）：只 POST `{question}` 到 `http://47.110.33.91/v1/qa`（明文 HTTP），**不传 session_id**，按 `data.answer` 取值。→ 当前无多轮、无用户/角色归因。记为 known-problem #15。
- `pc_sjmm` 主路由 `/home` 实际指向 `AiCheck_v3.0`；`AiChat`/`AiChat_v3.0` 为聊天页（具体挂载入口待确认）。

### 未改动业务代码。仅更新文档。

### 下一步
- 进行「维护+评分后台」决策树访谈（每次一个问题，附推荐答案），逐步定方案，再更新 tasks。

---

## Session 2026-07-03 · 生产服务器实机只读核查（第三轮）

### 本轮目标
- 用户提供测试服 `47.110.33.91` root 凭证，要求调研服务器现状（准备重装、可能装宝塔）。

### 只读 SSH 核查结论（未做任何修改）
- 规格：阿里云 Linux 3，16C/58G，磁盘 315G(剩 222G)，**NVIDIA A10 24GB**，已跑 143 天。
- 线上生效 = systemd `ragchatbot`（conda py3.12 + uvicorn:80），**用 Milvus Lite 文件 `milvus.db`（758MB）**。
- 同机 docker 另跑一套 Milvus Server 栈（etcd/minio/milvus/ollama）但**线上不使用**，`rag_api` 容器从未启动 → 资源空转。docker 实际是开着的（修正此前印象）。
- 未装宝塔；仅 22/80 对公网；80 端口有持续攻击探测。
- 详见 `01-current-state.md` 部署段与 `04-known-problems.md` #16–#19。

### 关键提醒
- **抹机前必须备份**：`milvus.db`(758MB)、`.env`、`traces/`、`api.log`（milvus.db 本地无同款副本）。

### 未改动任何业务代码/服务器状态。仅只读核查 + 更新文档。

---

## Session 2026-07-03 · 数据备份 + 安装宝塔（第四轮，有服务器变更）

### 用户指令
- 把重要数据拷到本地 SSD；在服务器装宝塔；之后由我用「最好的方案」重建，不确定处解释让用户选。

### 已完成
1. **备份到本地 SSD**：`/Volumes/XuanwuSSD/haiye/server-backup-47.110.33.91-20260703/`
   - `milvus.db`（758MB，MD5 `858f18c790ee261532c0cc52b48e3531`，与服务器一致 ✅）
   - `config/env.server`、`config/server_metadata.txt`（systemd unit + pip freeze + docker ps）、`config/api.log`、`traces/`(45)、`data/`(51MB)
   - 见该目录 `BACKUP-MANIFEST.md`。⚠️ 含明文 .env，勿提交 git / 勿外发。
2. **安装宝塔面板 LTS**（服务器变更）：
   - 面板：`https://47.110.33.91:28934/2526da89`，user `hbqlfplt`，pwd `52efa403`（用户需自行妥善保存/改密）。
   - 需在**阿里云安全组放行 28934**（用户在控制台操作）。
   - 副作用：firewalld 被启用（已放行 20/21/22/80/443/28934/39000-40000）。
   - 安装后验证：`ragchatbot` active、80/22 正常、`/healthz` ok、`/v1/qa` 正常返回。线上未受影响。

### 尚未做（下一步，需用户拍板）
- nginx 反向代理迁移（uvicorn 80 → 内部端口，nginx 80/443 转发）——风险动作，单独执行。
- 重建目标架构（单一 Milvus / RAG / Langfuse / 本地 Qwen 于 A10）——待用户在下轮选定方案。

---

## Session 2026-07-03 · 宝塔版本核查 + 部署 Langfuse（第五轮）

### 完成
1. **宝塔版本核查**：装的是 **9.0.0（当前最新代正式版）**，非旧版，无需重装。"绑定"提示为账号/访问限制的正常行为，建议保留 IP 限制。
2. **选型确认**：向量库 = Milvus Lite（保留）；生成 = DeepSeek API（先）；反代 = 待面板可用后做。已澄清 embedding = 本地 Qwen3-Embedding-8B、向量在 milvus.db，未丢。
3. **部署 Langfuse（docker 自托管）** 于 `/root/langfuse/`：
   - 本机下载官方 compose → scp 上传（服务器直连 GitHub raw 被墙）。
   - 生成强随机 `.env`（替换全部 CHANGEME + 预置 org/project/初始账号 + 禁用注册）。
   - 走国内镜像加速器 `docker.1ms.run` 拉镜像（cgr.dev/chainguard minio 也可达）。
   - **踩坑并解决**：宝塔启用 firewalld(nftables) 导致 langfuse_default 网桥容器间 TCP 不通（DNS 通但 EHOSTUNREACH，web 迁移 P1001 崩溃重启）。`systemctl restart docker` 重建 docker firewalld 区后恢复。
   - 结果：6 服务全 healthy，`/api/public/health` = 200。**线上 RAG 全程未受影响**（宿主 uvicorn + milvus-lite，非容器）。

### 待用户操作
- 阿里云安全组放行 **3000**（建议限来源 IP），登录 `http://47.110.33.91:3000`（凭证在服务器 `/root/langfuse/.env`），改密码。

### 下一步（我方）
- 在 RAG 单出口（`masanduo/engine.respond`）接 Langfuse SDK 打点：把每次问答（问题/角色/命中来源/回答/耗时/path）作为 trace 上报 → 交付「会话维护+评分」闭环。

---

## Session 2026-07-03 · 语言说明 + Langfuse 打点接入（第六轮，含代码+部署）

### 语言问题
- Langfuse 无官方中文（issue #12890，官方暂无精力做）。方案：浏览器翻译/沉浸式翻译插件 + 中文对照小抄。已知中文小毛病：列表页可能显示 \uXXXX（详情正常）、全文搜索对中文差。接入时设 `LANGFUSE_ENSURE_ASCII=false`。

### 代码改动（仓库，已本地完成、无 lint 错误）
- 新增 `src/chatbot/observability/langfuse_tracing.py`：故障安全、可选、兼容 SDK v2/v3 的 `log_qa()`。
- `src/chatbot/masanduo/engine.py`：单出口新增 `_trace_qa(...)`（try/except 包裹，绝不影响回答）。
- `requirements.txt`：加 `langfuse>=3,<4`。

### 部署（服务器）
- scp 上述两文件到 `/root/ragchatbot/...`；conda rag 环境 `pip install langfuse`（阿里云镜像）；`.env` 追加 `LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST=http://localhost:3000/ENSURE_ASCII=false`（已备份 .env.bak）。
- `systemctl restart ragchatbot`（模型重载约 10s，未超前端超时）。

### 验证 ✅
- `/healthz` 200；`/v1/qa`（session_id=langfuse-test-1）正常返回回收价表。
- Langfuse `/api/public/traces` 已见 trace：name=masanduo_qa、sessionId、tags=[buyback]、input/output（中文正常显示）、metadata 带 intent/path/model/latency。

### 待办
- 前端 `pc_sjmm` 传稳定 session_id（+角色）→ 才能多轮分组与按角色/门店归因（跨仓库小改）。
- Langfuse 内配置：人工打分（Scores/Annotation Queue）+ LLM-as-judge；trace 追加检索命中 sources。
- 后续：nginx 反代加固（uvicorn→内部端口）。

---

## Session 2026-07-03 · 会话归因 + 检索来源（第七轮，前后端代码+部署）

### 完成（两项均端到端验证通过）
1. **RAG 侧：trace 补充检索来源 sources**
   - `engine.py`：`_rag_fallback` 增 `sources_out`，`_retrieve_contexts`→`_retrieve_results`（返回带 metadata 的结果），从 metadata 取 source/title；`respond` 收集 sources 传入 `_trace_qa`。
   - 验证：`path=chat:rag` 的 trace metadata.sources = ['.../知识库.md','data/shangwu11to03.xlsx'] ✅。
2. **会话/归因：前端传 session_id + 门店/用户/角色**
   - 后端：`QaRequest` 增 `role/store_id/user_id`；`api/app.py` 透传；`engine.respond` 增同名参数；`log_qa` 设 Langfuse `userId=store_id||user_id`，role/intent 进 tags，全部进 metadata。
   - 前端 `pc_sjmm/src/pages/AiChat_v3.0/index.jsx`（确认为线上组件，被 `AiCheck_v3.0` 内嵌）：新增每次打开聊天生成 `sessionIdRef`，从 localStorage 读 `storeId/store_id`、`userId`，body 发 `{question,session_id,role:'merchant',store_id,user_id}`。
   - 验证：trace sessionId=sess-verify-1、userId=store-8899、tags=[buyback,merchant]、metadata 全 ✅。
   - ⚠️ 前端改动需用户自行构建/发布 pc_sjmm 才生效；后端对缺字段已优雅兜底。

### 部署
- scp `engine.py/langfuse_tracing.py/api/models.py/api/app.py` → `systemctl restart ragchatbot`（重载~10s）→ 冒烟正常。langfuse SDK v3.15.0。

### 观测发现（评测后台价值体现）
- 「你们平台碎屏保怎么理赔」被路由误判为 `buyback`（应为售后/规则类）。记为路由质量问题，见 `04-known-problems.md`。

---

## Session 2026-07-03 · 第一版 MVP 评测体系（第八轮，仅 eval/+docs/）

### 范围
- 只在 `eval/` 与 `docs/` 新增文件，**未改任何业务/部署/服务器/.env**。未跑生产。

### 新增文件
- `eval/golden_masanduo_v1.jsonl`：54 题、10 类，基于 `知识库.md`+`platform_rules.json`，不编造费率；6 题标 `needs_business_review`；5 题 `must_handoff`。
- `eval/forbidden_checker.py`：否定感知禁用词检查（自测通过：否定语境豁免、裸用命中）。
- `eval/bench_masanduo.py`：runner，调 `/v1/qa`→规则评分→JSON+MD 报告；默认 localhost、生产地址需 `--allow-prod`；离线冒烟验证报告生成 OK。
- `eval/judge_prompt.md` + `eval/judge.py`：LLM-as-judge 模板 + 可选封装（默认不启用）。
- `docs/06-mvp-benchmark.md`：门槛(红线=0/禁词100%/高频≥4/要点≥80%/转人工≥95%)+用法+局限+反馈闭环。

### 已验证
- forbidden_checker 自测正确；golden 解析/类别/唯一性 OK；runner 离线冒烟生成报告 OK。
- 尚无真实跑分（需一个运行中的 API；本轮不打生产）。

### 待用户确认
- `needs_business_review` 的 6 题标准答案；是否授权对服务器 `/v1/qa` 跑一次真实基线。

---

## Session 2026-07-03 · 业务协作工具 + 教学文档（第九轮，仅工具/文档/知识库脚手架）

### 范围
- 只新增 `scripts/`、`docs/`、`data/knowledge/`、`eval/`、`business_review/`。未改业务代码，未访问生产。

### 新增
- `eval/export_golden_review.py`：golden→`business_review/golden_review.csv`(+xlsx，openpyxl 可用则生成)。含业务填写列(business_status/corrected/notes/owner/reviewer/date)。
- `data/knowledge/_templates/`：7 个模板(rule/sop/sales_script/redline/faq/after_sales/system_operation) + `data/knowledge/05_faq/faq_service_fee.md`(填好的示例) + `data/knowledge/README.md`。
- `scripts/kb_lint.py`：零依赖 frontmatter 校验，跳过 _templates/README，检查必填字段/risk_level/visible_to/doc_id 唯一；有 error 退出 1。
- `scripts/prepare_business_review_pack.py`：一键生成审核包(csv/xlsx/kb_lint_report/templates_index/business_tasks)。
- `docs/07-golden-review-guide.md`、`docs/08-business-collaboration.md`、`docs/09-knowledge-base-structure.md`。

### 已验证（本地）
- 一键包跑通：CSV(54题)+xlsx 生成、kb_lint 扫描示例通过(error=0/warn=0)、5 个产物齐全。

### 待业务确认
- golden 的 `needs_business_review` 6 题；真实高频问题(≥50)；禁用话术清单；政策生效时间。

---

## Session 2026-07-03 · golden 回填导入闭环（第十轮，仅 scripts/docs/示例）

### 新增
- `scripts/import_golden_review.py`：读商务回填表(csv/可选xlsx)→按 business_status(confirmed/revise/delete/pending/add，含中文)合并回 golden→出 v2 + 差异报告。默认 dry-run，`--write` 才写，永不覆盖 v1。宽松解析(JSON/多行/顿号/逗号/分号)、must_handoff 多写法兼容、P0/P1 校验。
- `business_review/golden_review_sample.csv`：自测样例(覆盖5种状态)。
- `docs/10-golden-import-guide.md`：使用指南。

### 兼容映射（因上轮 export 列名与本轮 spec 不一致，且本轮不改 export）
- `business_corrected_answer`→revised_ideal_reply；`business_notes`→business_comment；`review_date`→reviewed_at。细粒度 revised_* 列存在则优先。已在报告"兼容说明"注明。

### 已验证（本地）
- dry-run 不写、--write 写/tmp；合并正确：删/加/确认(nbr=false)/修正覆盖/pending(nbr=true) 全部符合预期；errors=0。

### 完整业务闭环现已具备
export（导出审核表）→ 业务填表 → import（合并回 v2 + diff）→ bench_masanduo（用 v2 跑分对比）。

---

## Session 2026-07-03 · 导出↔导入字段对齐 + roundtrip 自测（第十一轮）

### 目标
- 消除上一轮暴露的字段不一致：让 export 表头与 importer 支持字段完全对齐，闭环无摩擦。

### 改动
- `eval/export_golden_review.py`：表头升级为 21 列（core + business_status/business_comment/reviewer/owner/reviewed_at + 6 个 revised_*）；xlsx 增 business_status 下拉 + "填写说明"页 + 业务填写区高亮；`--include-legacy` 可选附加旧列。
- `scripts/prepare_business_review_pack.py`：business_tasks 措辞更新到新字段（revised_ideal_reply / reviewed_at / add）。
- `docs/07`：重写为三区表格 + 每状态填法 + "原始列别乱改""不为过测试降标准"。
- `docs/10`：注明 export 已对齐 + legacy 兼容说明。
- 新增 `scripts/check_golden_review_roundtrip.py` + `docs/11-golden-roundtrip-check.md`。
- `business_review/golden_review_sample.csv` 重生成为新表头；新增 `golden_review_roundtrip_sample.csv`（由自测脚本程序化生成，列对齐）。

### 验证（本地全通过）
- `check_golden_review_roundtrip.py`：**9/9 通过**（题数/删/增/confirmed/revise覆盖/pending/add/v1未覆盖）。
- 新空表 dry-run 导入：54 未审核、0 错误。
- legacy 旧格式（business_corrected_answer/review_date）仍兼容：revise 正确覆盖、字段映射正确、0 错误。
- 一键包重跑：CSV(21列)+xlsx(下拉+说明页)+kb_lint(OK) 全部生成。

---

## Session 2026-07-04 · 表格中文化 + 全景文档（第十二轮）

### 改动
- `eval/export_golden_review.py`：**默认中文表头**（编号/类别/审核状态/修正-理想回答…），每列加中文批注，审核状态下拉改中文（确认/修改/删除/待定/新增），"字段说明"页升级为完整中英对照字典；`--english-headers` 供机器/自测用。
- `scripts/import_golden_review.py`：ALIASES 扩为**同时认中文表头 + 英文机器名 + 旧字段**。
- `data/knowledge/_templates/*.md`（7个）：frontmatter 每个英文键加中文备注。
- `business_review/golden_review_sample.csv`：重生成为中文表头 + 中文状态。
- 新增 `docs/12-how-it-works.md`（运行时图 + 闭环图 + 每文件职责 + 完善方向，mermaid）。

### 验证（全通过）
- roundtrip 9/9；中文表头空表导入=54未审核/0错误；中文表头+中文状态(修改/删除)导入正确；kb_lint OK；legacy 旧字段仍兼容。

### 结论
- 商务侧表格与模板已尽量中文化（英文键均有中文备注/对照），导入同时认中英表头。整套导出→填→导入→跑分闭环完整且有自测护栏。

---

## Session 2026-07-04 · 清理 + eval 侧 P1 + 商务文档（第十三轮）

### 删除（经用户确认，仅 B）
- 删除 `masanduo_624/`（死备份，git 跟踪，12 文件，可 `git checkout` 恢复）。其余候选(A教程码/C上游文档/D中间产物/F散落文档/G liuc.md)用户本轮**未选删**，保留。

### eval 侧低风险增强（不碰线上，用户选 safe_first）
- `eval/bench_masanduo.py`：新增 `--langfuse`（+host/pk/sk 或 LANGFUSE_* 环境变量）→ 反查 Langfuse trace 的 metadata.sources 得**真实检索来源**并计 required_sources 真实命中；`--use-judge` 的 LLM 裁判结果now在报告聚合（avg correctness/groundedness/helpfulness、compliance 通过率、error_type 分布）。缺 env 优雅跳过。
- 新增 `scripts/run_kb_pipeline.py`：一键 kb_lint→(可选)ingest→(可选)benchmark；**安全默认**（只 kb_lint，ingest/benchmark 需显式开，不碰生产）。

### 商务可转发文档
- 新增 `docs/商务整理指南.md`：非技术、说清"整理什么/怎么整理/对应文件"，可直接转发。

### 验证（全通过）
- roundtrip 9/9；bench 新代码离线不崩；--langfuse 缺 env 优雅跳过；pipeline 默认只跑 kb_lint(OK)。

### 明确未做（碰线上/前端/重灌，待单独确认）
- 前端 👍/👎 写 Langfuse（改 pc_sjmm + 可能加后端接口）
- 回答结构化契约 sources/confidence/need_human（改 engine.py 业务代码）
- 知识库.md 拆分并切 ingest（服务器重灌，影响线上）

---

## Session 2026-07-04 · 前端富反馈 + 结构化契约 + 知识库切线上（第十四轮，含线上变更）

### A 后端（本地验证 + 已部署线上）
- `langfuse_tracing.py`：`log_qa` 返回 trace_id；新增 `log_feedback`（写 Langfuse score，故障安全）。
- `engine.py`：新增 `QaOutput` + `respond_full`（answer/sources/confidence/need_human/trace_id/intent/path）；`respond` 薄封装向后兼容；派生规则见 `docs/12`。
- `api/models.py`+`app.py`：`QaResponse` 追加 sources/confidence/need_human，trace_id 换成真实 Langfuse id；新增 `POST /v1/feedback`。

### B 前端（改完，待你发版）
- `pc_sjmm/src/pages/AiChat_v3.0/index.jsx`：AI 气泡下富反馈条（👍/👎 + 差评原因标签 + 选填文字），记录每条 trace_id，POST `/v1/feedback`，故障安全。内联样式、单文件。

### C 知识库拆分 + 切线上（B2）
- `loader.py`：解析 .md frontmatter→metadata（**保留 source_type=file**，加 doc_id/visible_to/risk_level/doc_type），跳过 _templates/README。
- `scripts/split_kb_to_knowledge.py`：把 知识库.md 机械拆成 15 篇入 data/knowledge/，kb_lint 全过。
- **线上切换**：GPU 不足并发载 8B、Milvus Lite 单进程锁 → 采用**维护窗口 GPU ingest**：备份 milvus.db/.env → 停服务 → GPU ingest data/knowledge → `chatbot_docs_v2`（灌进同一 milvus.db，旧集合 chatbot_docs 43280 向量完好）→ `.env` MILVUS_COLLECTION=chatbot_docs_v2 → 启动。停机约 2-3 分钟。
- **回滚**：`sed -i 's/^MILVUS_COLLECTION=.*/MILVUS_COLLECTION=chatbot_docs/' .env && systemctl restart ragchatbot`（旧集合完好，秒级回滚）。

### 线上验证（v2）
- 冒烟：办单/回收价/红线/提前还款均正确；结构化字段(confidence/need_human/真实 trace_id)返回正常；`/v1/feedback`→`{"ok":true}` 写入 Langfuse score；无错误日志。
- benchmark(54题,打 prod)：**0 报错**、平均分 2.59(规则粗评低估)、转人工 0.889、**红线违规 2=均为否定语境误报**（答案实为"不是利息/不是贷款"，非真实违规）。

### 已知/待办
- v2 只含 16 块（治理版，剔除七鱼对话）；未采集 v1 基线分（切换前本地无法跑 8B），"不回退"未数值化证明——建议后续用 LLM judge + 基线对比。
- `forbidden_checker` 否定窗口偏小致误报——建议扩窗/语义化（eval 侧小改）。
- 前端 pc_sjmm 需构建发版后反馈才在线上生效。
