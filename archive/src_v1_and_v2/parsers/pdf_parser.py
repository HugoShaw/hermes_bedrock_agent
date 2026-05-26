"""PDF parser — extracts text and page metadata from PDF files.

Uses pymupdf (fitz) for text extraction. Supports page-level image extraction
interface for optional VLM second-pass (but does not call VLM directly).

Note: pymupdf is an optional dependency. Falls back to raw bytes info if unavailable.
"""

from __future__ import annotations

import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.parsers.base import BaseParser, ParserContext, ParserError, ParserOutput
from hermes_bedrock_agent.schemas.document import NormalizedDocument, SourceType
from hermes_bedrock_agent.schemas.visual import VisualBlock, VisualType
from hermes_bedrock_agent.utils.hashing import content_hash, make_visual_id

logger = get_logger(__name__)


class PdfParser(BaseParser):
    """Parser for PDF documents.

    Capabilities:
    - Full text extraction per page (via pymupdf)
    - Page-level metadata (page count, dimensions)
    - Image extraction interface (for VLM second-pass)
    - Falls back gracefully if pymupdf is not installed
    """

    @property
    def parser_name(self) -> str:
        return "PdfParser"

    def parse(self, ctx: ParserContext) -> ParserOutput:
        """Parse a PDF document.

        Args:
            ctx: Parser context with PDF bytes.

        Returns:
            ParserOutput with text content and optional VisualBlocks for pages.
        """
        try:
            return self._parse_with_pymupdf(ctx)
        except ImportError:
            logger.warning("pymupdf not installed — PDF text extraction unavailable")
            return self._fallback_parse(ctx)

    def _parse_with_pymupdf(self, ctx: ParserContext) -> ParserOutput:
        """Full PDF parsing with pymupdf."""
        import fitz  # pymupdf

        doc_pdf = fitz.open(stream=ctx.content_bytes, filetype="pdf")
        pages_text: list[str] = []
        sections: list[dict[str, str]] = []
        visual_blocks: list[VisualBlock] = []

        for page_num in range(len(doc_pdf)):
            page = doc_pdf[page_num]
            page_text = page.get_text("text")
            pages_text.append(page_text)

            # Section from first non-empty line on each page
            first_line = page_text.strip().split("\n")[0] if page_text.strip() else ""
            if first_line:
                sections.append({
                    "title": first_line[:100],
                    "level": "1",
                    "page": str(page_num + 1),
                })

            # Extract page as image for potential VLM processing
            if ctx.enable_vlm:
                page_image_bytes = self._render_page_image(page)
                if page_image_bytes:
                    vblock = VisualBlock(
                        visual_id=make_visual_id(
                            ctx.document.document_id, page_num + 1, "page"
                        ),
                        document_id=ctx.document.document_id,
                        source_uri=ctx.source_uri,
                        page=page_num + 1,
                        visual_type=VisualType.PAGE_SCREENSHOT,
                        image_base64=base64.b64encode(page_image_bytes).decode(),
                        image_format="png",
                        width=int(page.rect.width),
                        height=int(page.rect.height),
                        extracted_text=page_text[:500] if page_text else "",
                        confidence=0.0,  # Not yet processed by VLM
                        model_name="",
                        created_at=datetime.now(timezone.utc),
                    )
                    visual_blocks.append(vblock)

        doc_pdf.close()

        full_text = "\n\n--- Page Break ---\n\n".join(pages_text)

        normalized = NormalizedDocument(
            document_id=ctx.document.document_id,
            source_uri=ctx.source_uri,
            source_type=SourceType.PDF,
            title=self._infer_title(ctx.document, pages_text),
            content=full_text,
            sections=sections,
            language="",
            page_count=len(pages_text),
            content_hash=content_hash(ctx.content_bytes),
            metadata={
                "parser": self.parser_name,
                "page_count": len(pages_text),
                "total_chars": len(full_text),
            },
            visual_block_ids=[vb.visual_id for vb in visual_blocks],
            created_at=datetime.now(timezone.utc),
        )

        return ParserOutput(
            normalized_document=normalized,
            visual_blocks=visual_blocks,
        )

    def _fallback_parse(self, ctx: ParserContext) -> ParserOutput:
        """Minimal parsing when pymupdf is not available."""
        normalized = NormalizedDocument(
            document_id=ctx.document.document_id,
            source_uri=ctx.source_uri,
            source_type=SourceType.PDF,
            title=ctx.document.filename,
            content="[PDF text extraction unavailable — install pymupdf]",
            sections=[],
            language="",
            page_count=0,
            content_hash=content_hash(ctx.content_bytes),
            metadata={
                "parser": self.parser_name,
                "fallback": True,
                "file_size": len(ctx.content_bytes),
            },
            visual_block_ids=[],
            created_at=datetime.now(timezone.utc),
        )
        return ParserOutput(normalized_document=normalized)

    def _render_page_image(self, page: Any) -> Optional[bytes]:
        """Render a PDF page to PNG bytes for VLM processing."""
        try:
            # Render at 150 DPI for a good balance of quality and size
            pix = page.get_pixmap(dpi=150)
            return pix.tobytes("png")
        except Exception as exc:
            logger.warning("Failed to render page image: %s", exc)
            return None

    def _infer_title(self, doc: Any, pages_text: list[str]) -> str:
        """Infer title from first page content or filename."""
        if pages_text and pages_text[0].strip():
            first_line = pages_text[0].strip().split("\n")[0]
            if len(first_line) < 200:
                return first_line
        return doc.filename.rsplit(".", 1)[0] if "." in doc.filename else doc.filename
