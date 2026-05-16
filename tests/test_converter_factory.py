from __future__ import annotations

import pytest

from converters.base_converter import BaseConverter, ConversionError, ConversionResult
from converters.converter_factory import ConverterFactory


class _PdfStubConverter(BaseConverter):
    supported_extensions = (".pdf",)

    def convert(self, file_path, output_dir):
        return ConversionResult(markdown_path=None, metadata={"source": str(file_path)})


class _DocxStubConverter(BaseConverter):
    supported_extensions = (".docx", ".doc")

    def convert(self, file_path, output_dir):
        return ConversionResult(markdown_path=None, metadata={"source": str(file_path)})


class _XlsxStubConverter(BaseConverter):
    supported_extensions = (".xlsx", ".xls")

    def convert(self, file_path, output_dir):
        return ConversionResult(markdown_path=None, metadata={"source": str(file_path)})


def test_factory_routes_pdf(monkeypatch):
    monkeypatch.setattr(ConverterFactory, "_registry", {})
    ConverterFactory.register(_PdfStubConverter)
    converter = ConverterFactory.get_converter("sample.pdf")
    assert isinstance(converter, _PdfStubConverter)
    assert converter.can_handle("sample.pdf")


def test_factory_routes_docx_and_doc(monkeypatch):
    monkeypatch.setattr(ConverterFactory, "_registry", {})
    ConverterFactory.register(_DocxStubConverter)
    assert isinstance(ConverterFactory.get_converter("sample.docx"), _DocxStubConverter)
    assert isinstance(ConverterFactory.get_converter("sample.doc"), _DocxStubConverter)


def test_factory_routes_xlsx_and_xls(monkeypatch):
    monkeypatch.setattr(ConverterFactory, "_registry", {})
    ConverterFactory.register(_XlsxStubConverter)
    assert isinstance(ConverterFactory.get_converter("sample.xlsx"), _XlsxStubConverter)
    assert isinstance(ConverterFactory.get_converter("sample.xls"), _XlsxStubConverter)


def test_factory_rejects_unknown_extension(monkeypatch):
    monkeypatch.setattr(ConverterFactory, "_registry", {})
    with pytest.raises(ConversionError):
        ConverterFactory.get_converter("sample.txt")

