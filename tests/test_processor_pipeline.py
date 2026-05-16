from __future__ import annotations

from pathlib import Path

from converters.base_converter import ConversionResult
from processors.archiver import archive_processed_file
from processors.processor import index_markdown_file, process_file
from processors.watcher import process_inbox_once, scan_inbox


class _StubConverter:
    def __init__(self, response: ConversionResult):
        self.response = response

    def convert(self, file_path, output_dir):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        self.response.markdown_path = output_dir / "sample.md"
        self.response.markdown_path.write_text(self.response.content, encoding="utf-8")
        return self.response


class _StubCollection:
    def __init__(self):
        self.deleted = []
        self.added = []

    def delete(self, where=None):
        self.deleted.append(where)

    def add(self, ids, documents, embeddings, metadatas):
        self.added.append(
            {
                "ids": ids,
                "documents": documents,
                "embeddings": embeddings,
                "metadatas": metadatas,
            }
        )


def test_scan_inbox_filters_supported_files(tmp_path: Path):
    (tmp_path / "b.docx").write_text("x", encoding="utf-8")
    (tmp_path / "a.pdf").write_text("x", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")

    files = scan_inbox(tmp_path)

    assert [p.name for p in files] == ["a.pdf", "b.docx"]


def test_archive_processed_file_moves_into_dated_folder(tmp_path: Path):
    source = tmp_path / "report.pdf"
    source.write_text("x", encoding="utf-8")

    archived = archive_processed_file(source, tmp_path / "archive")

    assert archived.exists()
    assert archived.parent.parent.name == "archive"
    assert not source.exists()


def test_process_file_converts_archives_and_indexes(tmp_path: Path, monkeypatch):
    source = tmp_path / "report.pdf"
    source.write_text("original", encoding="utf-8")
    vault = tmp_path / "vault"
    archive = tmp_path / "archive"
    collection = _StubCollection()

    response = ConversionResult(markdown_path=None, metadata={"source_file": "report.pdf"}, content="# Report\n\nHello")
    stub = _StubConverter(response)

    monkeypatch.setattr("processors.processor.ConverterFactory.get_converter", lambda _source: stub)
    result = process_file(source, vault, archive, collection=collection)

    assert result.status == "success"
    assert result.markdown_path.exists()
    assert result.archive_path.exists()
    assert result.indexed is True
    assert result.indexed_chunks == 1
    assert collection.added


def test_index_markdown_file_adds_chunks(tmp_path: Path):
    markdown = tmp_path / "note.md"
    markdown.write_text("# Note\n\nHello world", encoding="utf-8")
    collection = _StubCollection()

    chunks = index_markdown_file(markdown, collection=collection)

    assert chunks == 1
    assert collection.deleted == [{"stem": "note"}]
    assert collection.added[0]["metadatas"][0]["source"].endswith("note.md")


def test_index_markdown_file_preserves_frontmatter_metadata(tmp_path: Path):
    markdown = tmp_path / "budget.md"
    markdown.write_text(
        """---
title: Budget 2025
source: budget.xlsx
category: accounts
created_at: 2026-05-14T00:00:00Z
---

# Budget 2025

Hello world
""".strip(),
        encoding="utf-8",
    )
    collection = _StubCollection()

    chunks = index_markdown_file(markdown, collection=collection)

    assert chunks == 1
    meta = collection.added[0]["metadatas"][0]
    assert meta["category"] == "accounts"
    assert meta["created_at"] == "2026-05-14T00:00:00Z"
    assert meta["source"] == "budget.xlsx"
