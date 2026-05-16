from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable

from processors.processor import process_file

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".xls"}


def scan_inbox(inbox_root: str | Path, extensions: Iterable[str] | None = None) -> list[Path]:
    inbox = Path(inbox_root)
    if not inbox.exists():
        return []

    allowed = {ext.lower() for ext in (extensions or SUPPORTED_EXTENSIONS)}
    files = [p for p in inbox.iterdir() if p.is_file() and p.suffix.lower() in allowed]
    return sorted(files, key=lambda p: p.name.lower())


def process_inbox_once(
    inbox_root: str | Path,
    vault_root: str | Path,
    archive_root: str | Path,
    *,
    processor: Callable[..., object] = process_file,
) -> list[object]:
    results: list[object] = []
    for file_path in scan_inbox(inbox_root):
        results.append(processor(file_path, vault_root, archive_root))
    return results


def watch_inbox(
    inbox_root: str | Path,
    vault_root: str | Path,
    archive_root: str | Path,
    *,
    interval_seconds: int = 30,
    processor: Callable[..., object] = process_file,
    stop_event=None,
) -> None:
    while True:
        process_inbox_once(inbox_root, vault_root, archive_root, processor=processor)
        if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
            return
        time.sleep(max(1, interval_seconds))

