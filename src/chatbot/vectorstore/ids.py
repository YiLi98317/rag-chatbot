from __future__ import annotations

import uuid
from typing import Any, Iterable, Optional


def stable_id(parts: Iterable[Any]) -> str:
    """
    Deterministic UUIDv5 from arbitrary parts.

    Used to generate stable vector IDs across re-ingests.
    """
    raw = "|".join("" if p is None else str(p) for p in parts)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))


def stable_chunk_id(
    *,
    source: str,
    chunk_id: int,
    table: Optional[str] = None,
    doc_id: Optional[str] = None,
    row_id: Optional[str] = None,
    extra: Optional[str] = None,
) -> str:
    return stable_id(
        [
            "v0",
            table or "",
            source or "",
            doc_id or "",
            row_id or "",
            int(chunk_id),
            extra or "",
        ]
    )

