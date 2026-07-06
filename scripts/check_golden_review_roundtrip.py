#!/usr/bin/env python3
"""导出↔导入闭环自测（roundtrip）。

流程：
1) 用与 importer 对齐的表头，程序化生成一份含 5 种状态的回填样例
   （默认写到 business_review/golden_review_roundtrip_sample.csv，保证列对齐）。
2) 跑 import 的 dry-run（不写）。
3) 跑 import 的 --write，生成临时 v2。
4) 断言 v2 的题数变化 / delete / add / confirmed / revise / pending 均正确。

只读/临时写，不碰线上，不覆盖 v1。用法：
    python scripts/check_golden_review_roundtrip.py
退出码：全通过 0，否则 1。
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.export_golden_review import columns  # noqa: E402

BASE = ROOT / "eval" / "golden_masanduo_v1.jsonl"
SAMPLE = ROOT / "business_review" / "golden_review_roundtrip_sample.csv"

# 使用 v1 里真实存在的 id
CONFIRMED_ID = "fee_001"
REVISE_ID = "fee_002"
DELETE_ID = "chat_004"
PENDING_ID = "audit_005"
ADD_ID = "rt_add_001"
REVISED_IDEAL = "老板，这是修订后的理想回答：订单总价=售价+服务费+50元设备管理费，具体以系统为准。"


def build_sample() -> None:
    cols = columns(False)

    def row(**kw: str) -> dict:
        r = {c: "" for c in cols}
        r.update(kw)
        return r

    rows = [
        row(id=CONFIRMED_ID, business_status="confirmed", reviewer="张三",
            owner="运营", reviewed_at="2026-07-03", business_comment="答案没问题"),
        row(id=REVISE_ID, business_status="revise", reviewer="李四", owner="财务",
            reviewed_at="2026-07-03", business_comment="补充设备管理费",
            revised_ideal_reply=REVISED_IDEAL),
        row(id=DELETE_ID, business_status="delete", reviewer="张三",
            reviewed_at="2026-07-03", business_comment="和业务无关删掉"),
        row(id=PENDING_ID, business_status="pending", reviewer="王五",
            reviewed_at="2026-07-03", business_comment="通过率口径待风控确认"),
        row(id=ADD_ID, category="服务费/费用解释", role="店员",
            question="会员服务费能不能退？", business_status="add",
            reviewer="赵六", owner="客服主管", reviewed_at="2026-07-03",
            revised_expected_answer_points="以平台规则为准；不要承诺一定可退",
            revised_ideal_reply="老板，会员服务费能不能退以平台规则为准，别打包票，让客户在小程序或联系客服确认。"),
    ]
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def load_jsonl(path: Path) -> list:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def run_import(out: Path, write: bool) -> int:
    cmd = [sys.executable, "scripts/import_golden_review.py",
           "--input", str(SAMPLE), "--base-golden", str(BASE),
           "--output", str(out), "--report", str(out.with_suffix(".report.md"))]
    if write:
        cmd.append("--write")
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> None:
    if not BASE.exists():
        print(f"[fail] base golden 不存在: {BASE}")
        sys.exit(1)

    build_sample()
    print(f"[ok] 生成 roundtrip 样例: {SAMPLE}")

    tmp = Path(tempfile.mkdtemp(prefix="rt_"))
    v2 = tmp / "golden_v2.jsonl"

    # dry-run（不应写 v2）
    run_import(v2, write=False)
    if v2.exists():
        print("[fail] dry-run 不应生成 v2，但文件已存在")
        sys.exit(1)
    print("[ok] dry-run 未写 v2")

    # write
    rc = run_import(v2, write=True)
    if rc != 0 or not v2.exists():
        print(f"[fail] --write 未生成 v2 (rc={rc})")
        sys.exit(1)

    base = load_jsonl(BASE)
    new = load_jsonl(v2)
    by_id = {c["id"]: c for c in new}
    ids = set(by_id)

    checks = []

    def chk(name: str, ok: bool) -> None:
        checks.append((name, ok))
        print(("  ✓ " if ok else "  ✗ ") + name)

    chk(f"题数变化正确（{len(base)} -1删 +1增 = {len(base)}）", len(new) == len(base))
    chk(f"delete 生效（{DELETE_ID} 不在 v2）", DELETE_ID not in ids)
    chk(f"add 生效（{ADD_ID} 在 v2）", ADD_ID in ids)
    chk(f"confirmed 后 needs_business_review=false（{CONFIRMED_ID}）",
        by_id.get(CONFIRMED_ID, {}).get("needs_business_review") is False)
    chk(f"revise 覆盖 ideal_reply（{REVISE_ID}）",
        by_id.get(REVISE_ID, {}).get("ideal_reply") == REVISED_IDEAL)
    chk(f"revise 后 needs_business_review=false（{REVISE_ID}）",
        by_id.get(REVISE_ID, {}).get("needs_business_review") is False)
    chk(f"pending 保持 needs_business_review=true（{PENDING_ID}）",
        by_id.get(PENDING_ID, {}).get("needs_business_review") is True)
    chk(f"add 默认 needs_business_review=true（{ADD_ID}）",
        by_id.get(ADD_ID, {}).get("needs_business_review") is True)
    chk("v1 未被覆盖（仍存在且题数不变）", BASE.exists() and len(load_jsonl(BASE)) == len(base))

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)
    print(f"\nROUNDTRIP: {passed}/{total} 通过")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
