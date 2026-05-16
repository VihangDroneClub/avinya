from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from pypdf import PdfReader

from .base_converter import BaseConverter, ConversionError, ConversionResult
from .converter_factory import ConverterFactory


@ConverterFactory.register
class PDFConverter(BaseConverter):
    supported_extensions = (".pdf",)

    def convert(self, file_path: str | Path, output_dir: str | Path) -> ConversionResult:
        source = Path(file_path)
        if not source.exists():
            raise ConversionError(f"PDF not found: {source}")
        if source.suffix.lower() not in self.supported_extensions:
            raise ConversionError(f"Unsupported file type: {source.suffix or '<none>'}")

        target_dir = Path(output_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{source.stem}.md"

        started = perf_counter()
        try:
            reader = PdfReader(str(source))
        except Exception as exc:  # pypdf raises several parser-specific exceptions
            raise ConversionError(f"Failed to read PDF: {source.name}") from exc

        if getattr(reader, "is_encrypted", False):
            try:
                decrypt_result = reader.decrypt("")
            except Exception as exc:
                raise ConversionError(f"Encrypted PDF cannot be opened: {source.name}") from exc
            if not decrypt_result:
                raise ConversionError(f"Encrypted PDF cannot be opened: {source.name}")

        page_texts: list[str] = []
        for page_index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                raise ConversionError(f"Failed to extract page {page_index} from {source.name}") from exc
            cleaned = text.strip()
            if cleaned:
                page_texts.append(f"## Page {page_index}\n\n{cleaned}")

        title = source.stem.replace("_", " ").replace("-", " ").strip().title() or source.stem
        metadata: dict[str, Any] = {
            "source_file": source.name,
            "markdown_path": str(target_path),
            "pages": len(reader.pages),
            "has_images": False,
            "has_tables": False,
            "conversion_method": "pypdf",
            "conversion_time": round(perf_counter() - started, 3),
            "title": title,
        }

        frontmatter = [
            "---",
            f"title: {title}",
            f"source_file: {source.name}",
            f"pages: {len(reader.pages)}",
            "has_images: false",
            "has_tables: false",
            "conversion_method: pypdf",
            "---",
        ]

        body: list[str] = [f"# {title}"]
        if page_texts:
            body.extend(page_texts)
        else:
            body.append("_No extractable text was found in this PDF._")

        markdown = "\n\n".join(frontmatter + body) + "\n"
        target_path.write_text(markdown, encoding="utf-8")

        return ConversionResult(
            markdown_path=target_path,
            metadata=metadata,
            status="success",
            content=markdown,
        )
