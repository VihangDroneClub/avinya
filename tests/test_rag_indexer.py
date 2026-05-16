from __future__ import annotations

from pathlib import Path

import rag.indexer as rag_indexer


class _StubCollection:
    def __init__(self):
        self.deleted = []
        self.got = False

    def get(self):
        self.got = True
        return {"ids": ["a", "b"]}

    def delete(self, ids=None, where=None):
        self.deleted.append({"ids": ids, "where": where})


def test_reindex_vault_uses_vault_relative_paths(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    markdown = vault / "reports" / "report.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# Report\n\nHello world", encoding="utf-8")

    stub_collection = _StubCollection()
    indexed = []

    def fake_index(path, collection=None):
        indexed.append(Path(path))
        return 2

    monkeypatch.setattr(rag_indexer, "collection", stub_collection)
    monkeypatch.setattr(rag_indexer, "index_markdown_file", fake_index)

    result = rag_indexer.reindex_vault(vault, files=["reports/report.md"], active_collection=stub_collection)

    assert result.files_indexed == 1
    assert result.chunks_created == 2
    assert indexed == [markdown]
    assert stub_collection.deleted == [{"ids": ["a", "b"], "where": None}]

