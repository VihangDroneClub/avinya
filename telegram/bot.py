from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from core.config import INBOX_PATH, TELEGRAM_API_BASE_URL
from telegram.commands import BotCommand, BotResponse, format_help_message, parse_command


@dataclass(slots=True)
class TelegramBotSurface:
    api_base_url: str = TELEGRAM_API_BASE_URL
    inbox_root: Path = Path(INBOX_PATH)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.api_base_url.rstrip('/')}{path}"
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def handle_text(self, text: str) -> BotResponse:
        command = parse_command(text)
        return self.dispatch(command)

    def dispatch(self, command: BotCommand) -> BotResponse:
        if command.name == "empty":
            return BotResponse(status="ignored", message="Empty message")
        if command.name == "start":
            return BotResponse(status="ok", message="Vihang bot ready")
        if command.name == "help":
            return BotResponse(status="ok", message=format_help_message())
        if command.name == "health":
            return self.get_health()
        if command.name == "reindex":
            return self.reindex(command.args.get("full_reindex", True), command.args.get("files"))
        if command.name == "query":
            return self.query(command.args.get("question", ""))
        return BotResponse(status="error", message=f"Unsupported command: {command.name}")

    def query(self, question: str, *, category: str | None = None, date_range: list[str] | None = None, max_results: int = 5, rerank: bool = False) -> BotResponse:
        payload: dict[str, Any] = {"question": question, "max_results": max_results, "rerank": rerank}
        filters: dict[str, Any] = {}
        if category:
            filters["category"] = category
        if date_range:
            filters["date_range"] = date_range
        if filters:
            payload["filters"] = filters

        data = self._post_json("/query", payload)
        sources = data.get("sources") or []
        source_text = "\n".join(f"- {item.get('file')}: {item.get('chunk')}" for item in sources[:3])
        message = data.get("answer", "")
        if source_text:
            message = f"{message}\n\nSources:\n{source_text}"
        return BotResponse(status="ok", message=message, data=data)

    def get_health(self) -> BotResponse:
        data = requests.get(f"{self.api_base_url.rstrip('/')}/health", timeout=30).json()
        status = data.get("status", "unknown")
        message = (
            f"status: {status}\n"
            f"chromadb: {data.get('chromadb')}\n"
            f"ollama: {data.get('ollama')}\n"
            f"indexed_documents: {data.get('indexed_documents')}"
        )
        return BotResponse(status=status, message=message, data=data)

    def reindex(self, full_reindex: bool = True, files: list[str] | None = None) -> BotResponse:
        payload: dict[str, Any] = {"full_reindex": full_reindex}
        if files:
            payload["files"] = files
        data = self._post_json("/reindex", payload)
        message = (
            f"reindex: {data.get('status')}\n"
            f"files_indexed: {data.get('files_indexed')}\n"
            f"chunks_created: {data.get('chunks_created')}"
        )
        return BotResponse(status=data.get("status", "ok"), message=message, data=data)

    def save_upload(self, filename: str, content: bytes) -> Path:
        self.inbox_root.mkdir(parents=True, exist_ok=True)
        path = self.inbox_root / filename
        if path.exists():
            suffix = path.suffix
            stem = path.stem
            counter = 1
            while True:
                candidate = self.inbox_root / f"{stem}_{counter}{suffix}"
                if not candidate.exists():
                    path = candidate
                    break
                counter += 1
        path.write_bytes(content)
        return path

    def handle_upload(self, filename: str, content: bytes) -> BotResponse:
        path = self.save_upload(filename, content)
        return BotResponse(
            status="ok",
            message=f"saved upload: {path.name}",
            data={"saved_path": str(path), "inbox_root": str(self.inbox_root)},
        )
