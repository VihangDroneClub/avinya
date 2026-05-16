from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _strip_frontmatter(text: str) -> str:
    stripped = (text or "").lstrip()
    if not stripped.startswith("---"):
        return stripped.strip()

    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        return stripped.strip()

    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return stripped.strip()
    return "\n".join(lines[end_index + 1 :]).strip()


def format_markdown_document(
    *,
    body: str,
    source_name: str,
    title: str | None = None,
    category: str,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> str:
    metadata = dict(metadata or {})
    created_at = created_at or datetime.now(timezone.utc)
    normalized_title = (title or Path(source_name).stem.replace("_", " ").replace("-", " ").strip().title())
    normalized_body = _strip_frontmatter(body)

    frontmatter = [
        "---",
        f"title: {normalized_title}",
        f"source: {source_name}",
        f"category: {category}",
        f"created_at: {created_at.isoformat()}",
    ]

    for key, value in metadata.items():
        if value is None:
            continue
        frontmatter.append(f"{key}: {value}")

    frontmatter.append("---")

    parts = [f"# {normalized_title}"]
    if normalized_body:
        parts.append(normalized_body)
    else:
        parts.append("_No content available._")

    return "\n\n".join(frontmatter + parts) + "\n"

