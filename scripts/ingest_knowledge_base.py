"""Ingest the knowledge_base/ directory into Avinya's vault and index it."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
KB_DIR = _ROOT / "knowledge_base"
VAULT_DIR = _ROOT / "vihang_data" / "vault"


def ingest_knowledge_base() -> None:
    if not KB_DIR.exists():
        print("No knowledge_base/ directory found.")
        return

    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    copied = 0
    for src in KB_DIR.rglob("*"):
        if src.is_file():
            dest = VAULT_DIR / src.name
            shutil.copy2(src, dest)
            copied += 1
            print(f"  Copied: {src.name}")

    print(f"\nCopied {copied} files to vault. Reindexing...")

    sys.path.insert(0, str(_ROOT))
    from rag.indexer import reindex_vault
    result = reindex_vault(str(VAULT_DIR))
    print(f"Indexed {result.files_indexed} files, created {result.chunks_created} chunks.")
    print(f"Time: {result.time_elapsed:.2f}s")


if __name__ == "__main__":
    ingest_knowledge_base()
