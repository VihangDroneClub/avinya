from __future__ import annotations

from fastapi.testclient import TestClient

import rag.api as rag_api
from core.config import MODEL_DEFAULT


def test_query_endpoint_uses_retriever_and_generator(monkeypatch):
    captured = {}

    def fake_retrieve(question, filters=None, max_results=5, rerank=False, active_collection=None):
        captured["question"] = question
        captured["filters"] = filters
        captured["max_results"] = max_results
        captured["rerank"] = rerank
        return rag_api.QueryResult(
            answer_context="Context chunk",
            sources=[rag_api.SourceChunk(source="vault/report.md", chunk="Context chunk", relevance_score=0.12, metadata={"category": "reports"})],
            source_labels="vault/report.md",
        )

    def fake_generate(prompt, model):
        captured["prompt"] = prompt
        captured["model"] = model
        return "Answer text"

    monkeypatch.setattr(rag_api, "retrieve_query_context", fake_retrieve)
    monkeypatch.setattr(rag_api, "generate_text", fake_generate)

    client = TestClient(rag_api.app)
    response = client.post("/query", json={"question": "What happened?", "filters": {"category": "reports"}, "max_results": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "Answer text"
    assert payload["sources"][0]["file"] == "vault/report.md"
    assert captured["question"] == "What happened?"
    assert captured["filters"] == {"category": "reports"}
    assert captured["max_results"] == 3
    assert captured["rerank"] is False
    assert captured["model"] == MODEL_DEFAULT
    assert "Context chunk" in captured["prompt"]


def test_reindex_endpoint_delegates_to_indexer(monkeypatch):
    captured = {}

    def fake_reindex(vault_root, files=None, active_collection=None):
        captured["vault_root"] = vault_root
        captured["files"] = files
        return rag_api.ReindexResult(status="completed", files_indexed=2, chunks_created=4, time_elapsed=0.25, last_reindex="2026-05-14T00:00:00Z")

    monkeypatch.setattr(rag_api, "reindex_vault", fake_reindex)

    client = TestClient(rag_api.app)
    response = client.post("/reindex", json={"full_reindex": True})

    assert response.status_code == 200
    assert response.json()["files_indexed"] == 2
    assert captured["vault_root"] == rag_api.VAULT_PATH
    assert captured["files"] is None


def test_health_and_stats_endpoints(monkeypatch):
    class StubCollection:
        def count(self):
            return 11

    monkeypatch.setattr(rag_api, "collection", StubCollection())
    monkeypatch.setattr(rag_api, "LAST_REINDEX", "2026-05-14T00:00:00Z")
    monkeypatch.setattr(rag_api, "FILES_INDEXED", 7)
    monkeypatch.setattr(rag_api, "CHUNKS_CREATED", 19)
    monkeypatch.setattr(rag_api, "check_ollama", lambda: None)

    client = TestClient(rag_api.app)
    health = client.get("/health")
    stats = client.get("/stats")

    assert health.status_code == 200
    assert health.json()["status"] == "healthy"
    assert stats.status_code == 200
    assert stats.json()["files_indexed"] == 7
    assert stats.json()["indexed_documents"] == 11


def test_root_and_favicon_endpoints():
    client = TestClient(rag_api.app)
    root = client.get("/")
    favicon = client.get("/favicon.ico")

    assert root.status_code == 200
    assert root.json()["name"] == "Vihang RAG API"
    assert favicon.status_code == 204
