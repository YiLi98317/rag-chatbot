from __future__ import annotations

import os

from chatbot.config import get_settings
from chatbot.rag.pipeline import build_prompt


def _assert_contains(haystack: str, needle: str) -> None:
    if needle not in haystack:
        raise AssertionError(f"Missing {needle!r} in prompt. Head:\n{haystack[:600]!r}")


def main() -> None:
    contexts = [
        "一级分类（必填）: 3300 话术标题（选填）: 下单流程 话术内容（必填）: 办单流程① 商家打开手机妈妈APP登录…",
        "一级分类（必填）: 1111 话术标题（选填）: 下单成功 话术内容（必填）: 客户下单成功后…",
    ]
    question = "手机妈下单流程是什么"

    # Persona OFF
    os.environ["ANSWER_PERSONA"] = "none"
    s0 = get_settings()
    p0 = build_prompt(question, contexts, debug=False, settings=s0)
    _assert_contains(p0, "SYSTEM_GROUNDING_RULES:")
    _assert_contains(p0, "CONTEXT:")
    _assert_contains(p0, "[1]")
    _assert_contains(p0, "QUESTION:")
    _assert_contains(p0, "ANSWER:")
    if "SYSTEM_PERSONA:" in p0:
        raise AssertionError("Persona should be skipped when ANSWER_PERSONA=none")

    # Persona ON
    os.environ["ANSWER_PERSONA"] = "phone_mom"
    s1 = get_settings()
    p1 = build_prompt(question, contexts, debug=False, settings=s1)
    _assert_contains(p1, "SYSTEM_PERSONA:")
    _assert_contains(p1, "SYSTEM_GROUNDING_RULES:")
    _assert_contains(p1, "我在现有资料中没有看到相关信息")
    _assert_contains(p1, "CONTEXT:")
    _assert_contains(p1, "[1]")
    _assert_contains(p1, "[2]")
    _assert_contains(p1, "QUESTION:")
    _assert_contains(p1, "ANSWER:")

    print("OK: persona prompt composition looks correct.")


if __name__ == "__main__":
    main()

