"""Protocol and data classes for type-aware chunking strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ChunkMetadata:
    """Metadata available from frontmatter + discovery context.

    Populated from YAML frontmatter in parsed markdown files and from the
    directory structure under parsed/.
    """

    source_file: str = ""
    source_type: str = ""           # excel, mermaid, csv, code, pdf, docx, html, txt
    document_type: str = ""         # flowchart, mapping, spec, field_definition, etc.
    document_role: str = ""         # data_mapping, flowchart_source, field_spec, etc.
    parser_type: str = ""           # excel_vlm, mermaid_parser, csv_parser, code, pdf_vlm, etc.
    unit_type: str = ""             # sheet, file, diagram, page
    document_name: str = ""
    document_id: str = ""
    project_id: str = ""
    display_name: str = ""
    parser_version: str = ""
    # Discovery context (from directory structure)
    parsed_subdir: str = ""         # "excel", "mermaid", "csv", "code", "pdf", etc.
    filename: str = ""              # e.g., "sheet_01.md", "mermaid_parsed.md"
    # Excel-specific
    workbook_name: str = ""
    sheet_name: str = ""
    sheet_index: int = 0


@dataclass
class ChunkConfig:
    """Chunking parameters (from Config)."""

    max_chars: int = 4000
    min_chars: int = 100
    target_chars: int = 2000
    mode: str = "semantic"


@dataclass
class ChunkResult:
    """One chunk output from a strategy.

    Strategies return a list of these. The caller (build_chunks_from_parsed_dir)
    wraps each into a full Chunk object with IDs, hashes, and project metadata.
    """

    text: str
    chunk_type: str = "overview"
    embedding_text: str = ""        # If empty, caller builds default embedding_text
    section_name: str = ""
    # Extracted metadata (optional — strategy may leave extraction to caller)
    systems: list[str] = field(default_factory=list)
    apis: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    field_codes: list[str] = field(default_factory=list)


@runtime_checkable
class ChunkingStrategy(Protocol):
    """Protocol for type-aware chunking strategies.

    Each strategy encapsulates:
    - How to split document body into chunks
    - How to infer chunk_type for each piece
    - How to build embedding_text (optional — can leave to default)
    - Which metadata fields to extract from each chunk
    """

    @property
    def name(self) -> str:
        """Strategy name for logging/debugging."""
        ...

    def chunk(
        self,
        body: str,
        metadata: ChunkMetadata,
        config: ChunkConfig,
    ) -> list[ChunkResult]:
        """Split document body into typed chunks.

        Args:
            body: Markdown body text (frontmatter already stripped)
            metadata: Document metadata from frontmatter + discovery
            config: Chunking parameters (max_chars, min_chars, mode, etc.)

        Returns:
            List of ChunkResult objects, one per output chunk.
            Empty list if body is too short or cannot be chunked.
        """
        ...
