"""Base parser interface and shared types.

All parsers implement BaseParser and produce ParserOutput containing
a NormalizedDocument and optional VisualBlocks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from hermes_bedrock_agent.schemas.document import NormalizedDocument, SourceDocument
from hermes_bedrock_agent.schemas.visual import VisualBlock


@dataclass
class ParserContext:
    """Context passed to a parser for a single document.

    Contains everything the parser needs: document metadata, raw bytes,
    and optional VLM configuration.
    """

    document: SourceDocument
    content_bytes: bytes
    enable_vlm: bool = False
    bedrock_client: Optional[Any] = None
    vlm_model_id: str = "anthropic.claude-sonnet-4-20250514-v1:0"

    @property
    def text(self) -> str:
        """Decode content_bytes as UTF-8 text (lossy)."""
        return self.content_bytes.decode("utf-8", errors="replace")

    @property
    def filename(self) -> str:
        return self.document.filename

    @property
    def source_uri(self) -> str:
        return self.document.source_uri


@dataclass
class ParserOutput:
    """Output from a parser — normalized document + optional visual blocks."""

    normalized_document: NormalizedDocument
    visual_blocks: list[VisualBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseParser(ABC):
    """Abstract base class for all document parsers.

    Subclasses must implement:
    - parse(ctx: ParserContext) -> ParserOutput
    - supported_types: class attribute listing handled SourceTypes
    """

    @abstractmethod
    def parse(self, ctx: ParserContext) -> ParserOutput:
        """Parse a document and return normalized output.

        Args:
            ctx: Parser context with document metadata and content bytes.

        Returns:
            ParserOutput with NormalizedDocument and optional VisualBlocks.

        Raises:
            ParserError: On parsing failure.
        """
        ...

    @property
    @abstractmethod
    def parser_name(self) -> str:
        """Human-readable parser name."""
        ...


class ParserError(Exception):
    """Raised when a parser fails to process a document."""

    def __init__(self, message: str, document_id: str = "", cause: str = "") -> None:
        super().__init__(message)
        self.document_id = document_id
        self.cause = cause
