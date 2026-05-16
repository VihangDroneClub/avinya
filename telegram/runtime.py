from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

from converters.base_converter import ConversionError
from core.config import (
    ARCHIVE_PATH,
    INBOX_PATH,
    TELEGRAM_ALLOWED_CHAT_IDS,
    TELEGRAM_API_BASE_URL,
    TELEGRAM_BOT_TOKEN,
    VAULT_PATH,
)
from processors.processor import process_file
from telegram.bot import TelegramBotSurface


def parse_allowed_chat_ids(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()

    ids: list[int] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            ids.append(int(value))
        except ValueError as exc:
            raise ValueError(f"Invalid chat id: {value}") from exc
    return tuple(ids)


def is_chat_allowed(chat_id: int, allowed_chat_ids: Iterable[int]) -> bool:
    allowed = tuple(allowed_chat_ids)
    return not allowed or chat_id in allowed


def build_upload_message(markdown_path: Path, archive_path: Path, indexed_chunks: int) -> str:
    return (
        f"Processed: {markdown_path.name}\n"
        f"Saved: {markdown_path}\n"
        f"Archived: {archive_path.name}\n"
        f"Indexed chunks: {indexed_chunks}"
    )


def validate_bot_token(token: str) -> str:
    value = (token or "").strip()
    if not value:
        raise RuntimeError("AVINYA_TELEGRAM_BOT_TOKEN is not set")
    if value == "..." or ":" not in value:
        raise RuntimeError(
            "AVINYA_TELEGRAM_BOT_TOKEN must be a real BotFather token in the form <digits>:<secret>"
        )
    return value


@dataclass(slots=True)
class TelegramRuntime:
    token: str
    api_base_url: str = TELEGRAM_API_BASE_URL
    inbox_root: Path = Path(INBOX_PATH)
    vault_root: Path = Path(VAULT_PATH)
    archive_root: Path = Path(ARCHIVE_PATH)
    allowed_chat_ids: tuple[int, ...] = TELEGRAM_ALLOWED_CHAT_IDS

    def build_surface(self) -> TelegramBotSurface:
        return TelegramBotSurface(api_base_url=self.api_base_url, inbox_root=self.inbox_root)

    def run(self) -> None:
        self.token = validate_bot_token(self.token)

        import telebot

        bot = telebot.TeleBot(self.token)
        surface = self.build_surface()

        def gate(message) -> bool:
            chat_id = getattr(getattr(message, "chat", None), "id", None)
            return chat_id is not None and is_chat_allowed(int(chat_id), self.allowed_chat_ids)

        def deny(message) -> None:
            bot.reply_to(message, "Access denied.")

        @bot.message_handler(commands=["start"])
        def on_start(message) -> None:
            if not gate(message):
                return deny(message)
            bot.reply_to(message, "Vihang bot is ready.")

        @bot.message_handler(commands=["help"])
        def on_help(message) -> None:
            if not gate(message):
                return deny(message)
            bot.reply_to(message, surface.handle_text("/help").message)

        @bot.message_handler(commands=["health"])
        def on_health(message) -> None:
            if not gate(message):
                return deny(message)
            bot.reply_to(message, surface.get_health().message)

        @bot.message_handler(commands=["reindex"])
        def on_reindex(message) -> None:
            if not gate(message):
                return deny(message)
            command = surface.handle_text(message.text or "")
            bot.reply_to(message, command.message)

        @bot.message_handler(commands=["graph"])
        def on_graph(message) -> None:
            if not gate(message):
                return deny(message)
            try:
                report_path = Path(__file__).parent.parent / "CKB" / "GRAPH_REPORT.md"
                if report_path.exists():
                    content = report_path.read_text(encoding="utf-8")
                    # Send up to 3000 chars
                    summary = content[:3000] + "\n\n... (view full report in Obsidian)"
                    bot.reply_to(message, summary)
                else:
                    bot.reply_to(message, "Knowledge graph report not found. Run /reindex first.")
            except Exception as e:
                bot.reply_to(message, f"Error reading graph report: {e}")

        @bot.message_handler(content_types=["document"])
        def on_document(message) -> None:
            if not gate(message):
                return deny(message)

            document = message.document
            if document is None:
                bot.reply_to(message, "No document received.")
                return

            file_info = bot.get_file(document.file_id)
            file_bytes = bot.download_file(file_info.file_path)
            filename = document.file_name or Path(file_info.file_path).name
            saved_path = surface.save_upload(filename, file_bytes)

            try:
                result = process_file(saved_path, self.vault_root, self.archive_root)
            except ConversionError as exc:
                bot.reply_to(message, f"Processing failed: {exc}")
                return

            bot.reply_to(
                message,
                build_upload_message(result.markdown_path, result.archive_path, result.indexed_chunks),
            )

        @bot.message_handler(content_types=["text"])
        def on_text(message) -> None:
            if not gate(message):
                return deny(message)
            response = surface.handle_text(message.text or "")
            bot.reply_to(message, response.message)

        while True:
            try:
                bot.infinity_polling(
                    timeout=60,
                    long_polling_timeout=60,
                    skip_pending=True,
                    allowed_updates=["message"],
                )
                break
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError, TimeoutError):
                time.sleep(5)
                continue
            except KeyboardInterrupt:
                break


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Avinya Telegram bot")
    parser.add_argument("--token", default=TELEGRAM_BOT_TOKEN, help="Telegram bot token")
    parser.add_argument("--api-base-url", default=TELEGRAM_API_BASE_URL, help="RAG API base URL")
    parser.add_argument("--inbox", default=INBOX_PATH, help="Inbox directory")
    parser.add_argument("--vault", default=VAULT_PATH, help="Vault directory")
    parser.add_argument("--archive", default=ARCHIVE_PATH, help="Archive directory")
    parser.add_argument(
        "--allowed-chat-ids",
        default=",".join(str(item) for item in TELEGRAM_ALLOWED_CHAT_IDS),
        help="Comma-separated Telegram chat IDs allowed to use the bot",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runtime = TelegramRuntime(
        token=validate_bot_token(args.token),
        api_base_url=args.api_base_url,
        inbox_root=Path(args.inbox).expanduser(),
        vault_root=Path(args.vault).expanduser(),
        archive_root=Path(args.archive).expanduser(),
        allowed_chat_ids=parse_allowed_chat_ids(args.allowed_chat_ids),
    )
    runtime.run()
    return 0
