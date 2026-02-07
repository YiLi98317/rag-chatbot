from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Counter as CounterType, Tuple


def parse_label_and_body(line: str) -> Tuple[str, str]:
    s = (line or "").strip()
    if not s:
        return "unknown", ""
    if "\t" in s:
        label, body = s.split("\t", 1)
        return (label or "unknown").strip(), (body or "").strip()
    parts = s.split(None, 1)
    if len(parts) == 1:
        return "unknown", parts[0]
    return parts[0], parts[1].strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Shard THUCNews cnews.train.txt and optionally cap max docs."
    )
    parser.add_argument(
        "--input",
        default="data/THUCNews/cnews.train.txt",
        help="Input file path (default: data/THUCNews/cnews.train.txt)",
    )
    parser.add_argument(
        "--out",
        default="data/THUCNews/sample",
        help="Output directory (default: data/THUCNews/sample)",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=2000,
        help="Max articles to write (suggest 500-5000; default: 2000)",
    )
    parser.add_argument(
        "--balanced",
        action="store_true",
        help="Try to balance samples across labels (recommended).",
    )
    parser.add_argument(
        "--labels",
        nargs="*",
        default=None,
        help="Optional explicit label set for balancing. If omitted, uses THUCNews defaults.",
    )
    parser.add_argument(
        "--shard-size",
        type=int,
        default=250,
        help="Docs per shard .txt file (default: 250)",
    )
    args = parser.parse_args()

    inp = Path(args.input)
    out_dir = Path(args.out)
    if not inp.exists():
        raise SystemExit(f"Input file not found: {inp}")
    if args.max_docs <= 0:
        raise SystemExit("--max-docs must be > 0")
    if args.shard_size <= 0:
        raise SystemExit("--shard-size must be > 0")

    out_dir.mkdir(parents=True, exist_ok=True)
    shards_dir = out_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = out_dir / "train.sample.jsonl"
    manifest_path = out_dir / "manifest.json"

    label_counts: CounterType[str] = Counter()
    total = 0
    shard_no = 0
    in_shard = 0
    shard_fp = None

    def open_new_shard() -> None:
        nonlocal shard_fp, shard_no, in_shard
        if shard_fp is not None:
            shard_fp.close()
        shard_path = shards_dir / f"cnews_train_sample_shard_{shard_no:04d}.txt"
        shard_fp = shard_path.open("w", encoding="utf-8")
        shard_no += 1
        in_shard = 0

    open_new_shard()

    # THUCNews is commonly grouped by label blocks in the raw file.
    # If we just take the first N lines, we'd only get the first label.
    label_allow: dict[str, int] | None = None
    if args.balanced:
        labels = args.labels
        if not labels:
            labels = [
                "体育",
                "娱乐",
                "家居",
                "房产",
                "教育",
                "时尚",
                "时政",
                "游戏",
                "科技",
                "财经",
            ]
        per_label = max(1, int(math.ceil(args.max_docs / max(1, len(labels)))))
        label_allow = {lab: per_label for lab in labels}

    with inp.open("r", encoding="utf-8", errors="ignore") as f, jsonl_path.open(
        "w", encoding="utf-8"
    ) as jf:
        for line in f:
            if total >= args.max_docs:
                break

            label, body = parse_label_and_body(line)
            if not body:
                continue
            if label_allow is not None:
                if label not in label_allow:
                    continue
                if label_counts[label] >= label_allow[label]:
                    continue

            rec = {"id": total, "label": label, "text": body}
            jf.write(json.dumps(rec, ensure_ascii=False) + "\n")

            assert shard_fp is not None
            shard_fp.write(f"【{total}】[{label}]\n")
            shard_fp.write(body)
            shard_fp.write("\n\n")

            label_counts[label] += 1
            total += 1
            in_shard += 1

            if in_shard >= args.shard_size:
                open_new_shard()

    if shard_fp is not None:
        shard_fp.close()

    manifest = {
        "source": str(inp),
        "total_rows_written": total,
        "max_docs": args.max_docs,
        "balanced": bool(args.balanced),
        "label_allow": label_allow,
        "shard_size": args.shard_size,
        "shards_dir": str(shards_dir),
        "jsonl_path": str(jsonl_path),
        "label_counts": dict(label_counts),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote sample to: {out_dir}")
    print(f"- rows: {total}")
    print(f"- shards: {shard_no} (size={args.shard_size})")


if __name__ == "__main__":
    main()

