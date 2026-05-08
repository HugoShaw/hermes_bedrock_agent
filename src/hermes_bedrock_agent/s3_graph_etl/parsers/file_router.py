"""File router - dispatches files to appropriate parsers."""
from __future__ import annotations

import logging
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.parsers.base import BaseParser
from hermes_bedrock_agent.s3_graph_etl.parsers.text_parser import TextParser
from hermes_bedrock_agent.s3_graph_etl.parsers.code_parser import CodeParser
from hermes_bedrock_agent.s3_graph_etl.parsers.pdf_text_parser import PdfTextParser
from hermes_bedrock_agent.s3_graph_etl.parsers.docx_parser import DocxParser
from hermes_bedrock_agent.s3_graph_etl.schemas import DocumentChunk

logger = logging.getLogger(__name__)


class FileRouter:
    """Route files to the appropriate parser based on extension."""

    def __init__(self) -> None:
        self._parsers: list[BaseParser] = [
            TextParser(),
            CodeParser(),
            PdfTextParser(),
            DocxParser(),
        ]
        self._ext_map: dict[str, BaseParser] = {}
        for parser in self._parsers:
            for ext in parser.supported_extensions:
                self._ext_map[ext] = parser

    def route(self, file_path: Path, source_uri: str) -> list[DocumentChunk]:
        """Parse a file using the appropriate parser."""
        ext = file_path.suffix.lower()
        parser = self._ext_map.get(ext)

        if parser is None:
            logger.warning("No parser for extension %s (file: %s)", ext, source_uri)
            return []

        try:
            chunks = parser.parse(file_path, source_uri)
            logger.info("Parsed %s -> %d chunks (parser=%s)", source_uri, len(chunks), type(parser).__name__)
            return chunks
        except Exception as exc:
            logger.error("Parser failed for %s: %s", source_uri, exc)
            return []

    def get_parser_name(self, file_path: Path) -> str | None:
        ext = file_path.suffix.lower()
        parser = self._ext_map.get(ext)
        return type(parser).__name__ if parser else None

    @property
    def supported_extensions(self) -> set[str]:
        return set(self._ext_map.keys())
