from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ConversionResult:
    markdown_path: Path | None
    metadata: dict[str, Any] = field(default_factory=dict)
    status: str = "success"
    content: str = ""


class ConversionError(RuntimeError):
    """Raised when a document cannot be converted."""


class BaseConverter(ABC):
    supported_extensions: tuple[str, ...] = ()

    def can_handle(self, file_path: str | Path) -> bool:
        return Path(file_path).suffix.lower() in self.supported_extensions

    @abstractmethod
    def convert(self, file_path: str | Path, output_dir: str | Path) -> ConversionResult:
        raise NotImplementedError

