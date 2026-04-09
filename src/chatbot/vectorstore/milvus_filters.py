from __future__ import annotations

from typing import List, Optional

from chatbot.vectorstore.base import FilterDict


def _quote_str(s: str) -> str:
    # Milvus expr uses single quotes for strings.
    return "'" + (s or "").replace("\\", "\\\\").replace("'", "\\'") + "'"


def build_expr(filters: Optional[FilterDict]) -> Optional[str]:
    """
    Translate v0 filter dict into a Milvus boolean expression.

    Supported keys:
    - table: list[str]
    - lang: list[str]
    """
    if not filters or not isinstance(filters, dict):
        return None

    clauses: List[str] = []

    raw_tables = filters.get("table")
    if isinstance(raw_tables, list):
        tables = [t for t in raw_tables if isinstance(t, str) and t.strip()]
        if tables:
            items = ", ".join(_quote_str(t.strip()) for t in tables)
            clauses.append(f"table in [{items}]")

    raw_lang = filters.get("lang")
    if isinstance(raw_lang, list):
        langs = [t for t in raw_lang if isinstance(t, str) and t.strip()]
        include_empty = any(isinstance(t, str) and not t.strip() for t in raw_lang)
        if langs and include_empty:
            items = ", ".join(_quote_str(t.strip()) for t in langs)
            clauses.append(f"(lang in [{items}] or lang == '')")
        elif langs:
            items = ", ".join(_quote_str(t.strip()) for t in langs)
            clauses.append(f"lang in [{items}]")
        elif include_empty:
            clauses.append("lang == ''")

    if not clauses:
        return None
    return " and ".join(f"({c})" for c in clauses)

