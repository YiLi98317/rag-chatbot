from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Tuple


def _parse_label_and_body(raw: str) -> Tuple[str, str]:
    s = (raw or "").strip()
    if not s:
        return "unknown", ""
    parts = s.split(None, 1)
    if len(parts) == 1:
        return "unknown", parts[0]
    return parts[0], parts[1].strip()


def main() -> None:
    """
    Download dirtycomputer/THUCNews and materialize it into:
      - data/THUCNews/train.jsonl (full fidelity, structured)
      - data/THUCNews/shards/train_shard_XXXX.txt (for our ingester: .txt/.md only)

    Notes:
      - We write sharded .txt files (default 500 docs per shard) to avoid creating 50k files.
      - Shards include a simple header per doc: 【id】[label]
    """
    # Local import so the project can still run without datasets installed.
    from datasets import load_dataset  # type: ignore

    project_root = Path(__file__).resolve().parents[1]
    out_dir = Path(os.getenv("THUCNEWS_OUT_DIR", str(project_root / "data" / "THUCNews")))
    shard_size = int(os.getenv("THUCNEWS_SHARD_SIZE", "500"))

    out_dir.mkdir(parents=True, exist_ok=True)
    shards_dir = out_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = out_dir / "train.jsonl"
    manifest_path = out_dir / "manifest.json"

    # Streaming keeps memory bounded.
    ds = load_dataset("dirtycomputer/THUCNews", split="train", streaming=True)

    label_counts: Counter[str] = Counter()
    total = 0
    shard_no = 0
    in_shard = 0
    shard_fp = None

    def open_new_shard() -> None:
        nonlocal shard_fp, shard_no, in_shard
        if shard_fp is not None:
            shard_fp.close()
        shard_path = shards_dir / f"train_shard_{shard_no:04d}.txt"
        shard_fp = shard_path.open("w", encoding="utf-8")
        shard_no += 1
        in_shard = 0

    open_new_shard()

    with jsonl_path.open("w", encoding="utf-8") as jf:
        for ex in ds:
            raw = str(ex.get("text", ""))
            label, body = _parse_label_and_body(raw)

            rec = {
                "id": total,
                "label": label,
                "text": body,
                "raw": raw,
            }
            jf.write(json.dumps(rec, ensure_ascii=False) + "\n")

            # Our ingester reads .txt/.md and chunks by language. This is the simplest format.
            assert shard_fp is not None
            shard_fp.write(f"【{total}】[{label}]\n")
            shard_fp.write(body)
            shard_fp.write("\n\n")

            label_counts[label] += 1
            total += 1
            in_shard += 1

            if in_shard >= shard_size:
                open_new_shard()

    if shard_fp is not None:
        shard_fp.close()

    manifest = {
        "dataset": "dirtycomputer/THUCNews",
        "split": "train",
        "total_rows": total,
        "shard_size": shard_size,
        "shards_dir": str(shards_dir),
        "jsonl_path": str(jsonl_path),
        "label_counts": dict(label_counts),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote THUCNews to: {out_dir}")
    print(f"- rows: {total}")
    print(f"- shards: {shard_no} (size={shard_size})")
    print(f"- jsonl: {jsonl_path}")


if __name__ == "__main__":
    main()

