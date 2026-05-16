from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

import chromadb
import yaml

from converters.base_converter import ConversionError
from converters.converter_factory import ConverterFactory
from core.config import CHROMA_PATH, CHUNK_MAX_CHARS, CHUNK_OVERLAP, COLLECTION_NAME
from embeddings.embedder import generate_embeddings, load_embedding_model
from processors.categorizer import categorize_document
from processors.archiver import archive_processed_file
from processors.formatter import format_markdown_document
from utils.chunking import chunk_text

_client = chromadb.PersistentClient(path=CHROMA_PATH)
_collection = _client.get_or_create_collection(name=COLLECTION_NAME)


@dataclass(slots=True)
class ProcessResult:
    source_file: Path
    markdown_path: Path
    archive_path: Path
    indexed_chunks: int
    archived: bool
    indexed: bool
    status: str
    metadata: dict[str, Any]


def _stem_for(source: Path) -> str:
    return source.stem


def _parse_frontmatter(text: str) -> dict[str, Any]:
    stripped = (text or "").lstrip()
    if not stripped.startswith("---"):
        return {}

    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return {}

    block = "\n".join(lines[1:end_index]).strip()
    if not block:
        return {}
    data = yaml.safe_load(block) or {}
    return data if isinstance(data, dict) else {}


def _format_frontmatter_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        text = value.isoformat()
        return text.replace("+00:00", "Z")
    return str(value)


def index_markdown_file(markdown_path: str | Path, collection=None) -> int:
    path = Path(markdown_path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return 0

    load_embedding_model()
    chunks = chunk_text(text, CHUNK_MAX_CHARS, CHUNK_OVERLAP)
    if not chunks:
        return 0

    active_collection = collection or _collection
    stem = _stem_for(path)
    frontmatter = _parse_frontmatter(text)
    source_name = _format_frontmatter_value(frontmatter.get("source")) or path.as_posix()
    category = _format_frontmatter_value(frontmatter.get("category"))
    created_at = _format_frontmatter_value(frontmatter.get("created_at"))

    try:
        active_collection.delete(where={"stem": stem})
    except Exception:
        pass

    embeddings = generate_embeddings(chunks)
    ids = [f"{stem}#{i}" for i in range(len(chunks))]
    metadatas = []
    for i in range(len(chunks)):
        meta: dict[str, Any] = {"source": source_name, "stem": stem, "chunk_index": str(i)}
        if category:
            meta["category"] = category
        if created_at:
            meta["created_at"] = created_at
        metadatas.append(meta)
    active_collection.add(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)
    return len(chunks)


def process_file(
    input_path: str | Path,
    vault_root: str | Path,
    archive_root: str | Path,
    *,
    collection=None,
) -> ProcessResult:
    source = Path(input_path)
    if not source.exists():
        raise ConversionError(f"Input file not found: {source}")

    vault = Path(vault_root)
    archive = Path(archive_root)
    vault.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)

    started = perf_counter()
    converter = ConverterFactory.get_converter(source)
    conversion = converter.convert(source, vault)
    if conversion.markdown_path is None:
        raise ConversionError(f"Converter did not return a markdown path for {source.name}")

    category_match = categorize_document(source_name=source.name, content=conversion.content)
    formatted_markdown = format_markdown_document(
        body=conversion.content,
        source_name=source.name,
        title=conversion.metadata.get("title") or source.stem,
        category=category_match.category,
        metadata={
            "conversion_method": conversion.metadata.get("conversion_method", "unknown"),
            "source_file": source.name,
            "score": round(category_match.score, 3),
            "matched_terms": ",".join(category_match.matched_terms) if category_match.matched_terms else "",
        },
    )
    conversion.markdown_path.write_text(formatted_markdown, encoding="utf-8")

    archived_path = archive_processed_file(source, archive)
    indexed_chunks = index_markdown_file(conversion.markdown_path, collection=collection)

    metadata = dict(conversion.metadata)
    metadata.update(
        {
            "source_file": source.name,
            "category": category_match.category,
            "category_score": round(category_match.score, 3),
            "matched_terms": category_match.matched_terms,
            "archive_path": str(archived_path),
            "indexed_chunks": indexed_chunks,
            "processing_time": round(perf_counter() - started, 3),
        }
    )

    return ProcessResult(
        source_file=source,
        markdown_path=conversion.markdown_path,
        archive_path=archived_path,
        indexed_chunks=indexed_chunks,
        archived=True,
        indexed=indexed_chunks > 0,
        status="success",
        metadata=metadata,
    )
