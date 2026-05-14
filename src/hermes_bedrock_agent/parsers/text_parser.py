"""Text parser — handles markdown, plaintext, code, SQL, config files.

Extracts text content with section structure and metadata.
Supports: .md, .txt, .py, .java, .js, .ts, .sql, .ddl, .yaml, .json, .xml
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.parsers.base import BaseParser, ParserContext, ParserOutput
from hermes_bedrock_agent.schemas.document import NormalizedDocument, SourceType
from hermes_bedrock_agent.utils.hashing import content_hash

logger = get_logger(__name__)

# Regex patterns for section detection
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_SQL_SECTION_RE = re.compile(r"^--\s*=+\s*(.+?)\s*=*\s*$", re.MULTILINE)
_CODE_CLASS_RE = re.compile(r"^(?:class|def|function|public\s+class)\s+(\w+)", re.MULTILINE)


class TextParser(BaseParser):
    """Parser for text-based files (markdown, code, SQL, config).

    Extracts:
    - Full text content
    - Section titles (from headings, comments, class/function defs)
    - Line count and metadata
    """

    @property
    def parser_name(self) -> str:
        return "TextParser"

    def parse(self, ctx: ParserContext) -> ParserOutput:
        """Parse a text-based file.

        Args:
            ctx: Parser context with document and content bytes.

        Returns:
            ParserOutput with NormalizedDocument containing full text + sections.
        """
        text = ctx.text
        doc = ctx.document
        sections = self._extract_sections(text, doc.source_type)
        line_count = text.count("\n") + 1

        normalized = NormalizedDocument(
            document_id=doc.document_id,
            source_uri=doc.source_uri,
            source_type=doc.source_type,
            title=self._infer_title(text, doc),
            content=text,
            sections=sections,
            language=self._detect_language(doc),
            page_count=1,
            content_hash=content_hash(ctx.content_bytes),
            metadata={
                "parser": self.parser_name,
                "line_count": line_count,
                "char_count": len(text),
            },
            visual_block_ids=[],
            created_at=datetime.now(timezone.utc),
        )

        return ParserOutput(normalized_document=normalized)

    def _extract_sections(
        self, text: str, source_type: SourceType
    ) -> list[dict[str, str]]:
        """Extract section structure from text content."""
        sections: list[dict[str, str]] = []

        if source_type == SourceType.MARKDOWN:
            for match in _MD_HEADING_RE.finditer(text):
                level = len(match.group(1))
                title = match.group(2).strip()
                sections.append({
                    "title": title,
                    "level": str(level),
                    "offset": str(match.start()),
                })

        elif source_type == SourceType.SQL:
            for match in _SQL_SECTION_RE.finditer(text):
                sections.append({
                    "title": match.group(1).strip(),
                    "level": "1",
                    "offset": str(match.start()),
                })

        elif source_type == SourceType.CODE:
            for match in _CODE_CLASS_RE.finditer(text):
                sections.append({
                    "title": match.group(1),
                    "level": "1",
                    "offset": str(match.start()),
                })

        return sections

    def _infer_title(self, text: str, doc: SourceDocument) -> str:
        """Infer a document title from content or filename."""
        # For markdown, use first H1
        if doc.source_type == SourceType.MARKDOWN:
            match = re.match(r"^#\s+(.+)$", text, re.MULTILINE)
            if match:
                return match.group(1).strip()

        # Fall back to filename without extension
        return doc.filename.rsplit(".", 1)[0] if "." in doc.filename else doc.filename

    def _detect_language(self, doc: SourceDocument) -> str:
        """Detect language/format from source type."""
        lang_map = {
            SourceType.MARKDOWN: "markdown",
            SourceType.TEXT: "text",
            SourceType.CODE: self._code_language(doc.filename),
            SourceType.SQL: "sql",
            SourceType.CONFIG: self._config_language(doc.filename),
        }
        return lang_map.get(doc.source_type, "text")

    @staticmethod
    def _code_language(filename: str) -> str:
        """Infer programming language from filename."""
        ext_map = {
            ".py": "python",
            ".java": "java",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".go": "go",
            ".rs": "rust",
            ".c": "c",
            ".cpp": "cpp",
        }
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext_map.get(ext, "code")

    @staticmethod
    def _config_language(filename: str) -> str:
        """Infer config format from filename."""
        ext_map = {
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".xml": "xml",
            ".toml": "toml",
        }
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext_map.get(ext, "config")
