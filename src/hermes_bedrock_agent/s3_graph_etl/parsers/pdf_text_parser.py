"""PDF text parser - extracts text from PDFs with fallback to vision."""
from __future__ import annotations

import logging
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.parsers.base import BaseParser
from hermes_bedrock_agent.s3_graph_etl.schemas import ContentType, DocumentChunk, ParserType

logger = logging.getLogger(__name__)


class PdfTextParser(BaseParser):
    """Parse PDFs using text extraction. Falls back to vision for scanned PDFs."""

    MIN_TEXT_QUALITY_RATIO = 0.3  # minimum ratio of readable chars

    @property
    def supported_extensions(self) -> set[str]:
        return {".pdf"}

    def parse(self, file_path: Path, source_uri: str) -> list[DocumentChunk]:
        """Parse PDF, attempting text extraction first."""
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.error("pypdf not installed. Cannot parse PDFs.")
            return []

        source_file = Path(source_uri.split("/")[-1]).name if "/" in source_uri else source_uri
        chunks: list[DocumentChunk] = []

        try:
            reader = PdfReader(str(file_path))
        except Exception as exc:
            logger.error("Failed to read PDF %s: %s", source_uri, exc)
            return []

        for page_num, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""

            # Check text quality
            if self._is_text_quality_acceptable(text):
                chunks.append(DocumentChunk(
                    id=self.make_chunk_id(source_uri, page_num, 0),
                    source_uri=source_uri,
                    source_file=source_file,
                    page_number=page_num,
                    chunk_index=0,
                    content_type=ContentType.TEXT,
                    title=f"Page {page_num}",
                    text=text.strip(),
                    evidence_text=text.strip()[:500],
                    confidence=0.9,
                    parser_type=ParserType.PYTHON_PARSER,
                ))
            else:
                # Mark as needing vision parsing
                chunks.append(DocumentChunk(
                    id=self.make_chunk_id(source_uri, page_num, 0),
                    source_uri=source_uri,
                    source_file=source_file,
                    page_number=page_num,
                    chunk_index=0,
                    content_type=ContentType.IMAGE,
                    title=f"Page {page_num} (needs vision)",
                    text="",
                    visual_description="Scanned page requiring OCR/vision parsing",
                    confidence=0.0,
                    parser_type=ParserType.LLM_VISION_PARSER,
                    needs_review=True,
                ))

        logger.info("PDF %s: %d pages parsed", source_uri, len(chunks))
        return chunks

    def _is_text_quality_acceptable(self, text: str) -> bool:
        """Check if extracted text is readable (not garbled/empty)."""
        if not text or len(text.strip()) < 20:
            return False
        # Check ratio of printable ASCII + CJK characters
        readable = sum(1 for c in text if c.isprintable() or c in "\n\t")
        ratio = readable / len(text) if text else 0
        return ratio >= self.MIN_TEXT_QUALITY_RATIO
