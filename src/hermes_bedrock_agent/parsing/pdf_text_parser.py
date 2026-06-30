"""PDF text parser: extract text from PDFs using PyMuPDF, flag low-density pages for VLM."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

TEXT_DENSITY_THRESHOLD = 50  # chars per page minimum to consider "text-rich"


class PdfTextParser(BaseParser):
    """Extract text from PDF using PyMuPDF. Flags low-density pages as needing VLM."""

    @property
    def name(self) -> str:
        return "pdf_text_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.PDF_NATIVE

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        logger.info("Parsing PDF: %s", path.name)

        doc = fitz.open(str(path))
        page_count = len(doc)
        total_chars = 0
        pages_text: list[str] = []
        low_density_pages: list[int] = []

        for i, page in enumerate(doc):
            text = page.get_text("text")
            char_count = len(text.strip())
            total_chars += char_count

            if char_count < TEXT_DENSITY_THRESHOLD:
                low_density_pages.append(i + 1)

            if text.strip():
                pages_text.append(f"## Page {i + 1}\n\n{text.strip()}")

        doc.close()

        avg_density = total_chars / page_count if page_count > 0 else 0
        needs_vlm = avg_density < TEXT_DENSITY_THRESHOLD

        if pages_text:
            content = f"# {path.stem}\n\n" + "\n\n---\n\n".join(pages_text)
        else:
            content = f"# {path.stem}\n\n*No extractable text found. This PDF likely contains scanned images and requires VLM processing.*"

        metadata: dict[str, Any] = {
            "page_count": page_count,
            "total_chars": total_chars,
            "avg_chars_per_page": round(avg_density, 1),
            "needs_vlm": needs_vlm,
            "low_density_pages": low_density_pages,
            "text_density_threshold": TEXT_DENSITY_THRESHOLD,
        }

        if needs_vlm:
            metadata["vlm_note"] = (
                f"Average text density ({avg_density:.0f} chars/page) below threshold "
                f"({TEXT_DENSITY_THRESHOLD}). VLM processing recommended for accurate extraction."
            )

        rel = relative_path or path.name
        return [ParsedDocument(
            doc_id=generate_doc_id(project_id, rel),
            project_id=project_id,
            source_path=str(path),
            source_type=SourceType.PDF_NATIVE,
            title=path.stem,
            content_markdown=content,
            metadata=metadata,
            language=_detect_pdf_language(content),
            parse_method="pymupdf_text",
        )]

    def estimated_cost(self, path: Path) -> dict[str, Any]:
        base = super().estimated_cost(path)
        if path.exists():
            try:
                doc = fitz.open(str(path))
                base["page_count"] = len(doc)
                doc.close()
            except Exception:
                pass
        return base


def _detect_pdf_language(text: str) -> str:
    sample = text[:3000]
    cjk = sum(1 for c in sample if "一" <= c <= "鿿")
    jp = sum(1 for c in sample if "぀" <= c <= "ヿ")
    total = len(sample) if sample else 1

    if jp / total > 0.03:
        return "ja"
    elif cjk / total > 0.05:
        return "zh"
    return "en"
