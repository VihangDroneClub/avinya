"""Overlapping text segments for embedding and retrieval."""


def chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= max_chars:
        return [t]
    step = max(1, max_chars - overlap)
    return [t[i : i + max_chars] for i in range(0, len(t), step)]
