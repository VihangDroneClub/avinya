from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class BotCommand:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BotResponse:
    status: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)


def parse_command(text: str) -> BotCommand:
    raw = (text or "").strip()
    if not raw:
        return BotCommand(name="empty")

    parts = raw.split()
    head = parts[0].lower()
    args = parts[1:]

    if head in ("/start", "start"):
        return BotCommand(name="start")
    if head in ("/help", "help", "?"):
        return BotCommand(name="help")
    if head in ("/health", "health", "status"):
        return BotCommand(name="health")
    if head in ("/reindex", "reindex"):
        full_reindex = True
        files: list[str] = []
        for item in args:
            if item.lower() in ("--partial", "partial"):
                full_reindex = False
                continue
            files.append(item)
        return BotCommand(name="reindex", args={"full_reindex": full_reindex, "files": files or None})
    if head in ("/ask", "ask", "/query", "query"):
        return BotCommand(name="query", args={"question": " ".join(args).strip()})

    return BotCommand(name="query", args={"question": raw})


def format_help_message() -> str:
    return (
        "Commands:\n"
        "/ask <question> - query the knowledge base\n"
        "/health - check API and index status\n"
        "/reindex [files...] - rebuild the index\n"
        "Any other text is treated as a query."
    )

