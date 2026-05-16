from __future__ import annotations

import chromadb

from core.config import CHROMA_PATH
from embeddings.embedder import load_embedding_model

_vector_db = None


def initialise_system():
    global _vector_db

    print("AVINYA AI Initialising...")

    print("Loading embedding engine...")
    load_embedding_model()

    print("Loading knowledge base...")
    _vector_db = chromadb.PersistentClient(path=CHROMA_PATH)

    print("System Ready\n")

    return _vector_db
