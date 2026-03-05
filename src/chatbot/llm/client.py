from __future__ import annotations

import time
from typing import Any, Dict, Iterator, Literal, Optional, Tuple, Union

from chatbot.llm.deepseek_chat import (
    generate_text as deepseek_generate_text,
    generate_text_stream as deepseek_generate_text_stream,
    stream_chunks as deepseek_stream_chunks,
)
from chatbot.llm.ollama_chat import generate as ollama_generate
from chatbot.llm.ollama_chat import generate_json as ollama_generate_json
from chatbot.settings import Settings


Purpose = Literal["answer", "planner_json"]


def _norm_provider(p: str) -> str:
    v = (p or "").strip().lower()
    if v in {"api", "deepseek", "deepseek_api", "deepseek-api"}:
        return "deepseek"
    if v in {"ollama", "local"}:
        return "ollama"
    return v or "deepseek"


def generate(
    prompt: str,
    *,
    settings: Settings,
    purpose: Purpose = "answer",
    model_override: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """
    Provider-agnostic LLM generation used by both:
    - answer generation
    - query planner JSON generation
    """
    provider = _norm_provider(getattr(settings, "llm_provider", "deepseek"))

    if provider == "ollama":
        model = model_override or getattr(settings, "chat_model", "llama3.1")
        base_url = getattr(settings, "ollama_base_url", "http://localhost:11434")
        if purpose == "planner_json":
            t = float(temperature) if temperature is not None else float(getattr(settings, "llm_planner_temperature", 0.1))
            mt = max_tokens if max_tokens is not None else int(getattr(settings, "llm_planner_max_tokens", 256))
            return ollama_generate_json(
                prompt,
                model=model,
                base_url=base_url,
                temperature=t,
                num_predict=int(mt),
            )
        return ollama_generate(prompt=prompt, model=model, base_url=base_url)

    # DeepSeek / API path
    api_key = getattr(settings, "api_key", "") or ""
    api_base_url = getattr(settings, "api_base_url", "") or ""
    default_model = getattr(settings, "model_name", "deepseek-chat")
    model = model_override or default_model

    if purpose == "planner_json":
        t = float(temperature) if temperature is not None else float(getattr(settings, "llm_planner_temperature", 0.1))
        mt = max_tokens if max_tokens is not None else int(getattr(settings, "llm_planner_max_tokens", 256))
        timeout_s = int(getattr(settings, "llm_planner_request_timeout_s", getattr(settings, "llm_request_timeout_s", 60)))
        content, _ = deepseek_generate_text(
            prompt,
            api_base_url=api_base_url,
            api_key=api_key,
            model=model,
            temperature=t,
            max_tokens=mt,
            request_timeout_s=timeout_s,
            response_format_json=True,
        )
        return content

    t = float(temperature) if temperature is not None else float(getattr(settings, "llm_temperature", 0.3))
    mt = max_tokens if max_tokens is not None else getattr(settings, "llm_max_tokens", None)
    timeout_s = int(getattr(settings, "llm_request_timeout_s", 120))
    content, _ = deepseek_generate_text(
        prompt,
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        temperature=t,
        max_tokens=mt,
        request_timeout_s=timeout_s,
        response_format_json=False,
    )
    return content


def generate_with_metrics(
    prompt: str,
    *,
    settings: Settings,
    model_override: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Tuple[str, Optional[Dict[str, Any]], float, Optional[float]]:
    """
    Returns (content, usage_dict, t_llm_total_s, t_llm_first_token_s).
    usage_dict has prompt_tokens, completion_tokens, total_tokens when available.
    t_llm_first_token_s is None when not using streaming.
    """
    provider = _norm_provider(getattr(settings, "llm_provider", "deepseek"))

    if provider == "ollama":
        t0 = time.perf_counter()
        content = ollama_generate(
            prompt=prompt,
            model=model_override or getattr(settings, "chat_model", "llama3.1"),
            base_url=getattr(settings, "ollama_base_url", "http://localhost:11434"),
        )
        elapsed = time.perf_counter() - t0
        return (content or "", None, elapsed, None)

    # DeepSeek / API path: use streaming to capture TTFB
    api_key = getattr(settings, "api_key", "") or ""
    api_base_url = getattr(settings, "api_base_url", "") or ""
    default_model = getattr(settings, "model_name", "deepseek-chat")
    model = model_override or default_model
    t = float(temperature) if temperature is not None else float(getattr(settings, "llm_temperature", 0.3))
    mt = max_tokens if max_tokens is not None else getattr(settings, "llm_max_tokens", None)
    timeout_s = int(getattr(settings, "llm_request_timeout_s", 120))

    t0 = time.perf_counter()
    content, usage, ttfb_s = deepseek_generate_text_stream(
        prompt,
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        temperature=t,
        max_tokens=mt,
        request_timeout_s=timeout_s,
    )
    elapsed = time.perf_counter() - t0
    return (content or "", usage, elapsed, ttfb_s)


def stream_answer_chunks(
    prompt: str,
    *,
    settings: Settings,
    model_override: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> Iterator[Union[str, Tuple[None, Optional[Dict[str, Any]], Optional[float]]]:
    """
    Yields content chunks (str), then (None, usage_dict, ttfb_s) at the end.
    Use for streaming the answer to the client.
    """
    provider = _norm_provider(getattr(settings, "llm_provider", "deepseek"))

    if provider == "ollama":
        content = ollama_generate(
            prompt=prompt,
            model=model_override or getattr(settings, "chat_model", "llama3.1"),
            base_url=getattr(settings, "ollama_base_url", "http://localhost:11434"),
        )
        if content:
            yield content
        yield (None, None, None)
        return

    api_key = getattr(settings, "api_key", "") or ""
    api_base_url = getattr(settings, "api_base_url", "") or ""
    default_model = getattr(settings, "model_name", "deepseek-chat")
    model = model_override or default_model
    t = float(temperature) if temperature is not None else float(getattr(settings, "llm_temperature", 0.3))
    mt = max_tokens if max_tokens is not None else getattr(settings, "llm_max_tokens", None)
    timeout_s = int(getattr(settings, "llm_request_timeout_s", 120))

    for item in deepseek_stream_chunks(
        prompt,
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        temperature=t,
        max_tokens=mt,
        request_timeout_s=timeout_s,
    ):
        yield item

