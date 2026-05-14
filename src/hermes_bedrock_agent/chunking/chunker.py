"""Structure-aware document chunker.

Splits NormalizedDocument into DocumentChunk instances, respecting:
- Section boundaries
- Page boundaries
- Token/character limits with overlap
- Special handling for code/SQL/DDL
- VisualBlock → VISUAL_DESCRIPTION chunk generation

Produces stable chunk_ids: same input always yields same output.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.chunk import ChunkType, DocumentChunk
from hermes_bedrock_agent.schemas.document import (
    DocumentSection,
    NormalizedDocument,
    SourceType,
)
from hermes_bedrock_agent.schemas.visual import VisualBlock
from hermes_bedrock_agent.utils.hashing import content_hash, make_chunk_id

logger = get_logger(__name__)


class ChunkerConfig(BaseModel):
    """Configuration for the StructureAwareChunker."""

    chunk_size: int = Field(default=1500, ge=100, description="Target chunk size in chars")
    chunk_overlap: int = Field(default=200, ge=0, description="Overlap between consecutive chunks")
    max_chunk_size: int = Field(default=3000, ge=200, description="Hard max chunk size")
    min_chunk_size: int = Field(default=50, ge=10, description="Minimum chunk size (skip smaller)")
    code_chunk_size: int = Field(default=2000, ge=100, description="Chunk size for code/SQL")
    respect_sections: bool = Field(default=True, description="Try to split at section boundaries")
    respect_pages: bool = Field(default=True, description="Include page info in chunks")
    include_visual_chunks: bool = Field(default=True, description="Generate chunks from VisualBlocks")
    chars_per_token: float = Field(default=3.5, description="Approximate chars per token for token_count")


class StructureAwareChunker:
    """Chunks NormalizedDocument into DocumentChunk instances.

    Supports:
    - Section-aware splitting (prefer breaks at heading boundaries)
    - Page-aware metadata propagation
    - Code/SQL mode (larger chunks, break at function/class boundaries)
    - VisualBlock → VISUAL_DESCRIPTION chunk generation
    - Stable chunk_id (deterministic from content)
    """

    def __init__(self, config: Optional[ChunkerConfig] = None):
        self.config = config or ChunkerConfig()

    def chunk_document(
        self,
        document: NormalizedDocument,
        visual_blocks: Optional[list[VisualBlock]] = None,
    ) -> list[DocumentChunk]:
        """Split a NormalizedDocument into chunks.

        Args:
            document: Parsed and normalized document.
            visual_blocks: Optional VisualBlocks for generating visual chunks.

        Returns:
            Ordered list of DocumentChunks with stable IDs.
        """
        chunks: list[DocumentChunk] = []

        # 1. Text content chunks
        if document.content.strip():
            text_chunks = self._chunk_text(document)
            chunks.extend(text_chunks)

        # 2. Visual block chunks
        if self.config.include_visual_chunks and visual_blocks:
            visual_chunks = self._chunk_visual_blocks(document, visual_blocks)
            chunks.extend(visual_chunks)

        # Re-index all chunks sequentially
        for i, chunk in enumerate(chunks):
            chunk.chunk_index = i

        logger.info(
            f"Chunked document {document.document_id}: "
            f"{len(chunks)} chunks ({len(chunks) - len(visual_blocks or [])} text, "
            f"{len(visual_blocks or [])} visual)"
        )
        return chunks

    def _chunk_text(self, document: NormalizedDocument) -> list[DocumentChunk]:
        """Chunk the text content, respecting structure."""
        content = document.content
        source_type = document.source_type

        # Choose chunking strategy based on source type
        if source_type in (SourceType.CODE, SourceType.SQL, SourceType.DDL):
            return self._chunk_code(document)

        # Section-aware chunking
        if self.config.respect_sections and document.sections:
            return self._chunk_by_sections(document)

        # Fallback: simple sliding window
        return self._chunk_sliding_window(document, content)

    def _chunk_by_sections(self, document: NormalizedDocument) -> list[DocumentChunk]:
        """Split text at section boundaries with fallback to sliding window."""
        chunks: list[DocumentChunk] = []
        content = document.content
        sections = self._resolve_sections(document)

        for i, section in enumerate(sections):
            # Determine section text boundaries
            start = section.start_offset
            if section.end_offset > 0:
                end = section.end_offset
            elif i + 1 < len(sections):
                end = sections[i + 1].start_offset
            else:
                end = len(content)

            section_text = content[start:end].strip()
            if not section_text or len(section_text) < self.config.min_chunk_size:
                continue

            # If section fits in one chunk, keep it whole
            if len(section_text) <= self.config.max_chunk_size:
                chunk = self._make_chunk(
                    document=document,
                    content=section_text,
                    chunk_index=len(chunks),
                    char_start=start,
                    char_end=end,
                    section_title=section.title,
                    page=section.page,
                    visual_block_ids=section.visual_block_ids,
                )
                chunks.append(chunk)
            else:
                # Section too large: split with sliding window
                sub_chunks = self._chunk_sliding_window(
                    document, section_text,
                    base_offset=start,
                    section_title=section.title,
                    page=section.page,
                    visual_block_ids=section.visual_block_ids,
                )
                chunks.extend(sub_chunks)

        # Handle content before first section or after last section
        if not chunks and content.strip():
            chunks = self._chunk_sliding_window(document, content)

        return chunks

    def _chunk_code(self, document: NormalizedDocument) -> list[DocumentChunk]:
        """Chunk code/SQL files at logical boundaries (class/function/statement)."""
        content = document.content
        chunk_size = self.config.code_chunk_size
        chunks: list[DocumentChunk] = []

        # Split at blank lines (natural code boundaries)
        lines = content.split("\n")
        current_lines: list[str] = []
        current_start = 0
        char_pos = 0

        for line in lines:
            current_lines.append(line)
            line_end = char_pos + len(line) + 1  # +1 for \n

            current_text = "\n".join(current_lines)
            if len(current_text) >= chunk_size and line.strip() == "":
                # Break at blank line
                text = current_text.strip()
                if text and len(text) >= self.config.min_chunk_size:
                    chunk = self._make_chunk(
                        document=document,
                        content=text,
                        chunk_index=len(chunks),
                        char_start=current_start,
                        char_end=char_pos,
                        chunk_type=ChunkType.CODE,
                    )
                    chunks.append(chunk)
                current_lines = []
                current_start = line_end

            char_pos = line_end

        # Remaining lines
        remaining = "\n".join(current_lines).strip()
        if remaining and len(remaining) >= self.config.min_chunk_size:
            chunk = self._make_chunk(
                document=document,
                content=remaining,
                chunk_index=len(chunks),
                char_start=current_start,
                char_end=len(content),
                chunk_type=ChunkType.CODE,
            )
            chunks.append(chunk)

        return chunks

    def _chunk_sliding_window(
        self,
        document: NormalizedDocument,
        text: str,
        *,
        base_offset: int = 0,
        section_title: str = "",
        page: Optional[int] = None,
        visual_block_ids: Optional[list[str]] = None,
    ) -> list[DocumentChunk]:
        """Simple sliding window chunking with overlap."""
        chunks: list[DocumentChunk] = []
        chunk_size = self.config.chunk_size
        overlap = self.config.chunk_overlap

        if len(text) <= chunk_size:
            if text.strip() and len(text.strip()) >= self.config.min_chunk_size:
                chunk = self._make_chunk(
                    document=document,
                    content=text.strip(),
                    chunk_index=len(chunks),
                    char_start=base_offset,
                    char_end=base_offset + len(text),
                    section_title=section_title,
                    page=page,
                    visual_block_ids=visual_block_ids,
                )
                chunks.append(chunk)
            return chunks

        pos = 0
        while pos < len(text):
            end = min(pos + chunk_size, len(text))

            # Try to break at paragraph/sentence boundary
            if end < len(text):
                # Look for paragraph break
                para_break = text.rfind("\n\n", pos, end)
                if para_break > pos + chunk_size // 3:
                    end = para_break + 2
                else:
                    # Look for sentence break
                    for sep in (". ", "。", ".\n", "\n"):
                        sent_break = text.rfind(sep, pos + chunk_size // 2, end)
                        if sent_break > pos:
                            end = sent_break + len(sep)
                            break

            chunk_text = text[pos:end].strip()
            if chunk_text and len(chunk_text) >= self.config.min_chunk_size:
                chunk = self._make_chunk(
                    document=document,
                    content=chunk_text,
                    chunk_index=len(chunks),
                    char_start=base_offset + pos,
                    char_end=base_offset + end,
                    section_title=section_title,
                    page=page,
                    visual_block_ids=visual_block_ids,
                )
                chunks.append(chunk)

            # Advance — ensure forward progress to prevent infinite loops
            if end >= len(text):
                break
            new_pos = end - overlap
            if new_pos <= pos:
                new_pos = pos + max(1, chunk_size // 2)
            pos = new_pos

        return chunks

    def _chunk_visual_blocks(
        self,
        document: NormalizedDocument,
        visual_blocks: list[VisualBlock],
    ) -> list[DocumentChunk]:
        """Generate VISUAL_DESCRIPTION chunks from VisualBlocks.

        Produces embedding-friendly text from visual analysis results.
        Does NOT include image_base64 in chunk content.
        """
        chunks: list[DocumentChunk] = []

        for vb in visual_blocks:
            text_parts: list[str] = []

            if vb.visual_summary:
                text_parts.append(f"[Visual: {vb.visual_type.value}] {vb.visual_summary}")

            if vb.extracted_text:
                text_parts.append(f"Extracted text: {vb.extracted_text}")

            if vb.table_markdown:
                text_parts.append(f"Table:\n{vb.table_markdown}")

            if vb.diagram_nodes:
                nodes_str = ", ".join(vb.diagram_nodes[:20])
                text_parts.append(f"Diagram nodes: {nodes_str}")

            if vb.diagram_edges:
                edges_str = "; ".join(vb.diagram_edges[:20])
                text_parts.append(f"Diagram edges: {edges_str}")

            if vb.detected_entities:
                entities_str = ", ".join(vb.detected_entities[:20])
                text_parts.append(f"Detected entities: {entities_str}")

            chunk_text = "\n".join(text_parts)
            if not chunk_text.strip() or len(chunk_text.strip()) < self.config.min_chunk_size:
                continue

            chunk = self._make_chunk(
                document=document,
                content=chunk_text.strip(),
                chunk_index=len(chunks),
                char_start=0,
                char_end=0,
                page=vb.page,
                visual_block_ids=[vb.visual_id],
                chunk_type=ChunkType.VISUAL_DESCRIPTION,
            )
            chunks.append(chunk)

        return chunks

    def _resolve_sections(self, document: NormalizedDocument) -> list[DocumentSection]:
        """Convert document.sections (list[dict]) to DocumentSection list."""
        result: list[DocumentSection] = []
        for s in document.sections:
            if isinstance(s, DocumentSection):
                result.append(s)
            elif isinstance(s, dict):
                result.append(DocumentSection.from_dict(s))
            else:
                logger.warning(f"Unknown section type: {type(s)}, skipping")
        return result

    def _make_chunk(
        self,
        document: NormalizedDocument,
        content: str,
        chunk_index: int,
        char_start: int = 0,
        char_end: int = 0,
        section_title: str = "",
        page: Optional[int] = None,
        visual_block_ids: Optional[list[str]] = None,
        chunk_type: ChunkType = ChunkType.TEXT,
    ) -> DocumentChunk:
        """Create a DocumentChunk with a stable chunk_id."""
        c_hash = content_hash(content)
        chunk_id = make_chunk_id(document.document_id, chunk_index, c_hash)

        token_count = int(len(content) / self.config.chars_per_token)

        return DocumentChunk(
            chunk_id=chunk_id,
            document_id=document.document_id,
            chunk_index=chunk_index,
            content=content,
            chunk_type=chunk_type,
            token_count=token_count,
            source_uri=document.source_uri,
            source_type=document.source_type.value if document.source_type else "",
            page=page,
            section_title=section_title,
            char_start=char_start,
            char_end=char_end,
            visual_block_ids=visual_block_ids or [],
            content_hash=c_hash,
            language=document.language,
            acl=document.acl,
        )
