from __future__ import annotations

from core.config import MODEL_DEFAULT, MODEL_REASONING


def choose_model(prompt: str) -> str:
    reasoning_keywords = [
        "derive",
        "calculate",
        "equation",
        "solve",
        "proof",
        "algorithm",
        "optimize",
        "analysis",
        "prove",
        "integrate",
        "differentiate",
        "theorem",
        "complexity",
    ]

    p = prompt.lower()
    for word in reasoning_keywords:
        if word in p:
            return MODEL_REASONING
    return MODEL_DEFAULT
