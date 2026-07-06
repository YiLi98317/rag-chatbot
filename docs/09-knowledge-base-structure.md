# 09 · 知识库结构与写法

> 给要写/整理知识库的人。目标：结构统一、可按角色过滤、可版本回溯、可评测。

## 1. 推荐目录结构

```text
data/knowledge/
  _templates/            # 模板（复制它来写新知识，不参与检查/ingest）
  01_rules/              # 平台规则 / 费率 / 结算
  02_sop/                # 办单 / 锁机 / 审核 等操作流程
  03_sales_scripts/      # 销售话术
  04_redlines/           # 红线与禁用话术
  05_faq/                # 标准问答（已放示例 faq_service_fee.md）
  06_product_params/     # 机型参数卖点
  07_qiyu_extracted/     # 从七鱼记录“提炼”的标准答案（非原始聊天）
  08_system_operations/  # 系统页面操作（可含页面跳转）
  09_after_sales/        # 售后 / 质保 / 丢失 / 逾期
  10_pricing_and_fee/    # 定价与费用
  99_archive/            # 历史/教程/归档（不进正式检索）
```

> 说明：当前线上实际 ingest 的仍是历史单文件 `data/target/知识库.md`。本结构是**目标治理结构**，迁移与 ingest 切换由技术侧统一安排；本目录只新增、不影响线上。

## 2. 每类文档怎么写
- 从 `_templates/` 复制对应模板（rule/sop/sales_script/redline/faq/after_sales/system_operation）。
- 一篇只讲一个主题，别把十件事塞一篇。
- 涉及费用/费率/通过率：写"以系统页面/平台规则为准"，不要写死会变的数字。

## 3. frontmatter 字段说明（每篇必带）

```yaml
---
doc_id:            # 全局唯一，如 faq-fee-001
title:             # 一句话标题
category:          # 目录类别，如 05_faq
visible_to:        # 谁能看到：[加盟商, 店员, 客服, 业务员, 管理员]（至少一个）
risk_level:        # low | medium | high（涉费用/风控/承诺/红线=high）
owner:             # 业务负责人（必填）
reviewer:          # 审核人（建议填）
version:           # 如 2026-07
effective_from:    # 生效日期 YYYY-MM-DD（必填）
effective_to:      # 失效日期，长期有效留空
source_type:       # rule|sop|sales_script|redline|faq|after_sales|system_operation
---
```

必填：`doc_id, title, category, visible_to, risk_level, owner, version, effective_from, source_type`。
写完运行 `python scripts/kb_lint.py` 自检，报告在 `business_review/kb_lint_report.md`。

## 4. 七鱼原始记录为什么不能直接进正式库
- 七鱼是客服真实聊天记录，里面**混着闲聊、情绪化表达、错误答案、临时口径**。
- 直接进库会被 AI 检索到，导致它学/引用错误答案。
- 正确做法：从七鱼里**提炼**出标准答案，整理成 `05_faq` / `03_sales_scripts` 放进 `07_qiyu_extracted`，原始记录只做参考、不进正式检索。

## 5. 知识库修改后的标准流程

```text
改知识库 → 业务审核 → kb_lint（结构检查） → ingest（技术，先本地）
  → smoke test（问几条真实问句） → benchmark（跑分对比） → Langfuse 复核（人工/LLM）
```

⚠️ 关键约束：**更换 embedding 模型必须重新 ingest 全部知识库**（向量与模型绑定）。所以短期不要换 embedding。

## 6. 迁移记录（2026-07-04）

- `scripts/split_kb_to_knowledge.py`：把历史单文件 `data/target/知识库.md` 按 `##` 机械拆进 `data/knowledge/`（15 篇，带 frontmatter 草稿，owner/reviewer=待业务确认）。可复用。
- `loader.py` 已支持解析 `.md` frontmatter → metadata（**保留 `source_type=file` 以免打断检索的 KB 优先过滤**；额外加 `doc_id/title/visible_to/risk_level/doc_type`）；并跳过 `_templates/` 与 `README.md`。
- 线上切换采用**独立 Milvus Lite 文件**方案：ingest 到 `milvus_v2.db`（不与线上 `milvus.db` 争单进程锁），切换只改 `.env` 的 `MILVUS_LITE_DB` 一行 + 重启，回滚=改回一行（旧 `milvus.db` 完好）。
- ⚠️ Milvus Lite 是单进程文件锁：服务运行时无法对同一 db 文件并发 ingest，故用独立文件；GPU 显存不足以并发再载 8B embedding，故 ingest 走 CPU。
