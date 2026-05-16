"""Shared session-memory maintenance (CLI + desktop)."""

from __future__ import annotations

from core.config import AUTO_SUMMARIZE_EVERY
from memory.session_memory import SessionMemory
from memory.summarizer import summarize_conversation


def maybe_roll_summary(memory: SessionMemory) -> None:
    if AUTO_SUMMARIZE_EVERY <= 0:
        return
    if memory.user_messages_total == 0:
        return
    if memory.user_messages_total % AUTO_SUMMARIZE_EVERY != 0:
        return

    parts: list[str] = []
    if memory.get_summary().strip():
        parts.append("Prior summary:\n" + memory.get_summary().strip())
    if memory.get_recent_context().strip():
        parts.append("Recent dialogue:\n" + memory.get_recent_context().strip())
    block = "\n\n".join(parts)
    if len(block.strip()) < 48:
        return

    new_s = summarize_conversation(block)
    if new_s:
        memory.update_summary(new_s)
        memory.clear_recent_only()
