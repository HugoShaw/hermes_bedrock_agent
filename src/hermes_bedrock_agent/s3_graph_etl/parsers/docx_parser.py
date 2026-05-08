"""DOCX parser - extracts text from Word documents."""
from __future__ import annotations

import logging
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.parsers.base import BaseParser
from hermes_bedrock_agent.s3_graph_etl.schemas import ContentType, DocumentChunk, ParserType

logger = logging.getLogger(__name__)


class DocxParser(BaseParser):
    """Parse .docx files using python-docx."""

    @property
    def supported_extensions(self) -> set[str]:
        return {".docx"}

    def parse(self, file_path: Path, source_uri: str) -> list[DocumentChunk]:
        try:
            from docx import Document
        except ImportError:
            logger.error("python-docx not installed. Cannot parse DOCX.")
            return []

        source_file = Path(source_uri.split("/")[-1]).name if "/" in source_uri else source_uri
        chunks: list[DocumentChunk] = []

        try:
            doc = Document(str(file_path))
        except Exception as exc:
            logger.error("Failed to read DOCX %s: %s", source_uri, exc)
            return []

        current_heading = ""
        heading_path: list[str] = []
        current_text = ""
        chunk_idx = 0

        for para in doc.paragraphs:
            style_name = para.style.name if para.style else ""

            if style_name.startswith("Heading"):
                # Save previous section
                if current_text.strip():
                    chunks.append(DocumentChunk(
                        id=self.make_chunk_id(source_uri, 0, chunk_idx),
                        source_uri=source_uri,
                        source_file=source_file,
                        chunk_index=chunk_idx,
                        content_type=ContentType.TEXT,
                        title=current_heading,
                        heading_path=heading_path[:],
                        text=current_text.strip(),
                        evidence_text=current_text.strip()[:500],
                        confidence=1.0,
                        parser_type=ParserType.PYTHON_PARSER,
                    ))
                    chunk_idx += 1
                    current_text = ""

                current_heading = para.text.strip()
                heading_path = [current_heading]
            else:
                if para.text.strip():
                    current_text += para.text + "\n"

        # Final section
        if current_text.strip():
            chunks.append(DocumentChunk(
                id=self.make_chunk_id(source_uri, 0, chunk_idx),
                source_uri=source_uri,
                source_file=source_file,
                chunk_index=chunk_idx,
                content_type=ContentType.TEXT,
                title=current_heading,
                heading_path=heading_path[:],
                text=current_text.strip(),
                evidence_text=current_text.strip()[:500],
                confidence=1.0,
                parser_type=ParserType.PYTHON_PARSER,
            ))

        logger.info("DOCX %s: %d chunks", source_uri, len(chunks))
        return chunks
