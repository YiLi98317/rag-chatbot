# 07 · golden 题库审核指南（给业务团队）

> 面向不懂代码的商务/客服/业务员。你只需要在表格里填字，把"AI 该怎么答"的正确口径告诉我们。
> 表格由技术生成（`business_review/golden_review.xlsx`，推荐用 Excel 打开，`business_status` 是下拉框，另有"填写说明"页）。

## 这是什么

golden 是一套"标准考题"：每题一个真实问题 + 我们认为正确的标准答案。
我们用它定期给 AI（马三多）打分，看它答得对不对、有没有说错话。
**你们的任务：审核这些标准答案对不对**——标准由业务定，不是技术拍脑袋。

## 表格分三区

| 区域 | 列 | 谁填 |
|---|---|---|
| 原始题（技术产出） | id, category, role, question, expected_answer_points, required_sources, forbidden_terms, must_handoff, ideal_reply, needs_business_review | 技术已填，**你别改这些原始列** |
| 审核区 | business_status, business_comment, reviewer, owner, reviewed_at | **你填** |
| 修正区 revised_* | revised_question, revised_expected_answer_points, revised_required_sources, revised_forbidden_terms, revised_must_handoff, revised_ideal_reply | **只有要改时才填** |

> 原始列（expected_answer_points 等）请**不要直接改**；要改就填到对应的 `revised_*` 列，方便留痕对比。

## business_status 怎么填（每种状态）

Excel 里直接下拉选。支持中文：确认/通过/正确、修改/修正、删除/作废、待定/待确认、新增。

### confirmed（确认无误）
- 只填：`business_status=confirmed`、`reviewer`、`reviewed_at`；`business_comment` 可选。
- **不要动 revised_***。

### revise（需要修改）
- **必须至少填一个 `revised_*`**：
  - 只改理想回答 → `revised_ideal_reply`
  - 改标准答案要点 → `revised_expected_answer_points`（多点用换行或顿号分隔）
  - 改禁用词 → `revised_forbidden_terms`
  - 改是否转人工 → `revised_must_handoff`（是/否）
- 填 `reviewer`、`reviewed_at`；`business_comment` 说明改了啥。

### delete（删除该题）
- `business_status=delete` + `business_comment` 写删除理由。

### pending（继续待定）
- `business_status=pending` + `business_comment` 写卡在哪里、需要谁确认。

### add（新增题）
- 给一个**新的、唯一的 id**（如 `fee_101`）+ `category` + `role` + `question`
- 答案：`revised_expected_answer_points`（或 `expected_answer_points`）+ `revised_ideal_reply`（或 `ideal_reply`）
- `business_status=add`

## 优先审哪些
1. `needs_business_review = 是` 的题（技术拿不准，最需要你）。
2. `category` 是"红线/合规""服务费/费用""审核失败""监管锁"的题（错了=事故）。
3. `must_handoff = 是` 的题（确认这些确实该转人工）。

## 原则（重要）
- **涉费用/风控/监管锁/红线：宁可保守**。拿不准写"以系统页面/平台规则为准"，或标 `pending`。
- 不要写死会变的具体费率/通过率，也不能对客户承诺"一定通过/一定发货"。
- **不要为了让 AI 通过测试而降低标准**——标准答案要以真实合规口径为准，考的是 AI，不是放水。

## legacy（旧字段兼容，了解即可）
旧表里的 `business_corrected_answer / business_notes / review_date` 仍能被导入，但**新表推荐用** `revised_ideal_reply / business_comment / reviewed_at`。

## 审核完怎么回给技术
把填好的 `golden_review.csv/xlsx` 发回。技术用 `scripts/import_golden_review.py` 合并生成 v2 并出差异报告（见 `docs/10`）。
