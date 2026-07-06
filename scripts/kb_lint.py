#!/usr/bin/env python3
"""知识库 frontmatter 校验（零依赖）。

扫描 data/knowledge/**/*.md（跳过 _templates/），检查每篇是否有合规的 frontmatter。
用途：让业务写的知识库文档结构统一、可治理、可按角色过滤、可版本回溯。

用法：
    python scripts/kb_lint.py
    python scripts/kb_lint.py --root data/knowledge --report business_review/kb_lint_report.md

退出码：有 error → 1；只有 warning 或全通过 → 0。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REQUIRED = [
    "doc_id", "title", "category", "visible_to",
    "risk_level", "owner", "version", "effective_from", "source_type",
]
RISK_VALUES = {"low", "medium", "high"}


def parse_frontmatter(text: str) -> Optional[Dict[str, object]]:
    """极简 frontmatter 解析：文件须以 --- 开头，到下一个 --- 结束。返回 dict 或 None。"""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fm: Dict[str, object] = {}
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        if ":" not in ln:
            continue
        key, _, raw = ln.partition(":")
        key = key.strip()
        val = raw.strip()
        # 去掉行内注释（空格 + #）
        if " #" in val:
            val = val.split(" #", 1)[0].strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            items = [x.strip() for x in inner.split(",") if x.strip()]
            fm[key] = items
        else:
            fm[key] = val
    return fm


def lint_file(path: Path) -> Tuple[List[str], List[str], Optional[str]]:
    """返回 (errors, warnings, doc_id)。"""
    errors: List[str] = []
    warnings: List[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return [f"读取失败: {e}"], [], None

    fm = parse_frontmatter(text)
    if fm is None:
        return ["缺少 frontmatter（文件需以 --- 开头）"], [], None

    for field in REQUIRED:
        v = fm.get(field)
        if v is None or (isinstance(v, str) and v == "") or (isinstance(v, list) and not v):
            errors.append(f"缺少/为空的必填字段: {field}")

    risk = fm.get("risk_level")
    if isinstance(risk, str) and risk and risk not in RISK_VALUES:
        errors.append(f"risk_level 非法: {risk}（应为 low/medium/high）")

    vt = fm.get("visible_to")
    if isinstance(vt, list) and not vt:
        errors.append("visible_to 为空（至少一个角色）")

    if not fm.get("reviewer"):
        warnings.append("reviewer 为空（建议指定审核人）")

    doc_id = fm.get("doc_id")
    return errors, warnings, (doc_id if isinstance(doc_id, str) and doc_id else None)


def main() -> None:
    ap = argparse.ArgumentParser(description="知识库 frontmatter 校验")
    ap.add_argument("--root", default="data/knowledge")
    ap.add_argument("--report", default="business_review/kb_lint_report.md")
    args = ap.parse_args()

    root = Path(args.root)
    files: List[Path] = []
    if root.exists():
        for p in sorted(root.rglob("*.md")):
            if "_templates" in p.parts:
                continue
            if p.name.upper() == "README.MD":
                continue
            files.append(p)

    total_err = 0
    total_warn = 0
    seen_ids: Dict[str, Path] = {}
    report_lines: List[str] = ["# 知识库 kb_lint 报告", "", f"- 扫描目录: `{root}`", f"- 文件数: {len(files)}", ""]

    if not files:
        report_lines.append("> 未发现 .md 文件（除模板/README）。目前正式知识库可能还没开始迁移。")
        print("[info] 未发现待检查的知识库 .md 文件（跳过 _templates/README）。")

    for p in files:
        errors, warnings, doc_id = lint_file(p)
        if doc_id:
            if doc_id in seen_ids:
                errors.append(f"doc_id 重复: {doc_id}（另见 {seen_ids[doc_id]}）")
            else:
                seen_ids[doc_id] = p
        total_err += len(errors)
        total_warn += len(warnings)
        status = "OK" if not errors and not warnings else ("ERROR" if errors else "WARN")
        print(f"[{status}] {p}")
        for e in errors:
            print(f"    ✗ {e}")
        for w in warnings:
            print(f"    ! {w}")
        report_lines.append(f"## {p}")
        report_lines.append(f"- 状态: {status}")
        for e in errors:
            report_lines.append(f"  - ✗ error: {e}")
        for w in warnings:
            report_lines.append(f"  - ! warn: {w}")
        report_lines.append("")

    report_lines.insert(4, f"- 结果: error={total_err}, warning={total_warn}\n")
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    print(f"\n汇总: error={total_err}, warning={total_warn}")
    print(f"报告: {report_path}")
    sys.exit(1 if total_err > 0 else 0)


if __name__ == "__main__":
    main()
