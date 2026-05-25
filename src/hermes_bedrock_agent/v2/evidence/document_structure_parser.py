"""
Document structure parser for the V2 evidence pipeline.

Converts raw document bytes into a list of SectionRecord objects.

Strategy per file type
----------------------
  text / md       — heading-aware split (##, ===, ---)
  SQL / DDL       — statement-level split on semicolons / CREATE/ALTER keywords
  Java/Python/JS  — class / function detection via simple regex
  docx            — paragraph & heading based (via python-docx when available)
  xlsx / pptx     — single root section (content extraction skipped)
  csv             — single root section (first N rows as text)
  xml/yaml/json/
  properties      — single root section (full text)
  unknown         — single root section
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.schemas.document_schema import DocumentRecord, SectionRecord

logger = logging.getLogger(__name__)

# Max chars to keep per SQL statement section
_SQL_STMT_MAX = 4000
# Max rows in a CSV preview
_CSV_PREVIEW_ROWS = 100


class DocumentStructureParser:
    """Convert document bytes into SectionRecord objects.

    Usage::

        parser = DocumentStructureParser()
        sections = parser.parse(doc_record, raw_bytes)
    """

    def parse(self, doc: DocumentRecord, raw: bytes) -> list[SectionRecord]:
        """Parse *raw* bytes for *doc* and return section records."""
        ext = Path(doc.source_path).suffix.lower()
        try:
            if ext in (".sql", ".ddl"):
                return self._parse_sql(doc, raw)
            if ext in (".java", ".py", ".js", ".ts"):
                return self._parse_code(doc, raw, ext)
            if ext in (".md", ".txt"):
                return self._parse_text_or_md(doc, raw, ext)
            if ext == ".docx":
                return self._parse_docx(doc, raw)
            if ext in (".xlsx", ".pptx"):
                return self._parse_binary_opaque(doc, ext)
            if ext == ".csv":
                return self._parse_csv(doc, raw)
            if ext in (".xml", ".yaml", ".yml", ".json", ".properties"):
                return self._parse_config(doc, raw)
            return self._single_root_section(doc, "")
        except Exception as exc:
            logger.warning("Structure parse failed for %s: %s", doc.source_path, exc)
            return self._single_root_section(doc, "")

    # ------------------------------------------------------------------
    # Per-type parsers
    # ------------------------------------------------------------------

    def _parse_text_or_md(self, doc: DocumentRecord, raw: bytes, ext: str) -> list[SectionRecord]:
        text = _decode(raw)
        if ext == ".md" or _looks_like_markdown(text):
            return self._split_by_markdown_headings(doc, text)
        return self._split_plain_text(doc, text)

    def _split_by_markdown_headings(self, doc: DocumentRecord, text: str) -> list[SectionRecord]:
        heading_re = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        parts = heading_re.split(text)
        # parts alternates: [pre, hashes, title, body, hashes, title, body, ...]
        sections: list[SectionRecord] = []
        heading_stack: list[tuple[int, str]] = []  # (level, title)
        idx = 0

        # Leading preamble before first heading
        preamble = parts[0].strip()
        if preamble:
            sec = _make_section(doc, "root", [], 0, preamble, idx)
            sections.append(sec)
            idx += 1

        i = 1
        while i < len(parts) - 2:
            hashes = parts[i]
            title = parts[i + 1].strip()
            body = parts[i + 2]
            level = len(hashes)

            # Maintain heading stack
            heading_stack = [(l, t) for l, t in heading_stack if l < level]
            heading_stack.append((level, title))
            path = [t for _, t in heading_stack]

            sec = _make_section(doc, title, path, level, body.strip(), idx)
            sections.append(sec)
            idx += 1
            i += 3

        return sections or self._single_root_section(doc, text)

    def _split_plain_text(self, doc: DocumentRecord, text: str) -> list[SectionRecord]:
        # Look for setext-style headings (underline with === or ---)
        setext_re = re.compile(r"^(.+)\n([=\-]{3,})\s*$", re.MULTILINE)
        parts = setext_re.split(text)
        if len(parts) > 1:
            sections: list[SectionRecord] = []
            idx = 0
            preamble = parts[0].strip()
            if preamble:
                sections.append(_make_section(doc, "root", [], 0, preamble, idx))
                idx += 1
            i = 1
            while i < len(parts) - 1:
                title = parts[i].strip()
                underline = parts[i + 1]
                body = parts[i + 2] if i + 2 < len(parts) else ""
                level = 1 if underline.startswith("=") else 2
                path = [title]
                sections.append(_make_section(doc, title, path, level, body.strip(), idx))
                idx += 1
                i += 3
            return sections

        return self._single_root_section(doc, text)

    def _parse_sql(self, doc: DocumentRecord, raw: bytes) -> list[SectionRecord]:
        text = _decode(raw)
        statements = _split_sql_statements(text)
        sections: list[SectionRecord] = []
        for i, stmt in enumerate(statements):
            stmt = stmt.strip()
            if not stmt:
                continue
            title = _sql_statement_title(stmt, i)
            path = [title]
            sec = _make_section(doc, title, path, 1, stmt[:_SQL_STMT_MAX], i)
            sections.append(sec)
        return sections or self._single_root_section(doc, text)

    def _parse_code(self, doc: DocumentRecord, raw: bytes, ext: str) -> list[SectionRecord]:
        text = _decode(raw)
        if ext == ".java":
            return self._split_java(doc, text)
        if ext == ".py":
            return self._split_python(doc, text)
        # JS/TS: generic function detection
        return self._split_generic_code(doc, text)

    def _split_java(self, doc: DocumentRecord, text: str) -> list[SectionRecord]:
        # Split on class / interface declarations
        class_re = re.compile(
            r"(?m)^(?:(?:public|private|protected|abstract|final|static)\s+)*"
            r"(?:class|interface|enum)\s+(\w+)"
        )
        return _split_by_pattern(doc, text, class_re, label_group=1, level=1)

    def _split_python(self, doc: DocumentRecord, text: str) -> list[SectionRecord]:
        # Split on top-level class or function definitions
        py_re = re.compile(r"(?m)^(?:class|def)\s+(\w+)")
        return _split_by_pattern(doc, text, py_re, label_group=1, level=1)

    def _split_generic_code(self, doc: DocumentRecord, text: str) -> list[SectionRecord]:
        fn_re = re.compile(r"(?m)^(?:function|const|let|var)\s+(\w+)")
        return _split_by_pattern(doc, text, fn_re, label_group=1, level=1)

    def _parse_docx(self, doc: DocumentRecord, raw: bytes) -> list[SectionRecord]:
        try:
            import io
            from docx import Document as DocxDocument  # type: ignore
        except ImportError:
            logger.warning("python-docx not installed; skipping docx content for %s", doc.source_path)
            return self._single_root_section(doc, "")

        try:
            d = DocxDocument(io.BytesIO(raw))
        except Exception as exc:
            logger.warning("Failed to open docx %s: %s", doc.source_path, exc)
            return self._single_root_section(doc, "")

        sections: list[SectionRecord] = []
        heading_stack: list[tuple[int, str]] = []
        current_title = "root"
        current_path: list[str] = []
        current_level = 0
        current_buf: list[str] = []
        sec_idx = 0

        def flush() -> None:
            nonlocal sec_idx
            body = "\n".join(current_buf).strip()
            if body:
                sec = _make_section(doc, current_title, current_path[:], current_level, body, sec_idx)
                sections.append(sec)
                sec_idx += 1
            current_buf.clear()

        for para in d.paragraphs:
            style_name = para.style.name if para.style else ""
            text = para.text.strip()
            if not text:
                continue

            if style_name.startswith("Heading"):
                flush()
                try:
                    level = int(style_name.split()[-1])
                except (ValueError, IndexError):
                    level = 1
                heading_stack = [(l, t) for l, t in heading_stack if l < level]
                heading_stack.append((level, text))
                current_title = text
                current_path = [t for _, t in heading_stack]
                current_level = level
            else:
                current_buf.append(text)

        flush()
        return sections or self._single_root_section(doc, "")

    def _parse_binary_opaque(self, doc: DocumentRecord, ext: str) -> list[SectionRecord]:
        """Xlsx/pptx: create a single placeholder section."""
        note = f"[{ext.lstrip('.')} file — content extraction not supported in this stage]"
        return self._single_root_section(doc, note)

    def _parse_csv(self, doc: DocumentRecord, raw: bytes) -> list[SectionRecord]:
        text = _decode(raw)
        rows = text.splitlines()[:_CSV_PREVIEW_ROWS]
        preview = "\n".join(rows)
        return self._single_root_section(doc, preview)

    def _parse_config(self, doc: DocumentRecord, raw: bytes) -> list[SectionRecord]:
        text = _decode(raw)
        return self._single_root_section(doc, text)

    def _single_root_section(self, doc: DocumentRecord, text: str) -> list[SectionRecord]:
        sec = _make_section(doc, doc.title or "root", [], 0, text, 0)
        return [sec]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "shift-jis", "euc-jp", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _looks_like_markdown(text: str) -> bool:
    return bool(re.search(r"^#{1,6}\s+", text, re.MULTILINE))


def _make_section(
    doc: DocumentRecord,
    title: str,
    heading_path: list[str],
    level: int,
    text: str,
    idx: int,
) -> SectionRecord:
    # Use index as tiebreaker so identical headings get unique IDs
    path_for_id = heading_path + [str(idx)] if heading_path else [str(idx)]
    section_id = SectionRecord.generate_id(doc.document_id, path_for_id)
    return SectionRecord(
        section_id=section_id,
        document_id=doc.document_id,
        title=title,
        heading_path=heading_path,
        level=level,
        text=text,
        metadata={
            "doc_type": doc.doc_type,
            "source_path": doc.source_path,
            "section_index": idx,
        },
    )


def _split_sql_statements(text: str) -> list[str]:
    """Split SQL text into individual statements."""
    # Remove single-line comments
    text = re.sub(r"--[^\n]*", "", text)
    # Remove multi-line comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # Primary split: on semicolons
    stmts = [s.strip() for s in text.split(";")]

    # If the file has very few semicolons, try keyword-based split
    if len([s for s in stmts if s]) < 2:
        kw_re = re.compile(
            r"(?=\b(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|SELECT|GRANT|REVOKE|COMMENT)\b)",
            re.IGNORECASE,
        )
        stmts = [s.strip() for s in kw_re.split(text)]

    return [s for s in stmts if s]


def _sql_statement_title(stmt: str, idx: int) -> str:
    first_line = stmt.strip().splitlines()[0][:120]
    # Try to extract the object name from CREATE TABLE / CREATE INDEX etc.
    m = re.match(
        r"(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX|VIEW|PROCEDURE|FUNCTION|TRIGGER)\s+(\S+)",
        first_line,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip("`\"'[]")
    return f"stmt_{idx:04d}"


def _split_by_pattern(
    doc: DocumentRecord,
    text: str,
    pattern: re.Pattern[str],
    label_group: int,
    level: int,
) -> list[SectionRecord]:
    """Split *text* into sections at every match of *pattern*."""
    matches = list(pattern.finditer(text))
    if not matches:
        return DocumentStructureParser()._single_root_section(doc, text)

    sections: list[SectionRecord] = []
    parser = DocumentStructureParser()

    # Preamble before first match
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(_make_section(doc, "preamble", ["preamble"], 0, preamble, 0))

    for i, m in enumerate(matches):
        title = m.group(label_group)
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        path = [title]
        sections.append(_make_section(doc, title, path, level, body, i + 1))

    return sections
