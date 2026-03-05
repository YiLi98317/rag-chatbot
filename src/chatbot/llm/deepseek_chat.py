from __future__ import annotations

from typing import Any, Dict, Optional

import requests


def _chat_completions_url(api_base_url: str) -> str:
    base = (api_base_url or "").strip()
    if not base:
        raise RuntimeError("API_BASE_URL is empty. Set API_BASE_URL (e.g. https://api.deepseek.com).")

    # Accept either an origin (https://api.deepseek.com) or a full endpoint
    # (https://api.deepseek.com/chat/completions).
    if "/chat/completions" in base:
        return base
    return f"{base.rstrip('/')}/chat/completions"


def generate_text(
    prompt: str,
    *,
    api_base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
    request_timeout_s: int = 120,
    response_format_json: bool = False,
) -> str:
    """
    Calls DeepSeek Chat Completions API.

    The rest of the codebase currently builds a single-string prompt (with system-like sections),
    so we send it as a single user message.
    """
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("API_KEY is empty. Set API_KEY for DeepSeek API calls.")

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "temperature": float(temperature),
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}

    url = _chat_completions_url(api_base_url)
    resp = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        json=payload,
        timeout=int(request_timeout_s),
    )

    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        body_head = ""
        try:
            body_head = (resp.text or "")[:800]
        except Exception:
            body_head = ""
        raise RuntimeError(
            f"DeepSeek /chat/completions failed: status={resp.status_code} url={url}. "
            f"Response head: {body_head!r}"
        ) from e

    data = resp.json()
    try:
        choices = data.get("choices") or []
        msg = (choices[0] or {}).get("message") or {}
        content = msg.get("content")
    except Exception:
        content = None
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(f"Unexpected DeepSeek response shape: {data}")

    usage: Optional[Dict[str, Any]] = None
    try:
        u = data.get("usage")
        if isinstance(u, dict):
            pt = u.get("prompt_tokens")
            ct = u.get("completion_tokens")
            prompt_tokens = int(pt) if pt is not None else None
            completion_tokens = int(ct) if ct is not None else None
            total_tokens = (prompt_tokens + completion_tokens) if (prompt_tokens is not None and completion_tokens is not None) else u.get("total_tokens")
            if total_tokens is not None:
                total_tokens = int(total_tokens)
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
    except (TypeError, KeyError, ValueError):
        usage = None

    return content, usage

