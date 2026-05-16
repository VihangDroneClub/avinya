from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chromadb
import numpy as np

from core.config import (
    CHROMA_PATH,
    COLLECTION_NAME,
    DISTANCE_SLACK_L2,
    KB_CONTEXT_MAX_TOKENS,
    MMR_LAMBDA,
    RETRIEVAL_CANDIDATE_K,
    RETRIEVAL_TOP_K,
)
from embeddings.embedder import generate_embedding
from rag.types import QueryResult, SourceChunk
from rag.reranker import rerank_sources
from utils.mmr import maximal_marginal_relevance
from utils.token_manager import trim_to_budget

client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(COLLECTION_NAME)


def _where_clause(filters: dict[str, Any] | None) -> dict[str, Any] | None:
    if not filters:
        return None

    clauses: dict[str, Any] = {}
    category = filters.get("category")
    if category:
        clauses["category"] = {"$eq": str(category)}

    date_range = filters.get("date_range") or []
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start, end = date_range
        if start or end:
            clauses["created_at"] = {}
            if start:
                clauses["created_at"]["$gte"] = str(start)
            if end:
                clauses["created_at"]["$lte"] = str(end)

    return clauses or None

def _expand_context_with_graph(sources: list[SourceChunk]) -> str:
    project_root = Path(__file__).parent.parent
    graph_path = project_root / "CKB" / "graph.json"
    if not graph_path.exists():
        return ""
    
    try:
        with open(graph_path, "r", encoding="utf-8") as f:
            graph_data = json.load(f)
    except Exception:
        return ""
        
    nodes = {n["id"]: n for n in graph_data.get("nodes", [])}
    edges = graph_data.get("edges", [])
    
    adj = {}
    for e in edges:
        s, t, r = e.get("source"), e.get("target"), e.get("relation")
        if s not in adj: adj[s] = []
        if t not in adj: adj[t] = []
        adj[s].append((t, r, "out"))
        adj[t].append((s, r, "in"))

    retrieved_files = {src.source for src in sources}
    active_nodes = set()
    for nid, ndata in nodes.items():
        sf = ndata.get("source_file", "")
        if sf and (sf in retrieved_files or sf.endswith(tuple("/" + rf.lstrip("/") for rf in retrieved_files if "/" in rf or rf))):
            active_nodes.add(nid)
            
    if not active_nodes:
        return ""
        
    expansions = []
    for nid in active_nodes:
        ndata = nodes[nid]
        neighbors = adj.get(nid, [])
        if not neighbors: continue
        
        related = []
        for nbr_id, rel, dir_ in neighbors:
            nbr_data = nodes.get(nbr_id)
            if not nbr_data: continue
            lbl = nbr_data.get("label", nbr_id)
            if dir_ == "out":
                related.append(f"- {rel} {lbl}")
            else:
                related.append(f"- is {rel} by {lbl}")
                
        if related:
            related_str = "\n".join(related[:10])
            if len(related) > 10:
                related_str += f"\n... and {len(related)-10} more"
            expansions.append(f"Graph context for {ndata.get('label', nid)}:\n{related_str}")
            
    if expansions:
        return "\n\n=== EXTENDED GRAPH CONTEXT ===\n" + "\n\n".join(expansions)
    return ""


def retrieve_query_context(
    query: str,
    *,
    filters: dict[str, Any] | None = None,
    max_results: int | None = None,
    rerank: bool = False,
    active_collection=None,
) -> QueryResult:
    if not (query or "").strip():
        return QueryResult(answer_context="", sources=[], source_labels="")

    collection_obj = active_collection or collection
    embedding = generate_embedding(query)

    try:
        count = collection_obj.count()
    except Exception:
        count = 0

    if count == 0:
        return QueryResult(answer_context="", sources=[], source_labels="")

    n_fetch = min(max_results or RETRIEVAL_CANDIDATE_K, count)
    results = collection_obj.query(
        query_embeddings=[embedding],
        n_results=n_fetch,
        include=["documents", "metadatas", "distances", "embeddings"],
        where=_where_clause(filters),
    )

    docs = results.get("documents") or []
    ids = results.get("ids") or []
    metas = results.get("metadatas") or []
    distances = results.get("distances")
    embs = results.get("embeddings")

    if not docs or not docs[0]:
        return QueryResult(answer_context="", sources=[], source_labels="")

    doc_list = list(docs[0])
    id_list = list(ids[0])
    meta_list = list(metas[0]) if metas and metas[0] else [{}] * len(doc_list)

    if distances is not None and len(distances) > 0 and distances[0] is not None:
        dist_list = np.asarray(distances[0], dtype=np.float64).tolist()
    else:
        dist_list = []

    emb_list: list[list[float]] = []
    if embs is not None and len(embs) > 0 and embs[0] is not None:
        arr = np.asarray(embs[0], dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        emb_list = arr.tolist()

    if dist_list and len(dist_list) == len(doc_list):
        d0 = dist_list[0]
        nd, ni, nm, ne, dists = [], [], [], [], []
        for i in range(len(doc_list)):
            if dist_list[i] <= d0 + DISTANCE_SLACK_L2:
                nd.append(doc_list[i])
                ni.append(id_list[i])
                nm.append(meta_list[i])
                dists.append(dist_list[i])
                if i < len(emb_list):
                    ne.append(emb_list[i])
        doc_list, id_list, meta_list = nd, ni, nm
        emb_list = ne if len(emb_list) == len(dist_list) else []
        dist_list = dists

    if not doc_list:
        return QueryResult(answer_context="", sources=[], source_labels="")

    if emb_list and len(emb_list) == len(doc_list):
        order = maximal_marginal_relevance(
            embedding,
            emb_list,
            k=min(max_results or RETRIEVAL_TOP_K, len(doc_list)),
            lambda_mult=MMR_LAMBDA,
        )
        doc_list = [doc_list[i] for i in order]
        id_list = [id_list[i] for i in order]
        meta_list = [meta_list[i] for i in order]
        if dist_list and len(dist_list) == len(order):
            dist_list = [dist_list[i] for i in order]
    else:
        limit = min(max_results or RETRIEVAL_TOP_K, len(doc_list))
        doc_list = doc_list[:limit]
        id_list = id_list[:limit]
        meta_list = meta_list[:limit]
        dist_list = dist_list[:limit] if dist_list else []

    seen_text: set[str] = set()
    parts: list[str] = []
    source_labels: list[str] = []
    sources: list[SourceChunk] = []

    for idx, (doc, doc_id, meta) in enumerate(zip(doc_list, id_list, meta_list)):
        if not doc or doc in seen_text:
            continue
        seen_text.add(doc)
        parts.append(doc)
        lbl = (meta or {}).get("source") or doc_id
        source_labels.append(lbl)
        score = None
        if dist_list and idx < len(dist_list):
            score = float(dist_list[idx])
        sources.append(SourceChunk(source=str(lbl), chunk=doc, relevance_score=score, metadata=meta or {}))

    if not parts:
        return QueryResult(answer_context="", sources=[], source_labels="")

    if rerank and sources:
        sources = rerank_sources(query, sources)
        parts = [src.chunk for src in sources if src.chunk]
        source_labels = []
        for src in sources:
            if src.source not in source_labels:
                source_labels.append(src.source)

    merged = "\n\n---\n\n".join(parts)
    
    # ADD GRAPH CONTEXT EXPANSION HERE
    graph_context = _expand_context_with_graph(sources)
    if graph_context:
        merged += graph_context

    merged = trim_to_budget(merged, KB_CONTEXT_MAX_TOKENS)

    seen_sources: list[str] = []
    for s in source_labels:
        if s not in seen_sources:
            seen_sources.append(s)

    return QueryResult(answer_context=merged, sources=sources, source_labels=", ".join(seen_sources))