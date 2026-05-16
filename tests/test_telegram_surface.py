from __future__ import annotations

from pathlib import Path

import telegram.bot as telegram_bot
from telegram.commands import parse_command


def test_parse_command_maps_help_and_query():
    assert parse_command("/help").name == "help"
    assert parse_command("What is the budget?").name == "query"
    assert parse_command("/ask budget status").args["question"] == "budget status"


def test_parse_command_handles_reindex_flags():
    cmd = parse_command("/reindex partial reports/report.md meetings/minutes.md")
    assert cmd.name == "reindex"
    assert cmd.args["full_reindex"] is False
    assert cmd.args["files"] == ["reports/report.md", "meetings/minutes.md"]


def test_bot_surface_routes_to_api_and_saves_uploads(tmp_path: Path, monkeypatch):
    bot = telegram_bot.TelegramBotSurface(api_base_url="http://example.invalid", inbox_root=tmp_path / "inbox")
    called = {}

    def fake_post(self, path, payload):
        called["path"] = path
        called["payload"] = payload
        return {
            "answer": "Budget is allocated",
            "sources": [{"file": "accounts/budget.md", "chunk": "Budget is allocated"}],
        }

    monkeypatch.setattr(telegram_bot.TelegramBotSurface, "_post_json", fake_post)
    response = bot.query("What is the budget?", category="accounts", rerank=True)

    assert called["path"] == "/query"
    assert called["payload"]["question"] == "What is the budget?"
    assert called["payload"]["filters"]["category"] == "accounts"
    assert called["payload"]["rerank"] is True
    assert "Sources:" in response.message

    upload = bot.handle_upload("briefing.pdf", b"PDF bytes")
    assert upload.status == "ok"
    assert (tmp_path / "inbox" / "briefing.pdf").exists()


def test_bot_surface_health_and_reindex(tmp_path: Path, monkeypatch):
    bot = telegram_bot.TelegramBotSurface(api_base_url="http://example.invalid", inbox_root=tmp_path / "inbox")

    monkeypatch.setattr(telegram_bot.requests, "get", lambda url, timeout=30: type("R", (), {"json": lambda self: {"status": "healthy", "chromadb": "connected", "ollama": "running", "indexed_documents": 9}})())
    monkeypatch.setattr(telegram_bot.TelegramBotSurface, "_post_json", lambda self, path, payload: {"status": "completed", "files_indexed": 2, "chunks_created": 4})

    health = bot.get_health()
    reindex = bot.reindex(full_reindex=False, files=["reports/report.md"])

    assert health.status == "healthy"
    assert "indexed_documents: 9" in health.message
    assert reindex.status == "completed"
    assert "files_indexed: 2" in reindex.message

