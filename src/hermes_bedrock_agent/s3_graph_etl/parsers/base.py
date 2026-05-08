"""Base parser interface."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.schemas import DocumentChunk


class BaseParser(ABC):
    """Abstract base parser. All parsers produce DocumentChunks."""

    @abstractmethod
    def parse(self, file_path: Path, source_uri: str) -> list[DocumentChunk]:
        """Parse a file and return a list of DocumentChunks."""
        ...

    @staticmethod
    def make_chunk_id(source_uri: str, page: int = 0, chunk_index: int = 0) -> str:
        """Generate deterministic chunk ID."""
        raw = f"{source_uri}::p{page}::c{chunk_index}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    @abstractmethod
    def supported_extensions(self) -> set[str]:
        """Return set of file extensions this parser handles."""
        ...
