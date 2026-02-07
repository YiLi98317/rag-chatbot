#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import threading
import time
import subprocess
from pathlib import Path

# Ensure `src/` is on sys.path so `import chatbot` works when running this file directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from chatbot.embeddings.provider import embed_text  # noqa: E402
from chatbot.settings import get_settings  # noqa: E402
from chatbot.vectorstore import get_vector_store  # noqa: E402
from chatbot.vectorstore.base import Point  # noqa: E402


def _ts() -> str:
    # ISO-ish without depending on tz-aware libs.
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _log(msg: str) -> None:
    print(f"[bootstrap] {_ts()} {msg}", flush=True)


def _du_human(path: str) -> str | None:
    # Best-effort: show HF cache growth to indicate progress during model download.
    try:
        out = subprocess.check_output(["du", "-sh", path], stderr=subprocess.DEVNULL, text=True).strip()
        return out.split()[0] if out else None
    except Exception:
        return None


def _start_heartbeat(*, every_seconds: int, stop: threading.Event, hf_cache_dir: str) -> threading.Thread:
    def _run() -> None:
        i = 0
        while not stop.wait(every_seconds):
            i += 1
            size = _du_human(hf_cache_dir) if hf_cache_dir else None
            extra = f" hf_cache={size}" if size else ""
            _log(f"still working... (tick={i}){extra}")

    t = threading.Thread(target=_run, name="bootstrap-heartbeat", daemon=True)
    t.start()
    return t


def main() -> int:
    _log("starting")
    s = get_settings()
    _log(
        "settings loaded"
        f" vector_provider={s.vector_provider}"
        f" collection={s.default_collection}"
        f" embed={s.embed_provider}:{s.embed_model}"
        f" chat_model={s.chat_model}"
        f" ollama_base_url={s.ollama_base_url}"
    )
    store = get_vector_store(s)
    _log("vector store initialized")

    # Compute an embedding to get the correct dimension for the configured embed model.
    seed_text = os.getenv("BOOTSTRAP_TEXT", "bootstrap collection")
    hf_cache_dir = os.getenv("HF_HOME") or "/root/.cache/huggingface"
    stop = threading.Event()
    hb = _start_heartbeat(every_seconds=30, stop=stop, hf_cache_dir=hf_cache_dir)
    t0 = time.time()
    _log("computing embedding (this may download/load the model on first run)")
    try:
        vec = embed_text(seed_text, provider=s.embed_provider, model=s.embed_model, ollama_base_url=s.ollama_base_url)
    finally:
        stop.set()
        hb.join(timeout=1)
    _log(f"embedding computed in {time.time() - t0:.1f}s")
    if not vec:
        raise RuntimeError("Failed to compute embedding vector (empty result). Check EMBED_PROVIDER/EMBED_MODEL.")

    collection = s.default_collection
    _log(f"ensuring collection exists: {collection} (dim={len(vec)})")
    store.ensure_collection(collection, len(vec))
    _log("collection ensured")

    # Optional: upsert a single point so early searches have a valid schema and at least one row.
    # (This keeps bootstrap minimal; real ingestion can overwrite/replace later.)
    try:
        _log("upserting bootstrap point")
        store.upsert(
            collection,
            points=[
                Point(
                    id="bootstrap:0",
                    vector=list(vec),
                    text="bootstrap document",
                    metadata={"source": "bootstrap", "table": "", "lang": "en"},
                )
            ],
            batch_size=1,
        )
        _log("upsert done")
    except Exception:
        # Best-effort: collection creation is the critical bit for readiness.
        _log("upsert failed (ignored)")
        pass

    _log(f"BOOTSTRAP_OK collection={collection} dim={len(vec)} provider={s.vector_provider} embed={s.embed_provider}:{s.embed_model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

