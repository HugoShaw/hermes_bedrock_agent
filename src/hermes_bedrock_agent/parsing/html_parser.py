"""HTML parser: convert HTML to markdown using BeautifulSoup + markdownify."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chardet
from bs4 import BeautifulSoup

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

_REMOVE_TAGS = ["script", "style", "nav", "header", "footer", "noscript", "iframe", "meta"]


def _detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:20000]
    result = chardet.detect(raw)
    enc = result.get("encoding") or "utf-8"
    # Normalize common aliases
    if enc.lower() in ("shift_jis", "shift-jis", "sjis", "cp932"):
        return "shift_jis"
    if enc.lower() in ("gb2312", "gbk", "gb18030"):
        return "GB18030"
    return enc


def _read_html(path: Path) -> str:
    enc = _detect_encoding(path)
    for candidate in [enc, "utf-8", "utf-8-sig", "shift_jis", "GB18030", "latin-1"]:
        try:
            return path.read_text(encoding=candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_bytes().decode("utf-8", errors="replace")


def _html_to_markdown(html: str) -> tuple[str, str]:
    """Parse HTML, strip noise, convert to markdown. Returns (markdown, title)."""
    soup = BeautifulSoup(html, "lxml")

    # Extract title before stripping
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Remove noise tags
    for tag_name in _REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Try to find main content area
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find("div", id="content")
        or soup.find("div", class_="content")
        or soup.find("body")
        or soup
    )

    import markdownify
    md = markdownify.markdownify(str(main), heading_style="ATX", strip=["a"])

    # Clean up excessive blank lines
    import re
    md = re.sub(r"\n{3,}", "\n\n", md).strip()

    return md, title


class HtmlParser(BaseParser):
    """Parse HTML files to markdown."""

    @property
    def name(self) -> str:
        return "html_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.HTML

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        logger.info("Parsing HTML: %s", path.name)
        rel = relative_path or path.name

        html = _read_html(path)
        md, title = _html_to_markdown(html)

        if not title:
            title = path.stem

        content = f"# {title}\n\n{md}"

        return [ParsedDocument(
            doc_id=generate_doc_id(project_id, rel),
            project_id=project_id,
            source_path=str(path),
            source_type=SourceType.HTML,
            title=title,
            content_markdown=content,
            metadata={
                "html_size_bytes": len(html.encode("utf-8")),
                "markdown_chars": len(md),
            },
            parse_method="html_beautifulsoup",
        )]
