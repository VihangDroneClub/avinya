from __future__ import annotations

from pathlib import Path

from .base_converter import BaseConverter, ConversionError


class ConverterFactory:
    _registry: dict[str, type[BaseConverter]] = {}

    @classmethod
    def register(cls, converter_cls: type[BaseConverter]) -> type[BaseConverter]:
        for ext in converter_cls.supported_extensions:
            cls._registry[ext.lower()] = converter_cls
        return converter_cls

    @classmethod
    def get_converter(cls, file_path: str | Path) -> BaseConverter:
        _bootstrap_registry()
        suffix = Path(file_path).suffix.lower()
        converter_cls = cls._registry.get(suffix)
        if converter_cls is None:
            raise ConversionError(f"Unsupported file type: {suffix or '<none>'}")
        return converter_cls()

    @classmethod
    def supported_extensions(cls) -> tuple[str, ...]:
        return tuple(sorted(cls._registry))


def _bootstrap_registry() -> None:
    # Lazy imports keep the factory usable before all converter implementations land.
    try:
        from .pdf_converter import PDFConverter  # noqa: F401
    except Exception:
        pass
    try:
        from .docx_converter import DOCXConverter  # noqa: F401
    except Exception:
        pass
    try:
        from .xlsx_converter import XLSXConverter  # noqa: F401
    except Exception:
        pass


_bootstrap_registry()
