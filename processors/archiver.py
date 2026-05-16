from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path


def _dedupe_target(target: Path) -> Path:
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def archive_processed_file(source_path: str | Path, archive_root: str | Path) -> Path:
    source = Path(source_path)
    root = Path(archive_root)
    root.mkdir(parents=True, exist_ok=True)

    dated_dir = root / date.today().isoformat()
    dated_dir.mkdir(parents=True, exist_ok=True)

    target = _dedupe_target(dated_dir / source.name)
    return Path(shutil.move(str(source), str(target)))

