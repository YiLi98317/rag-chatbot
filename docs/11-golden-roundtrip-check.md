# 11 · golden 导出↔导入闭环自测（roundtrip）

> 一条命令验证"导出表头 ↔ 导入逻辑"对齐，且 5 种审核状态都被正确处理。改了 export/import 后建议先跑它。

## 一键自测

```bash
python scripts/check_golden_review_roundtrip.py
```

它会：
1. 用与 importer 对齐的表头，程序化生成 `business_review/golden_review_roundtrip_sample.csv`（含 confirmed/revise/delete/pending/add 5 行，列一定对齐）。
2. 跑 import 的 dry-run（断言不写 v2）。
3. 跑 import 的 `--write`，在临时目录生成 v2。
4. 断言并打印每项结果。

## 预期结果

```
ROUNDTRIP: 9/9 通过
```

逐项含义：
- 题数变化正确（-1 删 +1 增 = 原数）
- delete 的题不在 v2
- add 的题在 v2
- confirmed 后 `needs_business_review=false`
- revise 覆盖了 `ideal_reply`
- revise 后 `needs_business_review=false`
- pending 保持 `needs_business_review=true`
- add 默认 `needs_business_review=true`
- v1 未被覆盖（题数不变）

## 失败怎么排查
- **题数不对/字段没覆盖**：多半是 export 表头与 importer 别名不一致 → 检查 `export_golden_review.py` 的 `columns()` 与 `import_golden_review.py` 的 `ALIASES`。
- **dry-run 却写了 v2**：检查 importer 的 `--write` 判定。
- **v1 被改**：检查 importer 的"拒绝覆盖 base golden"分支。
- 退出码非 0 表示有断言失败，看控制台 ✗ 项。
