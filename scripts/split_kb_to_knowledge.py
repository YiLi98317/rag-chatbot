#!/usr/bin/env python3
"""把历史单文件 data/target/知识库.md 机械拆分进 data/knowledge/ 治理结构。

按 `## ` 顶级小节切分，每节生成一个带 frontmatter 的 .md（内容原样，零转写误差）。
类别/风险等级按标题关键词启发式映射；owner/reviewer 标"待业务确认"，需业务后续审。

用法：
    python scripts/split_kb_to_knowledge.py            # dry-run，只打印将生成的文件
    python scripts/split_kb_to_knowledge.py --write     # 实际写入 data/knowledge/
默认不覆盖已存在文件（除非 --force）。
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "target" / "知识库.md"
OUT = ROOT / "data" / "knowledge"

# (关键词, 目录, source_type, risk_level)
RULES: List[Tuple[List[str], str, str, str]] = [
    (["首付", "费用", "提现", "返款", "结算", "还款", "结清"], "10_pricing_and_fee", "rule", "high"),
    (["锁机", "系统版本", "受远程管理", "权限"], "02_sop", "sop", "high"),
    (["下单", "审核", "验机", "办单", "绑定", "导资料", "电脑端", "安卓"], "02_sop", "sop", "high"),
    (["入驻", "营业员"], "08_system_operations", "system_operation", "low"),
]
DEFAULT = ("05_faq", "faq", "medium")


def classify(title: str) -> Tuple[str, str, str]:
    for kws, cat, st, risk in RULES:
        if any(k in title for k in kws):
            return cat, st, risk
    return DEFAULT


def split_sections(text: str) -> List[Tuple[str, str]]:
    """返回 [(title, section_text)]，按 '## ' 切。忽略首个 H1 之前内容。"""
    lines = text.splitlines()
    sections: List[Tuple[str, str]] = []
    cur_title = None
    cur_lines: List[str] = []
    for ln in lines:
        if ln.startswith("## "):
            if cur_title is not None:
                sections.append((cur_title, "\n".join(cur_lines).strip()))
            cur_title = ln[3:].strip()
            cur_lines = [ln]
        elif cur_title is not None:
            cur_lines.append(ln)
    if cur_title is not None:
        sections.append((cur_title, "\n".join(cur_lines).strip()))
    return sections


def build(title: str, body: str, idx: int) -> Tuple[str, str, str]:
    cat, st, risk = classify(title)
    doc_id = f"kb-{idx:02d}"
    fm = (
        "---\n"
        f"doc_id: {doc_id}\n"
        f"title: {title}\n"
        f"category: {cat}\n"
        "visible_to: [加盟商, 店员, 客服]\n"
        f"risk_level: {risk}\n"
        "owner: 待业务确认\n"
        "reviewer: 待业务确认\n"
        "version: 2026-07\n"
        "effective_from: 2026-07-01\n"
        "effective_to:\n"
        f"source_type: {st}\n"
        "---\n\n"
        "> 由 知识库.md 机械拆分生成，内容原样。owner/reviewer 待业务确认。\n\n"
    )
    return cat, f"{doc_id}.md", fm + body + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="拆分 知识库.md → data/knowledge/")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true", help="覆盖已存在文件")
    args = ap.parse_args()

    if not SRC.exists():
        raise SystemExit(f"源文件不存在: {SRC}")
    sections = split_sections(SRC.read_text(encoding="utf-8"))
    print(f"共 {len(sections)} 个小节")
    written = 0
    for i, (title, body) in enumerate(sections, 1):
        cat, fname, content = build(title, body, i)
        dest = OUT / cat / fname
        print(f"  [{cat}/{fname}] {title}")
        if args.write:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and not args.force:
                print(f"    (跳过：已存在，加 --force 覆盖)")
                continue
            dest.write_text(content, encoding="utf-8")
            written += 1
    if args.write:
        print(f"\n已写入 {written} 个文件到 {OUT}")
    else:
        print("\n[dry-run] 未写入。加 --write 生成。")


if __name__ == "__main__":
    main()
