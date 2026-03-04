from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def _project_root() -> Path:
    # src/chatbot/prompts/personas.py -> src/chatbot/prompts -> src/chatbot -> src -> <root>
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=8)
def load_persona_text(persona: str) -> str:
    """
    Load a persona prompt for answer generation only.

    Supported:
    - none: return empty string
    - phone_mom: load src/prompts/personas/phone_mom.zh.txt
    """
    name = (persona or "none").strip().lower()
    if name in {"", "none"}:
        return ""
    if name != "phone_mom":
        raise RuntimeError(f"Unknown ANSWER_PERSONA={persona!r}. Supported: none, phone_mom")

    path = _project_root() / "src" / "prompts" / "personas" / "phone_mom.zh.txt"
    if not path.exists():
        raise RuntimeError(
            f"ANSWER_PERSONA=phone_mom but persona file is missing: {path}. "
            "Expected: src/prompts/personas/phone_mom.zh.txt"
        )
    return path.read_text(encoding="utf-8").strip() + "\n"
