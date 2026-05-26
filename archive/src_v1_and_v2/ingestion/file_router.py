"""File router — routes documents to appropriate parsers based on type.

Maps SourceType to parser classes for the ingestion pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.document import SourceDocument, SourceType

if TYPE_CHECKING:
    from hermes_bedrock_agent.parsers.base import BaseParser

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Router configuration
# ---------------------------------------------------------------------------

# Parser class names mapped to source types
# Actual parser instances are created lazily to avoid circular imports
_PARSER_ROUTING: dict[SourceType, str] = {
    SourceType.MARKDOWN: "TextParser",
    SourceType.TEXT: "TextParser",
    SourceType.CODE: "TextParser",
    SourceType.SQL: "TextParser",
    SourceType.CONFIG: "TextParser",
    SourceType.PDF: "PdfParser",
    SourceType.IMAGE: "ImageParser",
    SourceType.DOCX: "TextParser",  # Future: DocxParser
    SourceType.PPTX: "TextParser",  # Future: PptxParser
    SourceType.SPREADSHEET: "TextParser",  # Future: SpreadsheetParser
}


class FileRouter:
    """Routes documents to the appropriate parser based on source_type.

    Maintains a registry of parser instances and selects the correct one
    for each document. Supports custom overrides and fallback behavior.
    """

    def __init__(
        self,
        custom_routes: dict[SourceType, str] | None = None,
        enable_vlm: bool = False,
    ) -> None:
        """Initialize the file router.

        Args:
            custom_routes: Optional overrides for default routing table.
            enable_vlm: Whether to enable VLM second-pass for images/PDFs.
        """
        self._routes = dict(_PARSER_ROUTING)
        if custom_routes:
            self._routes.update(custom_routes)
        self._enable_vlm = enable_vlm
        self._parsers: dict[str, "BaseParser"] = {}

    def get_parser_name(self, doc: SourceDocument) -> str:
        """Get the parser class name for a document.

        Args:
            doc: Source document to route.

        Returns:
            Parser class name string.
        """
        parser_name = self._routes.get(doc.source_type, "TextParser")
        return parser_name

    def get_parser(self, doc: SourceDocument) -> "BaseParser":
        """Get or create the parser instance for a document.

        Args:
            doc: Source document to route.

        Returns:
            Parser instance ready to parse.
        """
        parser_name = self.get_parser_name(doc)

        if parser_name not in self._parsers:
            self._parsers[parser_name] = self._create_parser(parser_name)

        return self._parsers[parser_name]

    def needs_vlm(self, doc: SourceDocument) -> bool:
        """Check if a document should also go through VLM parsing.

        Args:
            doc: Source document to check.

        Returns:
            True if VLM second-pass is needed.
        """
        if not self._enable_vlm:
            return False
        return doc.source_type in (SourceType.IMAGE, SourceType.PDF)

    def route_batch(
        self, documents: list[SourceDocument]
    ) -> dict[str, list[SourceDocument]]:
        """Group documents by their target parser.

        Args:
            documents: List of documents to route.

        Returns:
            Dict mapping parser_name → list of documents.
        """
        groups: dict[str, list[SourceDocument]] = {}
        for doc in documents:
            parser_name = self.get_parser_name(doc)
            if parser_name not in groups:
                groups[parser_name] = []
            groups[parser_name].append(doc)

        for name, docs in groups.items():
            logger.info("Routed %d documents to %s", len(docs), name)

        return groups

    def _create_parser(self, parser_name: str) -> "BaseParser":
        """Create a parser instance by name.

        Deferred import to avoid circular dependencies.
        """
        if parser_name == "TextParser":
            from hermes_bedrock_agent.parsers.text_parser import TextParser
            return TextParser()
        elif parser_name == "PdfParser":
            from hermes_bedrock_agent.parsers.pdf_parser import PdfParser
            return PdfParser()
        elif parser_name == "ImageParser":
            from hermes_bedrock_agent.parsers.image_parser import ImageParser
            return ImageParser()
        else:
            # Fallback to TextParser for unknown types
            from hermes_bedrock_agent.parsers.text_parser import TextParser
            logger.warning("Unknown parser '%s', falling back to TextParser", parser_name)
            return TextParser()
