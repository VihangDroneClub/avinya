# API Reference

## `POST /query`

Answer a question against the indexed vault.

Request:

```json
{
  "question": "What was the 2025 budget allocation?",
  "filters": {
    "category": "accounts",
    "date_range": ["2026-05-01", "2026-05-31"]
  },
  "max_results": 5,
  "rerank": true
}
```

Response:

```json
{
  "answer": "string",
  "sources": [
    {
      "file": "accounts/budget.md",
      "chunk": "retrieved text",
      "relevance_score": 0.12,
      "metadata": {
        "category": "accounts",
        "created_at": "2026-05-14T00:00:00Z"
      }
    }
  ],
  "query_time": 0.42
}
```

Notes:
- `filters.category` limits retrieval to one metadata category.
- `filters.date_range` expects `[start, end]`.
- `rerank=true` applies the lightweight lexical reranker after retrieval.

## `POST /reindex`

Rebuild the Chroma index from the vault.

Request:

```json
{
  "full_reindex": true,
  "files": []
}
```

Response:

```json
{
  "status": "completed",
  "files_indexed": 12,
  "chunks_created": 84,
  "time_elapsed": 3.21
}
```

Notes:
- `full_reindex=true` rebuilds from every markdown file in the vault.
- `files` may be used for a partial rebuild when `full_reindex=false`.

## `GET /health`

Return backend status.

Response:

```json
{
  "status": "healthy",
  "chromadb": "connected",
  "ollama": "running",
  "indexed_documents": 84,
  "last_reindex": "2026-05-14T00:00:00Z"
}
```

## `GET /stats`

Return index counters and last reindex time.

Response:

```json
{
  "status": "ok",
  "files_indexed": 12,
  "chunks_created": 84,
  "indexed_documents": 84,
  "last_reindex": "2026-05-14T00:00:00Z"
}
```

