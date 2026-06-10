"""Code/config file parser: wrap source files in fenced markdown code blocks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chardet

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

_LANG_MAP = {
    ".js": "javascript", ".ts": "typescript", ".css": "css", ".html": "html",
    ".htm": "html", ".py": "python", ".java": "java", ".sh": "bash",
    ".bat": "bat", ".sql": "sql", ".xml": "xml", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".properties": "properties",
    ".toml": "toml", ".ini": "ini", ".md": "markdown", ".txt": "text",
    ".log": "text",
}

_HANDLED_TYPES = {SourceType.CODE, SourceType.PLAINTEXT, SourceType.UNKNOWN}


def _detect_encoding(path: Path) -> str:
    raw = path.read_bytes()[:8000]
    result = chardet.detect(raw)
    enc = result.get("encoding") or "utf-8"
    if enc.lower() in ("shift_jis", "shift-jis", "sjis", "cp932"):
        return "shift_jis"
    if enc.lower() in ("gb2312", "gbk", "gb18030"):
        return "GB18030"
    return enc


def _read_text(path: Path) -> str:
    enc = _detect_encoding(path)
    for candidate in [enc, "utf-8", "utf-8-sig", "shift_jis", "GB18030", "latin-1"]:
        try:
            return path.read_text(encoding=candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_bytes().decode("utf-8", errors="replace")


class CodeParser(BaseParser):
    """Parse code and config files into fenced markdown code blocks."""

    @property
    def name(self) -> str:
        return "code_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        if source_type in _HANDLED_TYPES:
            return True
        # Also handle .js/.css classified as UNKNOWN
        return path.suffix.lower() in _LANG_MAP

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        logger.info("Parsing code: %s", path.name)
        rel = relative_path or path.name

        ext = path.suffix.lower()
        lang = _LANG_MAP.get(ext, "text")
        text = _read_text(path)

        content = f"# {path.name}\n\n```{lang}\n{text}\n```\n"

        return [ParsedDocument(
            doc_id=generate_doc_id(project_id, rel),
            project_id=project_id,
            source_path=str(path),
            source_type=SourceType.CODE,
            title=path.name,
            content_markdown=content,
            metadata={
                "language": lang,
                "file_size_bytes": path.stat().st_size if path.exists() else 0,
                "line_count": text.count("\n") + 1,
            },
            parse_method="code_fenced",
        )]
