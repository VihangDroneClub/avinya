from __future__ import annotations

import argparse
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from processors.processor import process_file
from converters.base_converter import ConversionError


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process a single inbox file into vault + archive + index")
    parser.add_argument("--input", required=True, help="Path to the source file")
    parser.add_argument("--vault", default="~/vihang_data/vault", help="Vault output directory")
    parser.add_argument("--archive", default="~/vihang_data/archive", help="Archive directory")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = Path(args.input).expanduser()
    vault = Path(args.vault).expanduser()
    archive = Path(args.archive).expanduser()

    try:
        result = process_file(source, vault, archive)
    except ConversionError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Processed: {result.source_file.name}")
    print(f"Markdown: {result.markdown_path}")
    print(f"Archive: {result.archive_path}")
    print(f"Indexed chunks: {result.indexed_chunks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

