"""Central settings; override with environment variables."""

from __future__ import annotations

import os


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Ollama (full URL to /api/generate)
OLLAMA_GENERATE_URL: str = os.environ.get(
    "OLLAMA_GENERATE_URL",
    os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate"),
)

OLLAMA_TIMEOUT_CONNECT: int = _i("OLLAMA_TIMEOUT_CONNECT", 15)
OLLAMA_TIMEOUT_READ: int = _i("OLLAMA_TIMEOUT_READ", 600)

# Models (pull these in Ollama)
MODEL_DEFAULT: str = os.environ.get("AVINYA_MODEL_DEFAULT", "gemma2:2b-instruct-q4_K_M")
MODEL_REASONING: str = os.environ.get("AVINYA_MODEL_REASONING", "hermes3:8b-llama3.1-q4_K_M")
MODEL_SUMMARY: str = os.environ.get("AVINYA_MODEL_SUMMARY", MODEL_DEFAULT)

# Chroma
CHROMA_PATH: str = os.environ.get("AVINYA_CHROMA_PATH", "./chroma_db")
COLLECTION_NAME: str = os.environ.get("AVINYA_COLLECTION", "club_knowledge_base")

# Data roots
INBOX_PATH: str = os.environ.get("AVINYA_INBOX_PATH", "./vihang_data/inbox")
VAULT_PATH: str = os.environ.get("AVINYA_VAULT_PATH", "./vihang_data/vault")
ARCHIVE_PATH: str = os.environ.get("AVINYA_ARCHIVE_PATH", "./vihang_data/archive")

# Telegram / bot surface
TELEGRAM_BOT_TOKEN: str = os.environ.get("AVINYA_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API_BASE_URL: str = os.environ.get("AVINYA_RAG_API_URL", "http://127.0.0.1:8000")
TELEGRAM_ALLOWED_CHAT_IDS: tuple[int, ...] = tuple(
    int(item.strip())
    for item in os.environ.get("AVINYA_TELEGRAM_ALLOWED_CHAT_IDS", "").split(",")
    if item.strip().lstrip("-").isdigit()
)

# Ingest / chunking
CHUNK_MAX_CHARS: int = _i("AVINYA_CHUNK_CHARS", 900)
CHUNK_OVERLAP: int = _i("AVINYA_CHUNK_OVERLAP", 120)

# Retrieval
RETRIEVAL_CANDIDATE_K: int = _i("AVINYA_RETRIEVAL_CANDIDATES", 12)
RETRIEVAL_TOP_K: int = _i("AVINYA_RETRIEVAL_TOP_K", 5)
DISTANCE_SLACK_L2: float = _f("AVINYA_DISTANCE_SLACK", 0.45)
MMR_LAMBDA: float = _f("AVINYA_MMR_LAMBDA", 0.55)
KB_CONTEXT_MAX_TOKENS: int = _i("AVINYA_KB_MAX_TOKENS", 3800)

# Session
SESSION_MAX_TURNS: int = _i("AVINYA_SESSION_MAX_TURNS", 8)
SUMMARY_TOKEN_BUDGET: int = _i("AVINYA_SUMMARY_MAX_TOKENS", 600)
# After this many user messages, compress dialogue into long-term summary (0 = off)
AUTO_SUMMARIZE_EVERY: int = _i("AVINYA_AUTO_SUMMARIZE_EVERY", 6)
