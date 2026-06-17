"""Plain text file parser: reads text content as-is into markdown.

Unlike CodeParser which wraps content in a fenced code block, TextParser
preserves the original text structure directly as markdown content.
This is appropriate for .txt, .log, and other plain text documents
that contain human-readable prose, setup guides, etc.

Also exports `post_process_all` for VLM parse result post-processing
(ensures H1 headings, extracts Mermaid blocks from parsed output).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

import chardet

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser
from .models import ParseResult

logger = logging.getLogger(__name__)

# ─── VLM post-processing (moved from archive/app_doc_pipeline/stages/markdown_post.py) ───

_MERMAID_FENCE_RE = re.compile(r"```mermaid\n.*?```", re.DOTALL)


def _structure_markdown(markdown: str, sheet_name: str) -> str:
    """Ensure the markdown starts with a top-level H1 for the sheet."""
    stripped = markdown.strip()
    if not stripped.startswith("# "):
        return f"# Sheet: {sheet_name}\n\n{stripped}"
    return stripped


def post_process_all(
    results: list[ParseResult],
    ground_truth_map: Optional[dict[str, str]] = None,
) -> list[ParseResult]:
    """Post-process all VLM parse results.

    - Ensures each sheet markdown starts with an H1 heading.
    - Extracts any mermaid code block into the `mermaid` field.

    ground_truth_map: sheet_name → path to .mmd file (optional, unused in current pipeline).
    """
    ground_truth_map = ground_truth_map or {}
    processed: list[ParseResult] = []
    for r in results:
        markdown = r.markdown
        markdown = _structure_markdown(markdown, r.sheet_info.name)

        mermaid = r.mermaid
        m = _MERMAID_FENCE_RE.search(markdown)
        if m:
            inner = m.group(0)
            mermaid = inner.replace("```mermaid\n", "").rstrip("`").rstrip()

        processed.append(r.model_copy(update={"markdown": markdown, "mermaid": mermaid}))
    return processed


def _detect_encoding(path: Path) -> str:
    """Detect file encoding with common Japanese/Chinese fallbacks."""
    raw = path.read_bytes()[:8000]
    result = chardet.detect(raw)
    enc = result.get("encoding") or "utf-8"
    if enc.lower() in ("shift_jis", "shift-jis", "sjis", "cp932"):
        return "shift_jis"
    if enc.lower() in ("gb2312", "gbk", "gb18030"):
        return "GB18030"
    return enc


def _read_text(path: Path) -> str:
    """Read text with encoding detection and fallback chain."""
    enc = _detect_encoding(path)
    for candidate in [enc, "utf-8", "utf-8-sig", "shift_jis", "GB18030", "latin-1"]:
        try:
            return path.read_text(encoding=candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_bytes().decode("utf-8", errors="replace")


class TextParser(BaseParser):
    """Parse plain text files as-is (no code fencing).

    Produces a heading followed by the raw text content. Suitable for:
    - .txt files (setup guides, README-like content, log files)
    - .log files
    - Any SourceType.PLAINTEXT file

    The output is directly chunk-ready without code block wrapping.
    """

    @property
    def name(self) -> str:
        return "text_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.PLAINTEXT

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        logger.info("Parsing text: %s", path.name)
        rel = relative_path or path.name

        text = _read_text(path)
        stem = path.stem

        # Output as a heading + raw text (preserves original structure)
        content = f"# {stem}\n\n{text}\n"

        return [ParsedDocument(
            doc_id=generate_doc_id(project_id, rel),
            project_id=project_id,
            source_path=str(path),
            source_type=SourceType.PLAINTEXT,
            title=stem,
            content_markdown=content,
            metadata={
                "file_size_bytes": path.stat().st_size if path.exists() else 0,
                "line_count": text.count("\n") + 1,
            },
            parse_method="text_passthrough",
        )]
