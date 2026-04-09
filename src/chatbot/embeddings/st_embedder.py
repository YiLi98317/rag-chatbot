from __future__ import annotations

from functools import lru_cache
from typing import List, Sequence

import os
import unicodedata
import re

_ZERO_WIDTH_RE = re.compile(r"[\u200B\u200C\u200D\uFEFF]")

# Reduce noisy model-download / weight-loading progress output from HF Hub / safetensors.
# NOTE: these must be set before importing transformers/sentence_transformers to take effect.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Ensure torch is loaded and transformers sees it so that transformers.integrations.accelerate
# imports torch.nn (used in type hints). Otherwise is_torch_available() can be False (e.g. torch < 2.4)
# and the accelerate module never defines nn -> NameError at annotation time.
try:
    import torch  # noqa: F401
    import torch.nn  # noqa: F401
    import transformers.utils.import_utils as _tf_import_utils
    _tf_import_utils.is_torch_available = lambda: True
except Exception:
    pass


def _normalize_input(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "")
    s = _ZERO_WIDTH_RE.sub("", s)
    return s


def _resolve_device() -> str:
    import torch as _torch
    if _torch.cuda.is_available():
        return "cuda"
    return "cpu"


@lru_cache(maxsize=2)
def _get_model(model_name: str):
    # When EMBED_MODEL_LOCAL_PATH is set and exists, load from that path (offline; no Hub access).
    load_path = os.getenv("EMBED_MODEL_LOCAL_PATH", "").strip()
    if load_path and os.path.exists(load_path):
        from sentence_transformers import SentenceTransformer  # type: ignore
        return SentenceTransformer(load_path, device=_resolve_device())

    try:
        from huggingface_hub.utils import disable_progress_bars  # type: ignore
        disable_progress_bars()
    except Exception:
        pass
    try:
        from transformers.utils import logging as hf_logging  # type: ignore
        hf_logging.set_verbosity_error()
    except Exception:
        pass

    from sentence_transformers import SentenceTransformer  # type: ignore
    import torch as _torch

    device = _resolve_device()
    model_kwargs = {"torch_dtype": _torch.float16}
    tokenizer_kwargs = {}

    if device == "cuda":
        try:
            from flash_attn import flash_attn_func  # noqa: F401
            model_kwargs["attn_implementation"] = "flash_attention_2"
        except ImportError:
            pass
        tokenizer_kwargs["padding_side"] = "left"

    return SentenceTransformer(
        model_name,
        device=device,
        model_kwargs=model_kwargs,
        tokenizer_kwargs=tokenizer_kwargs,
    )


def embed_texts(
    texts: Sequence[str],
    *,
    model_name: str,
    batch_size: int = 32,
) -> List[List[float]]:
    if not texts:
        return []
    m = _get_model(model_name)
    normed = [_normalize_input(t) for t in texts]
    try:
        vecs = m.encode(
            normed,
            batch_size=int(batch_size),
            show_progress_bar=False,
            normalize_embeddings=True,
        )
    except TypeError:
        vecs = m.encode(
            normed,
            batch_size=int(batch_size),
            show_progress_bar=False,
        )
    try:
        return vecs.tolist()
    except Exception:
        return [list(map(float, v)) for v in vecs]


def embed_text(text: str, *, model_name: str) -> List[float]:
    out = embed_texts([text], model_name=model_name, batch_size=1)
    return out[0] if out else []

