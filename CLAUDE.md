# CLAUDE.md — 面向 Claude / Claude Code 的长期项目规则

## 每次 session 开始，先按顺序读这些文件

1. `AGENTS.md` —— 全局硬性规则（禁止事项、工作方式）。**最高优先级。**
2. `docs/99-session-log.md` —— 上一轮做了什么、确认了什么、下一步建议。
3. `docs/04-known-problems.md` —— 已知风险和坑。
4. 与当前任务相关的 `tasks/TASK-*.md`。

读完后，用一两句话向用户复述你对「当前状态 + 本轮目标」的理解，再开始动手。

## 本仓库的特殊约定

- 这是 legacy 仓库，默认**只读优先**。改业务代码前必须先给计划、等用户确认（见 `AGENTS.md` 第 2 节）。
- 不要一次性大改。不要重构。不要升级依赖。不要碰部署/密钥/数据库。
- 区分**确定**与**推测**：凡是你没有在文件里亲眼读到的，标注「推测/待确认」，不要编造。

## 结束 session 时

在 `docs/99-session-log.md` 追加一段（不要覆盖历史），记录：

- 本轮目标
- 读了哪些文件、确认了什么
- 还不确定什么
- 创建/修改了哪些文件
- 下一步建议

## 常用定位（省得每次重新摸索）

- 服务入口：`api/app.py`（FastAPI，`/v1/qa` 走 masanduo 引擎）。
- 核心 RAG：`src/chatbot/service/qa_service.py`、`src/chatbot/rag/pipeline.py`、`src/chatbot/retrieval/`。
- 马三多工作流：`src/chatbot/masanduo/`（`engine.py` 是编排入口）。
- 配置读取：`src/chatbot/settings.py`（读 `.env`）。
- 评测：`eval/`（目前只有检索指标，缺 golden set，见 known-problems）。
