"""Text/Markdown parser - handles .txt, .md, .markdown files."""
from __future__ import annotations

import re
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.parsers.base import BaseParser
from hermes_bedrock_agent.s3_graph_etl.schemas import ContentType, DocumentChunk, ParserType


class TextParser(BaseParser):
    """Parse plain text and Markdown files into chunks by heading."""

    MAX_CHUNK_SIZE = 2000  # chars per chunk

    @property
    def supported_extensions(self) -> set[str]:
        return {".txt", ".md", ".markdown"}

    def parse(self, file_path: Path, source_uri: str) -> list[DocumentChunk]:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        source_file = Path(source_uri.split("/")[-1]).name if "/" in source_uri else source_uri

        # For markdown, split by headings
        if file_path.suffix.lower() in (".md", ".markdown"):
            return self._parse_markdown(text, source_uri, source_file)

        # For plain text, split by size
        return self._parse_plain(text, source_uri, source_file)

    def _parse_markdown(self, text: str, source_uri: str, source_file: str) -> list[DocumentChunk]:
        """Split markdown by headings into chunks."""
        chunks: list[DocumentChunk] = []
        sections = re.split(r"^(#{1,6}\s+.+)$", text, flags=re.MULTILINE)

        heading_path: list[str] = []
        current_title = ""
        current_text = ""
        chunk_idx = 0

        for i, section in enumerate(sections):
            if re.match(r"^#{1,6}\s+", section):
                # Save previous section
                if current_text.strip():
                    chunks.append(self._make_chunk(
                        source_uri, source_file, current_title,
                        heading_path[:], current_text.strip(), chunk_idx
                    ))
                    chunk_idx += 1
                current_title = section.strip().lstrip("#").strip()
                heading_path = [current_title]
                current_text = ""
            else:
                current_text += section

        # Final section
        if current_text.strip():
            chunks.append(self._make_chunk(
                source_uri, source_file, current_title,
                heading_path[:], current_text.strip(), chunk_idx
            ))

        return chunks if chunks else [self._make_chunk(source_uri, source_file, "", [], text.strip(), 0)]

    def _parse_plain(self, text: str, source_uri: str, source_file: str) -> list[DocumentChunk]:
        """Split plain text by size."""
        chunks: list[DocumentChunk] = []
        lines = text.split("\n")
        current = ""
        chunk_idx = 0

        for line in lines:
            if len(current) + len(line) > self.MAX_CHUNK_SIZE and current:
                chunks.append(self._make_chunk(source_uri, source_file, "", [], current.strip(), chunk_idx))
                chunk_idx += 1
                current = ""
            current += line + "\n"

        if current.strip():
            chunks.append(self._make_chunk(source_uri, source_file, "", [], current.strip(), chunk_idx))

        return chunks

    def _make_chunk(
        self, source_uri: str, source_file: str, title: str,
        heading_path: list[str], text: str, chunk_index: int
    ) -> DocumentChunk:
        return DocumentChunk(
            id=self.make_chunk_id(source_uri, 0, chunk_index),
            source_uri=source_uri,
            source_file=source_file,
            chunk_index=chunk_index,
            content_type=ContentType.TEXT,
            title=title,
            heading_path=heading_path,
            text=text,
            evidence_text=text[:500],
            confidence=1.0,
            parser_type=ParserType.PYTHON_PARSER,
        )
