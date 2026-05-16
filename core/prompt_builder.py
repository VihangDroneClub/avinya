from __future__ import annotations

from memory.session_memory import SessionMemory
from prompts.system_prompt import SYSTEM_PROMPT


def build_full_prompt(user_message: str, kb_text: str, memory: SessionMemory) -> str:
    """Assemble the full string prompt for Ollama /generate (single-turn string API)."""
    parts: list[str] = [SYSTEM_PROMPT]

    summ = (memory.get_summary() or "").strip()
    if summ:
        parts.append("\n## Conversation memory (rolling summary)\n" + summ)

    recent = (memory.get_recent_context() or "").strip()
    if recent:
        parts.append("\n## Recent dialogue\n[Sorted oldest → newest]\n" + recent)

    if (kb_text or "").strip():
        parts.append("\n## Knowledge Base (retrieved passages)\n" + kb_text.strip())
    else:
        parts.append("\n## Knowledge Base (retrieved passages)\n(No matching passages in the index for this query.)")

    parts.append("\n## Current user message\n" + user_message.strip())
    parts.append("\n## Assistant (respond now)\n")

    return "\n".join(parts)
