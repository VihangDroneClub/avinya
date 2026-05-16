from __future__ import annotations

import chromadb
from pathlib import Path

from core.config import CHROMA_PATH, CHUNK_MAX_CHARS, CHUNK_OVERLAP, COLLECTION_NAME
from embeddings.embedder import generate_embeddings, load_embedding_model
from utils.chunking import chunk_text

client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(name=COLLECTION_NAME)
CKB_PATH = Path("CKB")

existing = collection.get()
if existing.get("ids"):
    collection.delete(ids=existing["ids"])

load_embedding_model()

for filepath in sorted(CKB_PATH.rglob("*.md")):
    rel = filepath.relative_to(CKB_PATH)
    stem = str(rel.with_suffix("")).replace("/", "__").replace("\\", "__")

    text = filepath.read_text(encoding="utf-8")
    chunks = chunk_text(text, CHUNK_MAX_CHARS, CHUNK_OVERLAP)
    if not chunks:
        continue

    embeddings = generate_embeddings(chunks)
    ids = [f"{stem}#{i}" for i in range(len(chunks))]
    rel_display = str(rel).replace("\\", "/")
    metadatas = [{"source": rel_display, "stem": stem, "chunk_index": str(i)} for i in range(len(chunks))]

    collection.add(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)
    print(f"Added: {stem} ({len(chunks)} chunks)")

print("Final document count:", collection.count())
