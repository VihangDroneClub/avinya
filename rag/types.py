from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SourceChunk:
    source: str
    chunk: str
    relevance_score: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class QueryResult:
    answer_context: str
    sources: list[SourceChunk]
    source_labels: str

