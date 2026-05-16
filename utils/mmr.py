"""Maximal marginal relevance for diverse retrieval."""

from __future__ import annotations

import numpy as np


def maximal_marginal_relevance(
    query_embedding: list[float],
    candidate_embeddings: list[list[float]],
    k: int,
    lambda_mult: float = 0.55,
) -> list[int]:
    if not candidate_embeddings:
        return []

    q = np.asarray(query_embedding, dtype=np.float64)
    d = np.asarray(candidate_embeddings, dtype=np.float64)
    n = len(d)
    k = min(k, n)

    qn = np.linalg.norm(q) + 1e-12
    dn = np.linalg.norm(d, axis=1) + 1e-12
    sim_q = (d @ q) / (dn * qn)

    selected: list[int] = []
    remaining = set(range(n))

    first = int(np.argmax(sim_q))
    selected.append(first)
    remaining.discard(first)

    while len(selected) < k and remaining:
        best_idx = -1
        best_score = -1e9
        for i in remaining:
            rel = float(sim_q[i])
            div = max(
                float(
                    np.dot(d[i], d[j])
                    / ((np.linalg.norm(d[i]) + 1e-12) * (np.linalg.norm(d[j]) + 1e-12))
                )
                for j in selected
            )
            score = lambda_mult * rel - (1.0 - lambda_mult) * div
            if score > best_score:
                best_score = score
                best_idx = i
        selected.append(best_idx)
        remaining.discard(best_idx)

    return selected
