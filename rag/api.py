from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from core.config import VAULT_PATH
from llm.ollama_adapter import OllamaError, check_ollama, generate_text
from llm.router import choose_model
from prompts.system_prompt import SYSTEM_PROMPT
from rag.indexer import CHUNKS_CREATED, FILES_INDEXED, LAST_REINDEX, ReindexResult, collection, reindex_vault
from rag.retriever import retrieve_query_context
from rag.types import QueryResult, SourceChunk

app = FastAPI(title="Vihang RAG API", version="1.0")


class QueryFilters(BaseModel):
    category: str | None = None
    date_range: list[str] | None = None


class QueryRequest(BaseModel):
    question: str
    filters: QueryFilters | None = None
    max_results: int = Field(default=5, ge=1, le=20)
    rerank: bool = False


class SourceChunkResponse(BaseModel):
    file: str
    chunk: str
    relevance_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunkResponse]
    query_time: float


class ReindexRequest(BaseModel):
    full_reindex: bool = True
    files: list[str] | None = None


class ReindexResponse(BaseModel):
    status: str
    files_indexed: int
    chunks_created: int
    time_elapsed: float


class HealthResponse(BaseModel):
    status: str
    chromadb: str
    ollama: str
    indexed_documents: int
    last_reindex: str | None


class StatsResponse(BaseModel):
    status: str
    files_indexed: int
    chunks_created: int
    indexed_documents: int
    last_reindex: str | None


class RootResponse(BaseModel):
    name: str
    version: str
    status: str
    endpoints: list[str]


def _filters_payload(filters: QueryFilters | None) -> dict[str, Any] | None:
    if filters is None:
        return None
    payload = filters.model_dump(exclude_none=True)
    return payload or None


def _build_prompt(question: str, kb_text: str) -> str:
    parts = [SYSTEM_PROMPT]
    if kb_text.strip():
        parts.append("\n## Knowledge Base (retrieved passages)\n" + kb_text.strip())
    else:
        parts.append("\n## Knowledge Base (retrieved passages)\n(No matching passages in the index for this query.)")
    parts.append("\n## Current user message\n" + question.strip())
    parts.append("\n## Assistant (respond now)\n")
    return "\n".join(parts)


@app.get("/", response_model=RootResponse)
def root_endpoint() -> RootResponse:
    return RootResponse(
        name="Vihang RAG API",
        version="1.0",
        status="ok",
        endpoints=["/query", "/reindex", "/health", "/stats"],
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon_endpoint() -> Response:
    return Response(status_code=204)


def answer_question(
    question: str,
    filters: dict[str, Any] | None = None,
    max_results: int = 5,
    rerank: bool = False,
) -> QueryResponse:
    started = datetime.now()
    retrieval = retrieve_query_context(question, filters=filters, max_results=max_results, rerank=rerank)
    prompt = _build_prompt(question, retrieval.answer_context)
    model = choose_model(question)
    try:
        answer = generate_text(prompt, model=model).strip()
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    sources = [
        SourceChunkResponse(
            file=src.source,
            chunk=src.chunk,
            relevance_score=src.relevance_score,
            metadata=src.metadata or {},
        )
        for src in retrieval.sources
    ]
    return QueryResponse(answer=answer, sources=sources, query_time=round((datetime.now() - started).total_seconds(), 3))


@app.post("/query", response_model=QueryResponse)
def query_endpoint(request: QueryRequest) -> QueryResponse:
    return answer_question(
        request.question,
        _filters_payload(request.filters),
        request.max_results,
        request.rerank,
    )


@app.post("/reindex", response_model=ReindexResponse)
def reindex_endpoint(request: ReindexRequest) -> ReindexResponse:
    import sys
    import subprocess
    from pathlib import Path
    try:
        project_root = Path(__file__).parent.parent
        script = project_root / "scripts" / "update_graph.py"
        if script.exists():
            subprocess.run([sys.executable, str(script)], check=True, capture_output=True)
    except Exception as e:
        print(f"Warning: Failed to update graph: {e}")

    files = request.files if not request.full_reindex else None
    result: ReindexResult = reindex_vault(VAULT_PATH, files=files)
    return ReindexResponse(
        status=result.status,
        files_indexed=result.files_indexed,
        chunks_created=result.chunks_created,
        time_elapsed=result.time_elapsed,
    )


@app.get("/health", response_model=HealthResponse)
def health_endpoint() -> HealthResponse:
    chroma_status = "connected"
    indexed_documents = 0
    try:
        indexed_documents = collection.count()
    except Exception:
        chroma_status = "unhealthy"

    ollama_status = "running"
    try:
        check_ollama()
    except OllamaError:
        ollama_status = "unhealthy"

    return HealthResponse(
        status="healthy" if chroma_status == "connected" and ollama_status == "running" else "degraded",
        chromadb=chroma_status,
        ollama=ollama_status,
        indexed_documents=indexed_documents,
        last_reindex=LAST_REINDEX,
    )


@app.get("/stats", response_model=StatsResponse)
def stats_endpoint() -> StatsResponse:
    try:
        indexed_documents = collection.count()
    except Exception:
        indexed_documents = 0
    return StatsResponse(
        status="ok",
        files_indexed=FILES_INDEXED,
        chunks_created=CHUNKS_CREATED,
        indexed_documents=indexed_documents,
        last_reindex=LAST_REINDEX,
    )
