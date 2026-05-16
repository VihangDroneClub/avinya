from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from rag.types import SourceChunk

_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class RerankResult:
    source: SourceChunk
    score: float


def _tokenize(text: str) -> set[str]:
    return {token for token in _WORD_RE.findall((text or "").lower()) if token}


def _metadata_boost(metadata: dict[str, Any] | None, query_tokens: set[str]) -> float:
    if not metadata:
        return 0.0
    boost = 0.0
    category = str(metadata.get("category") or "").lower()
    source = str(metadata.get("source") or "").lower()
    if category and category in query_tokens:
        boost += 0.15
    if source and any(token in source for token in query_tokens):
        boost += 0.1
    return boost


def rerank_sources(query: str, sources: Iterable[SourceChunk]) -> list[SourceChunk]:
    query_tokens = _tokenize(query)
    ranked: list[RerankResult] = []

    for src in sources:
        chunk_tokens = _tokenize(src.chunk)
        if not chunk_tokens:
            overlap_score = 0.0
        else:
            overlap_score = len(query_tokens & chunk_tokens) / max(1, len(query_tokens | chunk_tokens))
        score = overlap_score + _metadata_boost(src.metadata, query_tokens)
        ranked.append(RerankResult(source=src, score=score))

    ranked.sort(key=lambda item: (-item.score, item.source.source, item.source.chunk))
    return [item.source for item in ranked]
