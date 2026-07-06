# 业务协作任务清单（给商务/客服/业务员）

> 目标：把"AI 答得对不对、说得合不合规"这件事，交给最懂业务的人来把关。
> 你们**不需要写代码**，只需要在表格和文档里提供正确的业务口径。

## 一、各角色要做什么

### 商务负责人
- 确认加盟商入驻、返点、提现、结算等规则口径。
- 审核 `golden_review` 里"红线/合规""服务费/费用""回收价/租机测算"类题目的标准答案。

### 客服主管
- 确认办单、审核、锁机、售后、质保、逾期等 SOP 的标准答案。
- 负责 `04_redlines`（红线）和"必须转人工"的判断口径。

### 业务员/店长（一线）
- 提供**真实高频问题**：客户/加盟商实际会怎么问（越口语越好）。
- 提供好用的**销售话术**原话（哪些说了有效、哪些说了出过问题）。

### 运营
- 提供活动政策、费用政策的**生效/失效时间**。
- 维护"禁用话术清单"（对外统一术语、不能说的表达）。

## 二、golden 题库怎么审核（重点）

1. 打开 `business_review/golden_review.csv`（或 .xlsx）。
2. 逐行看 `question` + `ideal_reply` + `expected_answer_points`。
3. 在 `business_status` 填（Excel 里是下拉框）：
   - `confirmed` 答案正确，可作为标准
   - `revise` 需要改（把正确答案写进 `revised_ideal_reply`；要改要点填 `revised_expected_answer_points` 等）
   - `pending` 暂不确定 / 需要开会定
   - `delete` 这题不合适，删掉
   - `add` 新增一题（给新 id + 问题 + 答案）
4. `needs_business_review = 是` 的题**优先处理**（这些是技术侧拿不准的）。
5. 填上 `owner`（谁负责这条业务）、`reviewer`（谁审的）、`reviewed_at`（审核日期）。
6. 涉及费用/风控/监管锁/红线的，**宁可保守**：拿不准就写"以系统页面/平台规则为准"或标 `pending`。

## 三、知识库怎么整理

1. 从 `data/knowledge/_templates/` 复制对应模板。
2. 按模板填写，务必填 frontmatter（doc_id、owner、visible_to、risk_level、version、生效日期）。
3. 一篇写完，技术侧会跑 `kb_lint` 检查结构（见 `kb_lint_report.md`）。
4. **不要把七鱼原始聊天记录直接粘进来**——要提炼成"标准答案"。

## 四、Langfuse 质检（简版）

- Langfuse 是我们的"AI 问答记录 + 打分后台"，能看到每次真实问答。
- 你们主要做两件事：
  1. 在 **Annotation / Scores** 里给回答打分（对不对、合不合规）。
  2. 看到答错的，记下来 → 变成知识库要补的内容或 golden 里的新题。
- 界面是英文，可用浏览器"翻译成中文"或"沉浸式翻译"插件；详细看 `docs/08-business-collaboration.md`。

## 五、截止时间建议（可按实际调整）

- 第 1-2 天：业务员/店长汇总真实高频问题（目标 ≥ 50 条）。
- 第 3-4 天：商务+客服审完 golden 里 `needs_business_review` 的题。
- 第 5 天：运营给出禁用话术清单 + 活动政策生效时间。
- 第 6-7 天：客服主管在 Langfuse 试打分 10-20 条真实问答。
