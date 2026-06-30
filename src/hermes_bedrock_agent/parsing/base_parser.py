"""Abstract base for all document parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..models.document import ParsedDocument, SourceType


class BaseParser(ABC):
    """Base class for document parsers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable parser name."""
        ...

    @abstractmethod
    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        """Return True if this parser can handle the given file."""
        ...

    @abstractmethod
    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        """Parse the file and return one or more ParsedDocument objects."""
        ...

    def estimated_cost(self, path: Path) -> dict[str, Any]:
        """Estimate cost/complexity for parsing this file. No API calls."""
        size = path.stat().st_size if path.exists() else 0
        return {
            "parser": self.name,
            "file_size_bytes": size,
            "estimated_tokens": 0,
            "needs_api": False,
        }
