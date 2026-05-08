"""Code parser - handles source code and SQL/DDL files."""
from __future__ import annotations

import re
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.parsers.base import BaseParser
from hermes_bedrock_agent.s3_graph_etl.schemas import ContentType, DocumentChunk, ParserType


class CodeParser(BaseParser):
    """Parse source code files into chunks."""

    MAX_CHUNK_SIZE = 3000  # chars per chunk, larger for code

    @property
    def supported_extensions(self) -> set[str]:
        return {".py", ".java", ".js", ".ts", ".tsx", ".jsx", ".sql", ".ddl", ".yaml", ".yml", ".json", ".xml"}

    def parse(self, file_path: Path, source_uri: str) -> list[DocumentChunk]:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        source_file = Path(source_uri.split("/")[-1]).name if "/" in source_uri else source_uri
        ext = file_path.suffix.lower()

        content_type = ContentType.DDL if ext in (".sql", ".ddl") else ContentType.CODE

        # For SQL/DDL, try to split by statements
        if ext in (".sql", ".ddl"):
            return self._parse_sql(text, source_uri, source_file)

        # For Python, split by class/function definitions
        if ext == ".py":
            return self._parse_python(text, source_uri, source_file)

        # Generic: split by size
        return self._parse_generic_code(text, source_uri, source_file, content_type)

    def _parse_sql(self, text: str, source_uri: str, source_file: str) -> list[DocumentChunk]:
        """Split SQL by statements (CREATE, ALTER, etc.)."""
        # Split on common SQL statement boundaries
        statements = re.split(r"(?=\b(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|GRANT)\b)", text, flags=re.IGNORECASE)
        chunks: list[DocumentChunk] = []

        for idx, stmt in enumerate(statements):
            stmt = stmt.strip()
            if not stmt:
                continue
            chunks.append(DocumentChunk(
                id=self.make_chunk_id(source_uri, 0, idx),
                source_uri=source_uri,
                source_file=source_file,
                chunk_index=idx,
                content_type=ContentType.DDL,
                title=self._extract_sql_title(stmt),
                text=stmt,
                evidence_text=stmt[:500],
                confidence=1.0,
                parser_type=ParserType.PYTHON_PARSER,
            ))

        return chunks if chunks else [self._make_single_chunk(text, source_uri, source_file, ContentType.DDL)]

    def _parse_python(self, text: str, source_uri: str, source_file: str) -> list[DocumentChunk]:
        """Split Python by class/function definitions."""
        # Split at top-level class and function definitions
        parts = re.split(r"(?=^(?:class |def |async def ))", text, flags=re.MULTILINE)
        chunks: list[DocumentChunk] = []

        for idx, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue
            title = ""
            first_line = part.split("\n")[0]
            if first_line.startswith(("class ", "def ", "async def ")):
                title = first_line.rstrip(":")

            chunks.append(DocumentChunk(
                id=self.make_chunk_id(source_uri, 0, idx),
                source_uri=source_uri,
                source_file=source_file,
                chunk_index=idx,
                content_type=ContentType.CODE,
                title=title,
                text=part,
                evidence_text=part[:500],
                confidence=1.0,
                parser_type=ParserType.PYTHON_PARSER,
            ))

        return chunks if chunks else [self._make_single_chunk(text, source_uri, source_file, ContentType.CODE)]

    def _parse_generic_code(self, text: str, source_uri: str, source_file: str, content_type: ContentType) -> list[DocumentChunk]:
        """Split generic code by size."""
        chunks: list[DocumentChunk] = []
        lines = text.split("\n")
        current = ""
        chunk_idx = 0

        for line in lines:
            if len(current) + len(line) > self.MAX_CHUNK_SIZE and current:
                chunks.append(DocumentChunk(
                    id=self.make_chunk_id(source_uri, 0, chunk_idx),
                    source_uri=source_uri,
                    source_file=source_file,
                    chunk_index=chunk_idx,
                    content_type=content_type,
                    text=current.strip(),
                    evidence_text=current.strip()[:500],
                    confidence=1.0,
                    parser_type=ParserType.PYTHON_PARSER,
                ))
                chunk_idx += 1
                current = ""
            current += line + "\n"

        if current.strip():
            chunks.append(DocumentChunk(
                id=self.make_chunk_id(source_uri, 0, chunk_idx),
                source_uri=source_uri,
                source_file=source_file,
                chunk_index=chunk_idx,
                content_type=content_type,
                text=current.strip(),
                evidence_text=current.strip()[:500],
                confidence=1.0,
                parser_type=ParserType.PYTHON_PARSER,
            ))

        return chunks

    def _make_single_chunk(self, text: str, source_uri: str, source_file: str, content_type: ContentType) -> DocumentChunk:
        return DocumentChunk(
            id=self.make_chunk_id(source_uri, 0, 0),
            source_uri=source_uri,
            source_file=source_file,
            chunk_index=0,
            content_type=content_type,
            text=text,
            evidence_text=text[:500],
            confidence=1.0,
            parser_type=ParserType.PYTHON_PARSER,
        )

    @staticmethod
    def _extract_sql_title(stmt: str) -> str:
        """Extract table/view name from SQL statement."""
        match = re.search(r"(?:CREATE|ALTER)\s+(?:TABLE|VIEW|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\S+)", stmt, re.IGNORECASE)
        return match.group(1) if match else ""
