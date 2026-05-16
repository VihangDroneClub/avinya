from __future__ import annotations

import re
from pathlib import Path
from time import perf_counter
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .base_converter import BaseConverter, ConversionError, ConversionResult
from .converter_factory import ConverterFactory

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkg": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _clean_text(value: str | None) -> str:
    return (value or "").strip()


def _col_to_index(cell_ref: str) -> int:
    letters = re.sub(r"\d+", "", cell_ref or "").upper()
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return max(1, index) - 1


def _parse_shared_strings(zf: ZipFile) -> list[str]:
    try:
        raw = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []

    root = ET.fromstring(raw)
    strings: list[str] = []
    for si in root.findall("main:si", NS):
        parts = [node.text or "" for node in si.findall(".//main:t", NS)]
        strings.append("".join(parts))
    return strings


def _parse_workbook(zf: ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))

    rel_map: dict[str, str] = {}
    for rel in rels.findall("pkg:Relationship", NS):
        rel_map[rel.attrib["Id"]] = rel.attrib["Target"]

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        name = sheet.attrib.get("name", "Sheet")
        rid = sheet.attrib.get(f"{{{NS['rel']}}}id")
        if rid and rid in rel_map:
            sheets.append((name, rel_map[rid]))
    return sheets


def _parse_sheet(zf: ZipFile, target: str, shared_strings: list[str]) -> list[list[str]]:
    sheet_path = f"xl/{target.lstrip('/')}"
    root = ET.fromstring(zf.read(sheet_path))
    rows: list[list[str]] = []

    for row in root.findall(".//main:sheetData/main:row", NS):
        values_by_index: dict[int, str] = {}
        max_index = -1
        for cell in row.findall("main:c", NS):
            ref = cell.attrib.get("r", "")
            idx = _col_to_index(ref)
            max_index = max(max_index, idx)
            cell_type = cell.attrib.get("t", "")
            value = ""
            if cell_type == "s":
                raw = cell.findtext("main:v", default="", namespaces=NS)
                if raw.isdigit():
                    shared_idx = int(raw)
                    if 0 <= shared_idx < len(shared_strings):
                        value = shared_strings[shared_idx]
            elif cell_type == "inlineStr":
                value = "".join(cell.itertext())
            else:
                value = cell.findtext("main:v", default="", namespaces=NS) or ""
            values_by_index[idx] = _clean_text(value)

        if max_index >= 0:
            rows.append([values_by_index.get(i, "") for i in range(max_index + 1)])

    return rows


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    header = normalized[0]
    separator = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in normalized[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


@ConverterFactory.register
class XLSXConverter(BaseConverter):
    supported_extensions = (".xlsx", ".xls")

    def convert(self, file_path: str | Path, output_dir: str | Path) -> ConversionResult:
        source = Path(file_path)
        if not source.exists():
            raise ConversionError(f"XLSX not found: {source}")
        if source.suffix.lower() not in self.supported_extensions:
            raise ConversionError(f"Unsupported file type: {source.suffix or '<none>'}")
        if source.suffix.lower() == ".xls":
            raise ConversionError("Legacy .xls files are not supported yet; convert to .xlsx first.")

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{source.stem}.md"

        started = perf_counter()
        try:
            with ZipFile(source) as zf:
                shared_strings = _parse_shared_strings(zf)
                sheets = _parse_workbook(zf)
                sheet_blocks: list[str] = []
                sheet_count = 0
                for sheet_name, target in sheets:
                    rows = _parse_sheet(zf, target, shared_strings)
                    markdown_table = _rows_to_markdown(rows)
                    if not markdown_table:
                        continue
                    sheet_count += 1
                    sheet_blocks.append(f"## Sheet: {sheet_name}\n\n{markdown_table}")
        except ConversionError:
            raise
        except Exception as exc:
            raise ConversionError(f"Failed to read XLSX: {source.name}") from exc

        title = source.stem.replace("_", " ").replace("-", " ").strip().title() or source.stem
        metadata: dict[str, Any] = {
            "source_file": source.name,
            "markdown_path": str(target_path),
            "sheets": sheet_count,
            "conversion_method": "zip-ooxml",
            "conversion_time": round(perf_counter() - started, 3),
            "title": title,
        }

        frontmatter = [
            "---",
            f"title: {title}",
            f"source_file: {source.name}",
            f"sheets: {sheet_count}",
            "conversion_method: zip-ooxml",
            "---",
        ]

        body = [f"# {title}"]
        if sheet_blocks:
            body.extend(sheet_blocks)
        else:
            body.append("_No tabular content was found in this XLSX._")

        markdown = "\n\n".join(frontmatter + body) + "\n"
        target_path.write_text(markdown, encoding="utf-8")

        return ConversionResult(
            markdown_path=target_path,
            metadata=metadata,
            status="success",
            content=markdown,
        )

