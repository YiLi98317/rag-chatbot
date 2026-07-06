# 06 · MVP 评测体系（benchmark）

> 本轮（2026-07-03）新增的**第一版评测体系**，只在 `eval/` 与 `docs/` 内，不改任何线上业务代码。
> 目的：用可重复、可对比的方式衡量马三多回答质量，发现**知识库/路由/提示词/红线/检索**的问题，反过来改系统。

## 组成

| 文件 | 作用 |
|---|---|
| `eval/golden_masanduo_v1.jsonl` | 业务 golden 数据集（50 题，10 类）。**评测草案，非最终业务规则**。 |
| `eval/forbidden_checker.py` | 禁用词/红线检查（否定感知，避免误杀"不是利息"这类合规提醒）。 |
| `eval/bench_masanduo.py` | runner：调 `/v1/qa` → 规则评分 → 出 JSON+MD 报告。 |
| `eval/judge_prompt.md` | LLM-as-judge 提示词模板（维度：correctness/groundedness/compliance/handoff/helpfulness/error_type）。 |
| `eval/judge.py` | 可选 LLM 裁判封装（默认不启用；`--use-judge` 时用现有 DeepSeek）。 |
| `eval/reports/` | 运行产物：`masanduo_benchmark_<ts>.json` + `.md`。 |

## 如何运行

```bash
# 本地（推荐先起本地 API：make api）
python eval/bench_masanduo.py \
  --golden eval/golden_masanduo_v1.jsonl \
  --base-url http://localhost:8000 \
  --output-dir eval/reports

# 只跑前 10 题快速试
python eval/bench_masanduo.py --limit 10

# 开启 LLM 裁判（需 .env 配好 LLM、PYTHONPATH=src）
PYTHONPATH=src python eval/bench_masanduo.py --use-judge
```

- **默认打 `localhost:8000`**，绝不默认打生产。检测到生产 IP/域名会拒绝，除非显式 `--allow-prod`。
- 每条请求 `session_id=bench_<id>`、`channel=benchmark`，方便在 Langfuse 里按此过滤这批评测流量。

## MVP 上线门槛（硬指标）

达不到下列门槛**不上线灰度**：

- 🔴 **红线/禁用词违规次数 = 0**
- 🔴 **禁止词检查通过率 = 100%**
- 🟠 **高频题平均分 ≥ 4/5**
- 🟠 **required answer points 平均命中率 ≥ 80%**
- 🟠 **must_handoff 准确率 ≥ 95%**
- 🟡 服务费/监管锁/风控/合规类问题必须**偏保守**（宁可转人工，不乱承诺）
- 🟡 没有知识库依据的问题**必须转人工或明确说无法确认**，不得编造费率/政策

## 重要局限（第一版，务必知悉）

1. **规则评分是"粗评"**：`rough_score` 用关键词/字符重叠代理"要点命中"，只适合**相对对比**（改动前后谁高谁低），不代表绝对质量。权威判断请用 `--use-judge` 或 Langfuse 人工评分。
2. **required_sources 是弱代理**：`/v1/qa` 响应不含检索来源（sources 只进 Langfuse）。runner 目前只检查"关键词是否出现在答案里"。要精确判断"检索命中"，需后续用 `session_id` 反查 Langfuse trace 的 `metadata.sources`。
3. **forbidden 否定判断有限**：基于"禁用词前若干字是否有否定词"，复杂句式可能漏/误判。红线项宁可保守，最终以人工/LLM 复核为准。
4. **must_handoff 检测靠措辞关键词**：常规"联系客服办理"可能被误判为转人工。低风险，但看报告时注意。
5. **golden 是草案**：`needs_business_review: true` 的题目需业务方确认后才能作为正式基准；涉及费率/价格的题目答案刻意写成"以系统/平台为准"，不锁死具体数字。

## 反馈闭环（怎么用它改系统）

```
跑 benchmark → 看报告(最差10/红线失败/低分类别)
  → 定位问题类型：
      要点没命中 & sources 没召回  → 知识库缺内容 / chunk / 检索问题
      召回了但答错                → 提示词/模型遵循问题(polish)
      红线该拦没拦                → router / replies 红线问题
      该转人工没转                → 增加兜底/转人工判定
  → 改（知识库 / 提示词 / 路由 / 红线词表）
  → 重新 ingest（若改了知识库）→ 重跑 benchmark 对比分数
  → Langfuse 人工/LLM 复核最差题
```
