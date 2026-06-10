"""DOCX parser: extract text, headings, and tables as markdown."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import Table

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)


def _table_to_markdown(table: Table) -> str:
    """Convert a docx table to markdown format."""
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
        rows.append(cells)

    if not rows:
        return ""

    lines: list[str] = []
    # Header row
    lines.append("| " + " | ".join(rows[0]) + " |")
    lines.append("| " + " | ".join("---" for _ in rows[0]) + " |")
    # Data rows
    for row in rows[1:]:
        # Pad if fewer cells than header
        while len(row) < len(rows[0]):
            row.append("")
        lines.append("| " + " | ".join(row[:len(rows[0])]) + " |")

    return "\n".join(lines)


class DocxParser(BaseParser):
    """Parse .docx files to markdown using python-docx."""

    @property
    def name(self) -> str:
        return "docx_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.DOCX

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        logger.info("Parsing DOCX: %s", path.name)

        # Legacy .doc (binary OLE format) cannot be handled by python-docx
        if path.suffix.lower() == ".doc":
            # Check if it's actually a .docx in disguise (ZIP-based)
            import zipfile
            if not zipfile.is_zipfile(str(path)):
                raise ValueError(
                    f"Legacy .doc format not supported by python-docx. "
                    f"File '{path.name}' needs VLM-based parsing or conversion to .docx."
                )

        doc = Document(str(path))
        markdown_parts: list[str] = []
        image_count = 0

        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                from docx.oxml.ns import qn
                # Check for images
                drawings = element.findall(f".//{qn('wp:inline')}") + element.findall(f".//{qn('wp:anchor')}")
                if drawings:
                    image_count += len(drawings)

                # Get paragraph
                from docx.text.paragraph import Paragraph
                para = Paragraph(element, doc)
                text = para.text.strip()
                if not text:
                    continue

                style_name = para.style.name if para.style else ""
                if "Heading 1" in style_name:
                    markdown_parts.append(f"# {text}")
                elif "Heading 2" in style_name:
                    markdown_parts.append(f"## {text}")
                elif "Heading 3" in style_name:
                    markdown_parts.append(f"### {text}")
                elif "Heading" in style_name:
                    markdown_parts.append(f"#### {text}")
                elif "List" in style_name or "Bullet" in style_name:
                    markdown_parts.append(f"- {text}")
                else:
                    markdown_parts.append(text)

            elif tag == "tbl":
                table = Table(element, doc)
                md_table = _table_to_markdown(table)
                if md_table:
                    markdown_parts.append("")
                    markdown_parts.append(md_table)
                    markdown_parts.append("")

        content = "\n\n".join(markdown_parts)

        metadata: dict[str, Any] = {
            "image_count": image_count,
            "paragraph_count": len(markdown_parts),
        }
        if image_count > 0:
            metadata["has_images"] = True
            metadata["note"] = f"{image_count} embedded images detected (not extracted in this phase)"

        # Try to detect language
        language = _detect_language(content)

        rel = relative_path or path.name
        return [ParsedDocument(
            doc_id=generate_doc_id(project_id, rel),
            project_id=project_id,
            source_path=str(path),
            source_type=SourceType.DOCX,
            title=path.stem,
            content_markdown=content,
            metadata=metadata,
            language=language,
            parse_method="python-docx",
        )]


def _detect_language(text: str) -> str:
    """Simple heuristic language detection based on character ranges."""
    if not text:
        return "unknown"

    sample = text[:2000]
    cjk_count = sum(1 for c in sample if "一" <= c <= "鿿")
    jp_count = sum(1 for c in sample if "぀" <= c <= "ヿ")
    total = len(sample)

    if total == 0:
        return "unknown"

    cjk_ratio = cjk_count / total
    jp_ratio = jp_count / total

    if jp_ratio > 0.05:
        return "ja"
    elif cjk_ratio > 0.1:
        return "zh"
    elif cjk_ratio > 0.02:
        return "zh-mixed"
    return "en"
