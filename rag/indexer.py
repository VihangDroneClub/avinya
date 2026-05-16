from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chromadb

from core.config import CHROMA_PATH, COLLECTION_NAME
from processors.processor import index_markdown_file

client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(COLLECTION_NAME)

LAST_REINDEX: str | None = None
FILES_INDEXED: int = 0
CHUNKS_CREATED: int = 0


@dataclass(slots=True)
class ReindexResult:
    status: str
    files_indexed: int
    chunks_created: int
    time_elapsed: float
    last_reindex: str


def _iter_markdown_files(vault_root: str | Path) -> list[Path]:
    root = Path(vault_root)
    candidates = []
    if root.exists():
        candidates.extend(p for p in root.rglob("*.md") if p.is_file())
        
    project_root = Path(__file__).parent.parent
    ckb = project_root / "CKB"
    if ckb.exists():
        candidates.extend(p for p in ckb.rglob("*.md") if p.is_file())
        
    kv = project_root / "knowledge_vault"
    if kv.exists():
        candidates.extend(p for p in kv.rglob("*.md") if p.is_file())
        
    return sorted(list(set(candidates)))


def _clear_collection(active_collection) -> None:
    try:
        existing = active_collection.get()
    except Exception:
        return
    ids = existing.get("ids") or []
    if ids:
        active_collection.delete(ids=ids)


def reindex_vault(
    vault_root: str | Path,
    *,
    files: list[str | Path] | None = None,
    active_collection=None,
) -> ReindexResult:
    from time import perf_counter

    global LAST_REINDEX, FILES_INDEXED, CHUNKS_CREATED

    started = perf_counter()
    active_collection = active_collection or collection
    _clear_collection(active_collection)

    if files:
        root = Path(vault_root)
        candidates = []
        for item in files:
            candidate = Path(item)
            if not candidate.is_absolute():
                candidate = root / candidate
            candidates.append(candidate)
    else:
        candidates = _iter_markdown_files(vault_root)

    files_indexed = 0
    chunks_created = 0
    for md_file in candidates:
        if not md_file.exists():
            continue
        files_indexed += 1
        chunks_created += index_markdown_file(md_file, collection=active_collection)

    LAST_REINDEX = datetime.now(timezone.utc).isoformat()
    FILES_INDEXED = files_indexed
    CHUNKS_CREATED = chunks_created
    return ReindexResult(
        status="completed",
        files_indexed=files_indexed,
        chunks_created=chunks_created,
        time_elapsed=round(perf_counter() - started, 3),
        last_reindex=LAST_REINDEX,
    )
