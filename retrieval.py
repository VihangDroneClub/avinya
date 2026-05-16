from __future__ import annotations

from rag.retriever import collection, retrieve_query_context


def retrieve_context(query: str) -> tuple[str, str]:
    result = retrieve_query_context(query)
    return result.answer_context, result.source_labels
