#!/usr/bin/env python3
"""Benchmark embedding latency for the configured provider.

Supports both sentence_transformers (in-process) and ollama (HTTP).

Usage:
    python scripts/bench_embed.py [--provider PROVIDER] [--model MODEL] [--rounds N]
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main() -> None:
    parser = argparse.ArgumentParser(description="Embedding latency benchmark")
    parser.add_argument(
        "--provider",
        default=os.getenv("EMBED_PROVIDER", "sentence_transformers"),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("EMBED_MODEL", "BAAI/bge-m3"),
    )
    parser.add_argument(
        "--ollama-url",
        default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    )
    parser.add_argument("--rounds", type=int, default=20)
    args = parser.parse_args()

    prompts = [
        "手机租赁流程是什么",
        "how to reset my password",
        "退款政策是什么样的",
        "what are the pricing plans available",
    ]

    from src.chatbot.embeddings.provider import embed_text

    # Warmup (loads model weights into memory / GPU VRAM)
    print(f"Warming up provider='{args.provider}' model='{args.model}' …")
    try:
        embed_text(
            "warmup",
            provider=args.provider,
            model=args.model,
            ollama_base_url=args.ollama_url,
        )
    except Exception as exc:
        print(f"ERROR: warmup failed: {exc}", file=sys.stderr)
        sys.exit(1)
    print("Warmup done.\n")

    times: list[float] = []
    for i in range(args.rounds):
        prompt = prompts[i % len(prompts)]
        start = time.perf_counter()
        embed_text(
            prompt,
            provider=args.provider,
            model=args.model,
            ollama_base_url=args.ollama_url,
        )
        elapsed = time.perf_counter() - start
        times.append(elapsed)
        print(f"  [{i + 1:>3}/{args.rounds}]  {elapsed:.4f}s  prompt={prompt[:30]}")

    times.sort()
    n = len(times)
    avg = sum(times) / n
    p50 = times[n // 2]
    p95 = times[int(n * 0.95)]
    p99 = times[min(int(n * 0.99), n - 1)]

    print(f"\n--- {args.provider}/{args.model} over {n} calls ---")
    print(f"  avg  = {avg:.4f}s")
    print(f"  p50  = {p50:.4f}s")
    print(f"  p95  = {p95:.4f}s")
    print(f"  p99  = {p99:.4f}s")
    print(f"  min  = {times[0]:.4f}s")
    print(f"  max  = {times[-1]:.4f}s")

    if avg < 0.8:
        print("\nPASS: avg < 0.8s target met")
    else:
        print(f"\nWARN: avg {avg:.3f}s exceeds 0.8s target")


if __name__ == "__main__":
    main()
