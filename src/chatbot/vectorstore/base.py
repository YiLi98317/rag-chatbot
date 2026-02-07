from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence


Metadata = Dict[str, Any]


@dataclass(frozen=True)
class Point:
    id: str
    vector: List[float]
    text: str
    metadata: Metadata


@dataclass(frozen=True)
class Hit:
    id: str
    score: float
    text: str
    metadata: Metadata


FilterDict = Dict[str, Any]


class VectorStore(Protocol):
    def ensure_collection(self, collection: str, dim: int) -> None: ...

    def upsert(self, collection: str, points: Sequence[Point], *, batch_size: int = 512) -> None: ...

    def search(
        self,
        collection: str,
        vector: Sequence[float],
        *,
        top_k: int,
        filters: Optional[FilterDict] = None,
        debug: bool = False,
    ) -> List[Hit]: ...

    def healthcheck(self) -> bool: ...

