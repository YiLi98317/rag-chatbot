"""LLM-as-judge（可选，默认不启用）。

第一版重点是 prompt 模板（eval/judge_prompt.md）与"如何调用"的封装。
默认 benchmark 走规则评分（rough_score）；只有显式 --use-judge 且配置了 LLM 时才调用这里。

故障安全：LLM 不可用/解析失败时返回 None，不影响 benchmark 主流程。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_PROMPT_PATH = Path(__file__).with_name("judge_prompt.md")


def _load_prompt_template() -> str:
    try:
        return _PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return ""


def build_judge_prompt(case: Dict[str, Any], answer: str) -> str:
    """把 case + answer 填进 judge_prompt.md 模板，返回可发给 LLM 的完整 prompt。"""
    tpl = _load_prompt_template()
    points = "\n".join(f"- {p}" for p in case.get("expected_answer_points", []))
    forbidden = "、".join(case.get("forbidden_terms", [])) or "（无）"
    repl = {
        "{{question}}": str(case.get("question", "")),
        "{{role}}": str(case.get("role", "")),
        "{{expected_answer_points}}": points or "（无）",
        "{{must_handoff}}": "是" if case.get("must_handoff") else "否",
        "{{forbidden_terms}}": forbidden,
        "{{ideal_reply}}": str(case.get("ideal_reply", "")),
        "{{answer}}": answer or "",
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)
    return tpl


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def judge_case(case: Dict[str, Any], answer: str) -> Optional[Dict[str, Any]]:
    """用现有 chatbot LLM client 调用裁判。任何异常返回 None（不影响主流程）。

    需要项目可导入 `chatbot`（设置 PYTHONPATH=src）且 .env 配好 LLM。
    """
    prompt = build_judge_prompt(case, answer)
    if not prompt:
        return None
    try:
        from chatbot.llm.client import generate as llm_generate  # type: ignore
        from chatbot.settings import get_settings  # type: ignore

        out = llm_generate(prompt, settings=get_settings(), purpose="answer", temperature=0.0)
        return _extract_json(out)
    except Exception:
        return None


__all__ = ["build_judge_prompt", "judge_case"]
