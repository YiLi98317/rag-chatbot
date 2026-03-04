from __future__ import annotations

from typing import Literal, Optional

from chatbot.llm.deepseek_chat import generate_text as deepseek_generate_text
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
        return deepseek_generate_text(
            prompt,
            api_base_url=api_base_url,
            api_key=api_key,
            model=model,
            temperature=t,
            max_tokens=mt,
            request_timeout_s=timeout_s,
            response_format_json=True,
        )

    t = float(temperature) if temperature is not None else float(getattr(settings, "llm_temperature", 0.3))
    mt = max_tokens if max_tokens is not None else getattr(settings, "llm_max_tokens", None)
    timeout_s = int(getattr(settings, "llm_request_timeout_s", 120))
    return deepseek_generate_text(
        prompt,
        api_base_url=api_base_url,
        api_key=api_key,
        model=model,
        temperature=t,
        max_tokens=mt,
        request_timeout_s=timeout_s,
        response_format_json=False,
    )

