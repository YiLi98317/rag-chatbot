# 10 · golden 回填导入指南

> 闭环最后一环：商务在表格里审完 golden → 本脚本把结果**合并回 golden**，生成 v2 + 差异报告。
> 低风险：默认 dry-run（只出报告不写文件）；只有 `--write` 才生成新 golden；**永不覆盖 v1**。

## 1. 解决什么问题

上一轮导出了 `business_review/golden_review.csv/xlsx` 给业务审核。业务填完后，需要有人把
"确认/修改/删除/待定/新增"合并回题库——手工改 jsonl 易错。本脚本自动做这件事，并出差异报告。

## 2. 商务怎么填 golden_review

在表里逐行处理，关键填 `business_status`（支持中英文）：

| business_status | 含义 | 还要填什么 |
|---|---|---|
| confirmed（确认/通过/正确） | 答案没问题 | reviewer、owner、review_date |
| revise（修改/修正） | 要改答案 | 把正确答案写进 `business_corrected_answer`（或 `revised_*` 列） |
| delete（删除/不要/作废） | 这题删掉 | business_notes 说明原因 |
| pending（待定/待确认） | 还不确定 | business_notes 写待确认点 |
| add（新增） | 加一条新题 | 新 id + question + category + role + expected_answer_points + 答案 |

> **表头已对齐**：`eval/export_golden_review.py` 现在原生导出 importer 支持的全部字段
> （含 `revised_*` 与 `business_comment/reviewer/owner/reviewed_at`），导出↔导入无摩擦。
> **legacy 兼容**：旧表的 `business_corrected_answer`→当作 `revised_ideal_reply`；
> `business_notes`→`business_comment`；`review_date`→`reviewed_at`。新表默认不含这些旧列
> （如需附加可 `export_golden_review.py --include-legacy`）。

## 3. dry-run（先预演，强烈建议先做）

```bash
python scripts/import_golden_review.py --input business_review/golden_review.csv
```
只生成报告 `business_review/golden_import_report_<时间戳>.md`，**不写** golden。先看报告有没有 P0 错误。

## 4. 正式生成 v2

```bash
python scripts/import_golden_review.py \
  --input business_review/golden_review.csv \
  --base-golden eval/golden_masanduo_v1.jsonl \
  --output eval/golden_masanduo_v2.jsonl \
  --write
```
- 有 P0 错误时**不会写入**（先修表）。
- 不会覆盖 v1；输出到 v2。

## 5. 怎么看差异报告

报告里有：统计（confirmed/revised/deleted/pending/added/未审核）、P0 错误、P1 警告、每条 revise 的字段级 diff、删除/待定/新增清单、下一步建议。

## 6. 校验规则

- **P0（阻止写入）**：id 空/重复、question/category/role/expected_answer_points/ideal_reply 空、status 无法识别、add 缺必要字段。
- **P1（仅警告）**：forbidden_terms/required_sources/reviewer/owner 空、仍 pending、高风险类别未定 must_handoff、ideal_reply 疑似含禁用词（可能是否定语境，需人工看）。

## 7. 常见错误

- **"该 id 不在 base golden 中"**：想新增请把 `business_status` 设成 `add`。
- **"add id 已存在"**：换个新 id（如 `xxx_new`）。
- **指定 xlsx 但没装 openpyxl**：改用 CSV，或 `pip install openpyxl`。
- **P0 未写入**：报告顶部会列出原因，修表后重跑。

## 8. 下一步跑 benchmark

```bash
python eval/bench_masanduo.py --golden eval/golden_masanduo_v2.jsonl --base-url http://localhost:8000
```
用 v2 重新跑分，和 v1 的报告对比，看业务修订后分数变化。
