"""马三多工作流挂件。

独立子包，复用 chatbot 的 llm.client / settings / RAG（answer_question）。
不修改任何现有 RAG 代码。对外暴露 engine.respond。
"""

from chatbot.masanduo.engine import respond

__all__ = ["respond"]
