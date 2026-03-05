from __future__ import annotations

import json
import time
from typing import Any, Dict, Iterator, Optional, Tuple, Union

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


def _parse_usage(u: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(u, dict):
        return None
    try:
        pt = u.get("prompt_tokens")
        ct = u.get("completion_tokens")
        prompt_tokens = int(pt) if pt is not None else None
        completion_tokens = int(ct) if ct is not None else None
        total_tokens = (
            (prompt_tokens + completion_tokens)
            if (prompt_tokens is not None and completion_tokens is not None)
            else u.get("total_tokens")
        )
        if total_tokens is not None:
            total_tokens = int(total_tokens)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
    except (TypeError, KeyError, ValueError):
        return None


def generate_text_stream(
    prompt: str,
    *,
    api_base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
    request_timeout_s: int = 120,
) -> Tuple[str, Optional[Dict[str, Any]], Optional[float]]:
    """
    Calls DeepSeek with stream=True, records TTFB, collects content and usage.
    Returns (content, usage, t_first_token_s).
    """
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("API_KEY is empty. Set API_KEY for DeepSeek API calls.")

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": float(temperature),
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    url = _chat_completions_url(api_base_url)
    resp = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        json=payload,
        timeout=int(request_timeout_s),
        stream=True,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        body_head = (resp.text or "")[:800] if not resp.raw.closed else ""
        raise RuntimeError(
            f"DeepSeek /chat/completions failed: status={resp.status_code} url={url}. "
            f"Response head: {body_head!r}"
        ) from e

    t_start = time.perf_counter()
    ttfb_s: Optional[float] = None
    content_parts: list = []
    usage: Optional[Dict[str, Any]] = None

    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        data_str = line[6:].strip()
        if data_str == "[DONE]":
            break
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        u = data.get("usage")
        if isinstance(u, dict) and (u.get("prompt_tokens") is not None or u.get("completion_tokens") is not None):
            usage = _parse_usage(u)
        choices = data.get("choices") or []
        if choices:
            delta = (choices[0] or {}).get("delta") or {}
            part = delta.get("content")
            if isinstance(part, str):
                if ttfb_s is None:
                    ttfb_s = time.perf_counter() - t_start
                content_parts.append(part)

    content = "".join(content_parts)
    return (content, usage, ttfb_s)


def stream_chunks(
    prompt: str,
    *,
    api_base_url: str,
    api_key: str,
    model: str,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
    request_timeout_s: int = 120,
) -> Iterator[Union[str, Tuple[None, Optional[Dict[str, Any]], Optional[float]]]:
    """
    Streams content deltas from DeepSeek. Yields each content delta as str,
    then yields (None, usage, ttfb_s) at the end.
    """
    key = (api_key or "").strip()
    if not key:
        raise RuntimeError("API_KEY is empty. Set API_KEY for DeepSeek API calls.")

    payload: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "temperature": float(temperature),
    }
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)

    url = _chat_completions_url(api_base_url)
    resp = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        json=payload,
        timeout=int(request_timeout_s),
        stream=True,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError as e:
        body_head = (resp.text or "")[:800] if not resp.raw.closed else ""
        raise RuntimeError(
            f"DeepSeek /chat/completions failed: status={resp.status_code} url={url}. "
            f"Response head: {body_head!r}"
        ) from e

    t_start = time.perf_counter()
    ttfb_s: Optional[float] = None
    usage: Optional[Dict[str, Any]] = None

    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        data_str = line[6:].strip()
        if data_str == "[DONE]":
            break
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        u = data.get("usage")
        if isinstance(u, dict) and (u.get("prompt_tokens") is not None or u.get("completion_tokens") is not None):
            usage = _parse_usage(u)
        choices = data.get("choices") or []
        if choices:
            delta = (choices[0] or {}).get("delta") or {}
            part = delta.get("content")
            if isinstance(part, str):
                if ttfb_s is None:
                    ttfb_s = time.perf_counter() - t_start
                yield part

    yield (None, usage, ttfb_s)

