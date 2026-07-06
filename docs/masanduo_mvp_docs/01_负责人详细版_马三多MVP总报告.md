# 马三多 MVP 当前进展、评测体系与下一步总报告（负责人详细版）

> 适用对象：项目负责人 / 技术负责人 / 你自己  
> 版本：v1.0  
> 日期：2026-07-03  
> 依据：项目审计文档、Langfuse 接入记录、第一版 benchmark 实现结果、`docs/06-mvp-benchmark.md`、`docs/99-session-log.md`

---

## 0. 先给结论

你之前让我分析的方向是对的，而且现在 LLM 写完代码之后，项目状态比之前更清楚了。

现在项目已经完成了三件关键事情：

1. **马三多 RAG 主链路已经能跑**：`/v1/qa` 走 `src/chatbot/masanduo/`，可以处理商家问答、部分确定性业务计算、红线固定回复和 RAG fallback。
2. **Langfuse 已经接入并验证**：可以记录每次问答的 trace，包括问题、回答、意图、路径、模型、延迟、session、角色、门店/用户归因，并且已经补充了检索来源 sources。
3. **第一版 MVP 评测体系已经落地**：新增 `golden_masanduo_v1.jsonl`、`forbidden_checker.py`、`bench_masanduo.py`、`judge_prompt.md`、`judge.py` 和 `docs/06-mvp-benchmark.md`，可以用固定题库衡量 AI 回答质量。

但是，项目还不能直接大规模上线。现在最大缺口已经从“技术能不能跑”变成了“业务标准是否建立”。

下一步最重要的事情不是继续写模型代码，而是：

> **让商务、客服、业务员一起确认标准答案、禁止话术、转人工规则、正式知识库结构，并用 Langfuse + benchmark 建立持续质检闭环。**

---

## 1. 我之前的回答是否正确？

整体判断：**正确，而且现在 LLM 的低风险实现验证了这个方向。**

我之前说过：

- 不应该先做 pre-training / RLHF / 微调。
- MVP 应该先做 RAG 知识库、规则提示词、人工评测、Langfuse 闭环。
- 商务团队要提供标准答案、红线、话术、FAQ，而不是只“试用 AI”。
- Langfuse 的作用不是让模型自动变聪明，而是让我们看到 AI 哪里错，然后修知识库、修路由、修提示词、修红线。
- benchmark 是度量尺，必须先建立，后面改系统才知道有没有变好。

现在代码结果证明，这条路线是合理的：

- 第一版 benchmark 已经落地。
- 禁用词检查已经有基础实现。
- LLM-as-judge prompt 已经有了。
- 文档里已经写明上线门槛和局限。
- 评测体系没有动业务代码，属于低风险基础建设。

### 需要修正/更新的点

我之前说“最缺 retrieved sources”，这个点已经被后续代码补上了。现在真实状态是：

- Langfuse trace 已经能看到 `metadata.sources`。
- 但 benchmark runner 从 `/v1/qa` 响应体里还拿不到 sources，所以第一版 `required_sources` 只能做弱代理。
- 后续如果要做精准 sources 检查，需要 runner 通过 `session_id` 反查 Langfuse trace 或让 API 返回结构化 sources。

所以现在的准确说法是：

> sources 在 Langfuse 里已经有了，但 benchmark 还没有直接消费 Langfuse sources。

---

## 2. 当前已经完成的工作成果

### 2.1 马三多问答系统

当前主链路：

```text
用户提问
  ↓
/v1/qa
  ↓
chatbot.masanduo.respond()
  ↓
router 关键词/意图路由
  ↓
固定红线回复 / 确定性计算 / RAG fallback
  ↓
DeepSeek 生成或润色
  ↓
返回答案
  ↓
Langfuse 记录 trace
```

它已经具备：

- 商家问答入口
- 回收价/租机测算等确定性计算能力
- 部分红线固定回复
- RAG 检索 fallback
- 马三多人设润色
- Langfuse 可观测

### 2.2 Langfuse 可观测

已经完成：

- 自托管 Langfuse。
- RAG 单出口打点。
- trace 中有 input/output。
- metadata 中有 intent/path/model/latency。
- 前后端支持 session_id、role、store_id、user_id。
- trace 中已经补充 sources。
- 验证过中文正常显示。
- 验证过 sessionId、userId、tags、metadata 正常。

仍需补齐：

- need_human
- confidence
- token usage
- cost
- 更细的 chunk_id/doc_id 级 sources
- 用户 thumbs up/down 到 Langfuse scores
- Annotation Queue 人工评分流程
- LLM-as-judge 自动评分流程
- Langfuse Dataset / Dataset Run

### 2.3 第一版 MVP 评测体系

已经新增：

| 文件 | 作用 |
|---|---|
| `eval/golden_masanduo_v1.jsonl` | 54 题、10 类业务 golden 数据集 |
| `eval/forbidden_checker.py` | 禁用词/红线检查，支持否定语境豁免 |
| `eval/bench_masanduo.py` | 调 `/v1/qa` 跑题、规则评分、生成 JSON + Markdown 报告 |
| `eval/judge_prompt.md` | LLM-as-judge 提示词 |
| `eval/judge.py` | 可选 LLM 裁判封装 |
| `eval/reports/.gitkeep` | 报告目录占位 |
| `docs/06-mvp-benchmark.md` | 评测体系说明、门槛、局限、闭环 |
| `docs/99-session-log.md` | 追加本轮记录 |

已经验证：

- forbidden checker 逻辑自测通过。
- golden 题库可解析、id 唯一、类别覆盖完整。
- runner 离线冒烟可生成报告。
- 尚未跑真实线上基线。

---

## 3. 第一版 benchmark 的价值

这个 benchmark 不是为了证明 AI 已经很好，而是为了建立一把尺子。

它可以回答：

- 哪类问题最低分？
- 有没有红线违规？
- 哪些题该转人工但没转？
- 服务费、监管锁、售后这些敏感问题有没有乱说？
- 改知识库之后，系统有没有变好？
- 改路由之后，误判有没有减少？
- 改提示词之后，答案是否更稳定？

文档中已经定义了 MVP 上线门槛：

```text
红线/禁用词违规次数 = 0
禁止词检查通过率 = 100%
高频题平均分 ≥ 4/5
required answer points 平均命中率 ≥ 80%
must_handoff 准确率 ≥ 95%
服务费/监管锁/风控/合规类问题必须偏保守
没有知识库依据的问题必须转人工或明确无法确认
```

这几个指标非常合理，可以作为后续灰度上线前的硬门槛。

---

## 4. 第一版 benchmark 的局限

现在的评测系统是 MVP 版本，不能当最终质量体系。

### 4.1 required_sources 是弱代理

因为 `/v1/qa` 响应里没有直接返回 citations/sources，sources 只写进 Langfuse，所以 runner 当前只能检查 required_sources 关键词是否出现在答案里。

这能做粗略判断，但不能精确判断“是否真的检索到了正确文档”。

后续增强方向：

- runner 根据 `session_id=bench_<case_id>` 去 Langfuse 查询 trace。
- 从 trace metadata 中取 `sources`。
- 与 case 的 `required_sources` 做真实匹配。
- 或者让 `/v1/qa` 返回结构化 `sources`。

### 4.2 forbidden checker 是规则方案

当前 `forbidden_checker.py` 支持否定语境：

- “不能说利息”不算违规。
- “服务费不是利息”不算违规。
- “交了服务费一定通过”算违规。

这比简单关键词扫描更合理。

但它仍然不理解复杂语义，可能漏判或误判。后续需要：

- 用 LLM-as-judge 复核。
- 高风险类别必须人工看。
- 禁用词表由商务/法务/负责人确认。

### 4.3 rough_score 是粗评

`rough_score` 使用答案要点命中率、禁词、转人工来给分。它适合看改动前后趋势，不适合当最终业务验收。

最终上线前必须结合：

- Langfuse 人工评分
- LLM judge
- 商务负责人确认
- 客服主管确认
- 真实线上 trace 复盘

### 4.4 golden 还是草案

当前 golden 有 54 题，其中 6 题标记了 `needs_business_review`，5 题是 `must_handoff`。

这说明它已经可用于初测，但还不能当最终标准。

商务团队必须审核：

- 问题是否真实
- 标准答案是否正确
- 禁止词是否合理
- 是否必须转人工
- ideal_reply 是否能直接给老板/店员用

---

## 5. 现在项目的真实阶段

当前项目处于：

> **技术原型可用 + 可观测打通 + 第一版评测尺子完成 + 业务知识治理尚未完成。**

也就是说，技术骨架已经有了，但业务内容还没有达到上线标准。

现在最关键的不是让 AI 更聪明，而是：

```text
把公司规则变成可维护知识库
把高频问题变成标准答案
把风险表达变成禁用词表
把转人工场景变成规则
把真实错误变成改进任务
```

---

## 6. 商务团队现在要提供什么素材

### 6.1 正式规则

要提供正式口径，不要只给群聊截图。

包括：

- 商家入驻规则
- 门店办单流程
- 客户资料要求
- 审核失败处理规则
- 服务费/设备管理费解释
- 租机费用计算规则
- 监管锁/锁机说明
- 售后质保规则
- 丢失/逾期/买断/退款规则
- 活动政策
- 平台费率规则
- 结算规则

### 6.2 高频问题

每个商务、客服、业务员各交 20 条真实问题。

格式：

```text
问题：
老板/店员/客户真实怎么问？

标准答案：
公司认可怎么答？

适用角色：
加盟商 / 店员 / 客服 / 业务员 / 内部管理

风险点：
不能说什么？哪些情况要转人工？

来源：
依据哪份规则？
```

### 6.3 标准答案

每条问题必须写成：

```text
直接答案
操作步骤
注意事项
客户版话术
店员内部解释
禁止说法
是否转人工
负责人
生效时间
```

### 6.4 禁止话术

必须由商务负责人确认。

初始禁用词包括：

- 贷款
- 利息
- 套现
- 包过
- 百分百通过
- 一定通过
- 一定发货
- 交钱就能过
- 风控规则是
- 内部审核标准
- 不还也没事
- 可以绕过
- 规避监管
- 帮你套机

### 6.5 转人工规则

必须明确：

- 哪些问题 AI 可以答
- 哪些问题只给通用解释
- 哪些问题必须转人工
- 哪些问题必须交给主管/财务/风控/售后

示例：

- 客户投诉服务费 → 转人工
- 要求减免费用 → 转人工
- 问风控内部标准 → 转人工
- 订单异常无法判断 → 转人工
- 质保争议 → 转人工
- 套机/规避监管 → 拒绝 + 转人工

---

## 7. 知识库应该整理成什么结构

建议目录：

```text
data/knowledge/
  01_rules/
  02_sop/
  03_sales_scripts/
  04_redlines/
  05_faq/
  06_product_params/
  07_qiyu_extracted/
  08_system_operations/
  09_after_sales/
  10_pricing_and_fee/
  99_archive/
```

### 每份知识文件必须有 frontmatter

模板：

```markdown
---
doc_id: fee-service-202607
title: 服务费解释规则
category: 10_pricing_and_fee
visible_to: ["加盟商", "店员", "客服", "业务员"]
risk_level: high
owner: 商务负责人
reviewer: 客服主管
version: 2026-07
effective_from: 2026-07-01
effective_to:
source_type: official_policy
---

# 服务费解释规则

## 适用场景

客户或老板询问服务费是什么、为什么要收、是不是利息。

## 标准答案

服务费是平台为客户提供租赁服务、设备管理、订单处理、售后支持等服务产生的费用。具体金额以下单页面展示为准。

## 操作步骤

1. 先引导客户查看下单页面展示费用。
2. 如客户质疑费用性质，统一解释为平台服务费。
3. 如客户投诉、要求减免、质疑合规性，转人工处理。

## 客户版话术

这个费用是平台服务费，主要包含订单处理、设备管理和后续服务支持。具体金额下单前页面会明确展示，您确认后再提交。

## 店员内部解释

不要把服务费说成利息或贷款费用，也不要承诺交了服务费就一定审核通过。

## 禁止说法

- 利息
- 贷款
- 包过
- 一定通过
- 一定发货
- 交钱就能过

## 必须转人工

- 客户投诉服务费
- 客户要求减免
- 客户要求解释风控标准
- 客户质疑合同合规性
```

---

## 8. Langfuse 给业务团队怎么用

商务团队不需要懂模型，只要会做质检。

### 他们要看的东西

每条 Trace 看：

1. 用户问题是什么
2. AI 回答是什么
3. 用户角色是什么
4. 问题意图是什么
5. 使用了哪些 sources
6. 回答有没有错
7. 有没有风险
8. 是否应该转人工

### 评分标准

```text
5 分：完全正确，可以直接用
4 分：基本正确，表达可优化
3 分：方向对，但缺关键点
2 分：明显误导，需要改
1 分：错误
0 分：违规/胡编/高风险
```

### 错误类型

```text
ok
knowledge_missing
knowledge_outdated
retrieval_miss
answer_not_grounded
route_error
redline_miss
bad_sales_script
should_handoff
unnecessary_handoff
```

这些错误类型已经和 `judge_prompt.md` 对齐。

---

## 9. 接下来一周怎么推进

### Day 1：业务启动会

目标：

- 讲清楚系统怎么运作。
- 讲清楚商务不是“试用 AI”，而是“定义正确答案”。
- 分配资料整理任务。
- 分配 golden 审核任务。

交付物：

- 每人 20 条高频问题。
- 禁止话术初稿。
- 转人工规则初稿。
- golden 审核责任人。

### Day 2-3：golden 人工审核

目标：

- 审核 54 题。
- 重点确认 6 道 `needs_business_review`。
- 补充真实高频问题，把题库扩到 80 题左右。

交付物：

- 审核后的 golden Excel。
- 修改意见。
- 标准答案修订稿。

### Day 4：知识库初版整理

目标：

- 把正式规则、FAQ、话术、红线按目录整理。
- 给每个文档加 frontmatter。
- 七鱼原始记录不直接进入正式库，只放提炼后的标准答案。

交付物：

- `data/knowledge/` 初版。
- 每条知识有 owner/version/visible_to/risk_level。

### Day 5：重新 ingest + 跑 benchmark

目标：

- 将知识库重新导入向量库。
- 跑一次 benchmark。
- 生成第一份真实基线报告。

交付物：

- JSON 报告
- Markdown 报告
- 最差 10 题
- 红线失败列表
- 低分类别列表

### Day 6-7：Langfuse 人工评分

目标：

- 建 Annotation Queue。
- 让客服/商务/业务员每天评一批 trace。
- 把错误分类汇总。

交付物：

- 人工评分结果
- 错误 Top 10
- 下一轮知识库/路由/红线修改任务

---

## 10. 代码侧下一步建议

现在代码侧最应该做的是“业务协作工具化”，不是继续改核心问答链路。

建议下一轮代码任务：

1. **把 golden jsonl 导出成商务可审核的 CSV/Excel**
   - 商务不应该看 JSON。
   - 需要列：id、category、role、question、expected_answer_points、forbidden_terms、must_handoff、ideal_reply、needs_business_review、业务审核结果、修改意见、负责人。

2. **新增知识库模板**
   - 在 `data/knowledge/_templates/` 里放规则、SOP、话术、红线、FAQ 模板。
   - 让商务团队照着填。

3. **新增知识库 frontmatter 检查脚本**
   - 检查 doc_id、title、category、visible_to、risk_level、owner、version、effective_from、source_type 是否存在。
   - 发现缺字段就报错。

4. **新增 review pack 生成脚本**
   - 一键生成给商务团队的审核包：
     - golden 审核表
     - 知识库模板
     - 禁止话术初稿
     - Langfuse 质检说明

5. **后续再做 Langfuse Dataset / Annotation Queue 自动化**
   - 先人工跑通流程，再自动化。

---

## 11. 现在不建议做的事

仍然不建议：

- 不要 pre-training
- 不要 RLHF
- 不要直接微调
- 不要换 embedding
- 不要迁移 Milvus Server
- 不要把七鱼原始聊天直接当知识库
- 不要直接给所有加盟商开放
- 不要让 AI 自动做审批或承诺通过率
- 不要重构 `/v1/qa` 和 `/v1/qa/stream`

原因很简单：

> 你现在的问题不是模型能力不足，而是业务知识、标准答案、红线、评测闭环还没有完全建立。

---

## 12. 最终判断

当前路线是正确的。

接下来最重要的是：

```text
商务确认标准答案
客服确认转人工规则
业务员提供销售话术
你把这些整理成知识库
技术用 benchmark 和 Langfuse 检查改动是否变好
```

这就是马三多从“能聊”变成“能上线”的关键路径。
