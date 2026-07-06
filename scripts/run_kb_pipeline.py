#!/usr/bin/env python3
"""知识库改动后的一键流水线：kb_lint → (可选)ingest → (可选)benchmark。

设计为**安全默认**：只有 kb_lint 默认执行；ingest 和 benchmark 需显式开启，
且 benchmark 默认打 localhost、不碰生产。

用法：
    python scripts/run_kb_pipeline.py                      # 只跑 kb_lint
    python scripts/run_kb_pipeline.py --benchmark          # kb_lint + 本地跑分
    python scripts/run_kb_pipeline.py --ingest --benchmark # kb_lint + 本地ingest + 跑分
    python scripts/run_kb_pipeline.py --all                # 三步都做（本地）

注意：
- ingest 会写向量库（本地 milvus.db）。**不要在生产服务器上随手跑本脚本的 ingest。**
- benchmark 需要一个在跑的 /v1/qa（默认 http://localhost:8000）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def step(title: str, cmd: list[str]) -> int:
    print(f"\n===== {title} =====\n$ {' '.join(cmd)}")
    try:
        return subprocess.call(cmd, cwd=str(ROOT))
    except Exception as e:
        print(f"[warn] 执行失败: {e}", file=sys.stderr)
        return 1


def main() -> None:
    ap = argparse.ArgumentParser(description="知识库改动一键流水线")
    ap.add_argument("--ingest", action="store_true", help="本地重灌向量库（写 milvus.db）")
    ap.add_argument("--benchmark", action="store_true", help="跑 benchmark")
    ap.add_argument("--all", action="store_true", help="kb_lint + ingest + benchmark 全做")
    ap.add_argument("--collection", default="chatbot_docs")
    ap.add_argument("--golden", default="eval/golden_masanduo_v1.jsonl")
    ap.add_argument("--base-url", default="http://localhost:8000")
    args = ap.parse_args()

    do_ingest = args.ingest or args.all
    do_bench = args.benchmark or args.all
    py = sys.executable
    rc_total = 0

    # 1) kb_lint（总是跑）
    rc = step("1/3 kb_lint（知识库结构检查）", [py, "scripts/kb_lint.py"])
    if rc == 1:
        print("[note] kb_lint 有 error（如正式知识库尚未迁移完成，属正常），流水线继续。")

    # 2) ingest（可选，仅本地）
    if do_ingest:
        rc = step("2/3 ingest（本地重灌，DATA_DIR=data/target --recreate）",
                  ["make", "ingest", f"collection={args.collection}",
                   "args=--recreate"])
        if rc != 0:
            print("[error] ingest 失败：确认本地 .venv/依赖/embedding 模型就绪。", file=sys.stderr)
            rc_total = 1
    else:
        print("\n===== 2/3 ingest 跳过（未加 --ingest） =====")

    # 3) benchmark（可选）
    if do_bench:
        rc = step("3/3 benchmark",
                  [py, "eval/bench_masanduo.py", "--golden", args.golden,
                   "--base-url", args.base_url])
        if rc != 0:
            print("[error] benchmark 失败：确认 API 在跑、base-url 正确。", file=sys.stderr)
            rc_total = 1
    else:
        print("\n===== 3/3 benchmark 跳过（未加 --benchmark） =====")

    print("\n===== 流水线结束 =====")
    print("提示：改了知识库→先 kb_lint 过 →（本地）ingest → benchmark 对比分数 → Langfuse 复核。")
    sys.exit(rc_total)


if __name__ == "__main__":
    main()
