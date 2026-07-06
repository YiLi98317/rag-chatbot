# data/knowledge/ — 正式知识库

这是**给业务团队维护**的正式知识库目录。每篇文档都要带 frontmatter 元数据，并通过 `scripts/kb_lint.py` 校验。

> 注意：当前线上 RAG 实际 ingest 的是 `data/target/知识库.md`（历史单文件）。迁移与 ingest 切换需技术侧统一安排（见 `docs/09-knowledge-base-structure.md`）。

## 目录结构

```
data/knowledge/
  _templates/          # 各类文档模板（写新知识时复制它）
  01_rules/            # 平台规则 / 费率 / 结算
  02_sop/              # 办单 / 锁机 / 审核等操作流程
  03_sales_scripts/    # 销售话术
  04_redlines/         # 红线与禁用话术
  05_faq/              # 标准问答（已放示例 faq_service_fee.md）
  06_product_params/   # 机型参数卖点
  07_qiyu_extracted/   # 从七鱼记录“提炼”的标准答案（非原始聊天）
  08_system_operations/# 系统页面操作
  09_after_sales/      # 售后 / 质保 / 丢失 / 逾期
  10_pricing_and_fee/  # 定价与费用
  99_archive/          # 历史/教程/归档
```

## 怎么写一篇新知识文档
1. 从 `_templates/` 复制对应模板到目标类别目录。
2. 填 frontmatter（doc_id 唯一、owner、visible_to、risk_level、version、effective_from 必填）。
3. 按模板正文结构填内容，涉费用/风控/红线的写保守、以系统为准。
4. 运行 `python scripts/kb_lint.py` 自检通过。

详见 `docs/09-knowledge-base-structure.md`。
