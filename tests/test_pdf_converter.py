from __future__ import annotations

from pathlib import Path

import pytest

from converters.base_converter import ConversionError
from converters.pdf_converter import PDFConverter


def _build_minimal_pdf(text: str) -> bytes:
    header = b"%PDF-1.4\n"
    objects: list[bytes] = []

    objects.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objects.append(b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n")
    objects.append(
        b"3 0 obj\n"
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\n"
        b"endobj\n"
    )
    objects.append(b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n")

    stream = (
        "BT\n"
        "/F1 18 Tf\n"
        "72 200 Td\n"
        f"({text}) Tj\n"
        "ET\n"
    ).encode("latin-1")
    objects.append(
        b"5 0 obj\n"
        + f"<< /Length {len(stream)} >>\n".encode("ascii")
        + b"stream\n"
        + stream
        + b"endstream\nendobj\n"
    )

    offsets = [0]
    cursor = len(header)
    for obj in objects:
        offsets.append(cursor)
        cursor += len(obj)

    xref_lines = [b"xref\n", b"0 6\n", b"0000000000 65535 f \n"]
    for offset in offsets[1:]:
        xref_lines.append(f"{offset:010d} 00000 n \n".encode("ascii"))

    xref = b"".join(xref_lines)
    startxref = len(header) + sum(len(obj) for obj in objects)
    trailer = (
        b"trailer\n"
        b"<< /Size 6 /Root 1 0 R >>\n"
        b"startxref\n"
        + str(startxref).encode("ascii")
        + b"\n%%EOF\n"
    )
    return header + b"".join(objects) + xref + trailer


def test_pdf_converter_writes_markdown(tmp_path: Path):
    source = tmp_path / "budget_2025.pdf"
    source.write_bytes(_build_minimal_pdf("Hello Vihang"))

    output_dir = tmp_path / "vault"
    result = PDFConverter().convert(source, output_dir)

    assert result.status == "success"
    assert result.markdown_path == output_dir / "budget_2025.md"
    assert result.markdown_path.exists()
    assert result.metadata["source_file"] == "budget_2025.pdf"
    assert result.metadata["pages"] == 1
    assert result.metadata["conversion_method"] == "pypdf"
    assert "Hello Vihang" in result.content
    assert "# Budget 2025" in result.content


def test_pdf_converter_rejects_missing_file(tmp_path: Path):
    with pytest.raises(ConversionError):
        PDFConverter().convert(tmp_path / "missing.pdf", tmp_path / "vault")


def test_pdf_converter_rejects_invalid_pdf(tmp_path: Path):
    source = tmp_path / "broken.pdf"
    source.write_text("not a pdf", encoding="utf-8")

    with pytest.raises(ConversionError):
        PDFConverter().convert(source, tmp_path / "vault")

