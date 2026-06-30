"""Markdown passthrough parser: read .md files, detect encoding, wrap with frontmatter."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chardet

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()[:8000]
    result = chardet.detect(raw)
    enc = result.get("encoding") or "utf-8"
    for candidate in [enc, "utf-8", "utf-8-sig", "shift_jis", "GB18030", "latin-1"]:
        try:
            return path.read_text(encoding=candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_bytes().decode("utf-8", errors="replace")


class MarkdownParser(BaseParser):
    """Passthrough parser for existing .md files."""

    @property
    def name(self) -> str:
        return "markdown_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.MARKDOWN

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        logger.info("Parsing Markdown: %s", path.name)
        rel = relative_path or path.name
        text = _read_text(path)

        # Detect embedded Mermaid blocks
        import re
        mermaid_blocks = re.findall(r"```mermaid[\s\S]*?```", text)

        # Derive title from first H1 or filename
        title = path.stem
        h1_match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if h1_match:
            title = h1_match.group(1).strip()

        return [ParsedDocument(
            doc_id=generate_doc_id(project_id, rel),
            project_id=project_id,
            source_path=str(path),
            source_type=SourceType.MARKDOWN,
            title=title,
            content_markdown=text,
            metadata={
                "mermaid_block_count": len(mermaid_blocks),
                "char_count": len(text),
            },
            parse_method="markdown_passthrough",
        )]
