from __future__ import annotations

import rag.reranker as reranker
from rag.retriever import QueryResult, SourceChunk, retrieve_query_context


class _StubCollection:
    def __init__(self):
        self.last_where = None

    def count(self):
        return 2

    def query(self, query_embeddings=None, n_results=None, include=None, where=None):
        self.last_where = where
        return {
            "documents": [["Budget allocation overview", "Meeting action items"]],
            "ids": [["doc-1", "doc-2"]],
            "metadatas": [[
                {"source": "accounts/budget.md", "category": "accounts", "created_at": "2026-05-01T00:00:00Z"},
                {"source": "meetings/minutes.md", "category": "meetings", "created_at": "2026-05-02T00:00:00Z"},
            ]],
            "distances": [[0.12, 0.35]],
            "embeddings": [[[0.1, 0.2], [0.2, 0.1]]],
        }


def test_retriever_applies_category_and_date_filters(monkeypatch):
    stub = _StubCollection()
    monkeypatch.setattr("rag.retriever.generate_embedding", lambda query: [0.1, 0.2])

    result = retrieve_query_context(
        "budget question",
        filters={"category": "accounts", "date_range": ["2026-05-01", "2026-05-31"]},
        active_collection=stub,
    )

    assert stub.last_where == {
        "category": {"$eq": "accounts"},
        "created_at": {"$gte": "2026-05-01", "$lte": "2026-05-31"},
    }
    assert result.sources
    assert result.sources[0].metadata.get("category") == "accounts"


def test_reranker_prefers_matching_chunk_and_keeps_traceability():
    sources = [
        SourceChunk(source="accounts/budget.md", chunk="Budget allocation for equipment and batteries", metadata={"category": "accounts"}),
        SourceChunk(source="meetings/minutes.md", chunk="General agenda and open items", metadata={"category": "meetings"}),
    ]

    ranked = reranker.rerank_sources("budget equipment", sources)

    assert ranked[0].source == "accounts/budget.md"
    assert ranked[0].metadata["category"] == "accounts"
    assert ranked[1].source == "meetings/minutes.md"


def test_retriever_can_rerank_results(monkeypatch):
    stub = _StubCollection()
    monkeypatch.setattr("rag.retriever.generate_embedding", lambda query: [0.1, 0.2])
    monkeypatch.setattr(
        "rag.retriever.rerank_sources",
        lambda query, sources: list(reversed(sources)),
    )

    result = retrieve_query_context(
        "budget question",
        filters=None,
        rerank=True,
        active_collection=stub,
    )

    assert result.sources[0].source == "meetings/minutes.md"
    assert "Meeting action items" in result.answer_context or "Meeting" in result.answer_context
