from __future__ import annotations

import os
import time
import requests


def _generate_endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/generate"


def generate(prompt: str, model: str, base_url: str) -> str:
    # Local-K8s defaults aim to avoid Ollama OOMs on CPU.
    # These can be overridden via env without code changes.
    num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "2048") or "2048")
    num_batch = int(os.getenv("OLLAMA_NUM_BATCH", "128") or "128")
    request_timeout_s = int(os.getenv("OLLAMA_REQUEST_TIMEOUT_S", "600") or "600")
    temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0.3") or "0.3")
    # Clamp to a sane range (Ollama accepts 0..)
    if temperature < 0.0:
        temperature = 0.0
    if temperature > 2.0:
        temperature = 2.0

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "num_batch": num_batch,
            "temperature": temperature,
        },
    }

    # If the model load causes Ollama to restart (common on memory pressure),
    # a single quick retry helps smooth the first request.
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            resp = requests.post(
                _generate_endpoint(base_url),
                json=payload,
                timeout=request_timeout_s,
            )
            break
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt == 0:
                time.sleep(1.0)
                continue
            raise RuntimeError(
                f"Ollama request failed (attempts=2) url={_generate_endpoint(base_url)}. "
                f"This often means the Ollama container restarted (OOMKilled) while loading the model. "
                f"Check sidecar logs: kubectl logs deploy/rag-api -c ollama --previous"
            ) from e
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        # Make the error actionable (common causes: wrong base URL, model not pulled).
        body_head = ""
        try:
            body_head = (resp.text or "")[:400]
        except Exception:
            body_head = ""
        raise RuntimeError(
            f"Ollama /api/generate failed: status={resp.status_code} url={resp.url}. "
            f"Check OLLAMA_BASE_URL and that the model is pulled (ollama list). "
            f"Response head: {body_head!r}"
        ) from e

    data = resp.json()
    output = data.get("response")
    if not isinstance(output, str):
        raise RuntimeError(f"Unexpected generate response: {data}")
    return output


def generate_json(
    prompt: str,
    *,
    model: str,
    base_url: str,
    temperature: float = 0.1,
    num_predict: int = 256,
) -> str:
    """
    Call Ollama /api/generate with JSON output format enabled when supported.
    Returns raw response text (expected to be a JSON string/object).
    """
    request_timeout_s = int(os.getenv("OLLAMA_REQUEST_TIMEOUT_S", "600") or "600")
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": max(0.0, min(1.0, float(temperature))),
            "num_predict": int(num_predict),
        },
    }
    resp = requests.post(
        _generate_endpoint(base_url),
        json=payload,
        timeout=request_timeout_s,
    )
    resp.raise_for_status()
    data = resp.json()
    out = data.get("response")
    if not isinstance(out, str):
        raise RuntimeError(f"Unexpected generate_json response: {data}")
    if not out.strip():
        raise RuntimeError(f"Planner returned empty response: {data}")
    return out.strip()
