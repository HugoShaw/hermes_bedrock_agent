"""Context builder — constructs structured prompt context from fused evidence.

Produces a formatted context string for LLM answer generation:
- Text Evidence section
- Graph Context section
- Source Citations
- Graph Paths
- Missing Evidence Warning (when evidence is insufficient)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.retrieval import FusedContext, GraphEvidence, TextEvidence

logger = get_logger(__name__)

# Type alias for chunk text resolver callback
ChunkTextResolver = Callable[[list[str]], dict[str, str]]


@dataclass
class ContextBuilderConfig:
    """Configuration for context building."""

    max_text_chars: int = 8000
    max_graph_chars: int = 4000
    include_citations: bool = True
    include_graph_paths: bool = True
    include_missing_warning: bool = True
    min_evidence_threshold: int = 1  # Minimum evidence items to avoid warning
    include_graph_chunk_text: bool = True  # Resolve graph source_chunk_ids to text
    language: str = "auto"  # auto, en, ja, zh


class ContextBuilder:
    """Builds structured prompt context from FusedContext.

    Produces formatted sections that the answer generator can include
    directly in the LLM prompt.

    Supports optional chunk_text_resolver callback to look up chunk text
    from source_chunk_ids found in GraphEvidence. This allows graph evidence
    to be enriched with the actual text content of referenced chunks.
    """

    def __init__(
        self,
        config: Optional[ContextBuilderConfig] = None,
        chunk_text_resolver: Optional[ChunkTextResolver] = None,
    ):
        """Initialize context builder.

        Args:
            config: Builder configuration.
            chunk_text_resolver: Optional callback that takes a list of chunk_ids
                and returns dict[chunk_id, text]. Used to resolve graph evidence
                source_chunk_ids to actual text content.
        """
        self.config = config or ContextBuilderConfig()
        self._chunk_resolver = chunk_text_resolver

    def build_context(self, fused: FusedContext) -> str:
        """Build complete structured context string.

        Args:
            fused: FusedContext from the fusion stage.

        Returns:
            Formatted context string for LLM prompt injection.
        """
        sections: list[str] = []

        # Text Evidence section
        text_section = self._build_text_section(fused.text_evidence)
        if text_section:
            sections.append(text_section)

        # Graph Context section
        graph_section = self._build_graph_section(fused.graph_evidence)
        if graph_section:
            sections.append(graph_section)

        # Graph Paths section
        if self.config.include_graph_paths:
            paths_section = self._build_paths_section(fused.graph_evidence)
            if paths_section:
                sections.append(paths_section)

        # Graph Source Text section (resolved chunk text for graph evidence)
        if self.config.include_graph_chunk_text and self._chunk_resolver:
            chunk_text_section = self._build_graph_chunk_text_section(fused.graph_evidence)
            if chunk_text_section:
                sections.append(chunk_text_section)

        # Source Citations section
        if self.config.include_citations:
            citations_section = self._build_citations_section(
                fused.text_evidence, fused.graph_evidence
            )
            if citations_section:
                sections.append(citations_section)

        # Missing Evidence Warning
        if self.config.include_missing_warning:
            warning = self._build_missing_warning(fused)
            if warning:
                sections.append(warning)

        return "\n\n".join(sections)

    def _build_text_section(self, evidence: list[TextEvidence]) -> str:
        """Build the Text Evidence section."""
        if not evidence:
            return ""

        lines = ["## Text Evidence"]
        char_count = 0

        for i, ev in enumerate(evidence):
            if char_count >= self.config.max_text_chars:
                lines.append(f"... ({len(evidence) - i} more items truncated)")
                break

            header = f"[T{i + 1}]"
            if ev.source_uri:
                header += f" Source: {ev.source_uri}"
            if ev.page is not None:
                header += f" (p.{ev.page})"
            if ev.section_title:
                header += f" § {ev.section_title}"

            lines.append(header)
            lines.append(ev.content)
            lines.append("")
            char_count += len(ev.content) + len(header)

        return "\n".join(lines)

    def _build_graph_section(self, evidence: list[GraphEvidence]) -> str:
        """Build the Graph Context section."""
        if not evidence:
            return ""

        lines = ["## Graph Context"]
        char_count = 0

        for i, ev in enumerate(evidence):
            if char_count >= self.config.max_graph_chars:
                lines.append(f"... ({len(evidence) - i} more items truncated)")
                break

            header = f"[G{i + 1}]"
            if ev.entity_id:
                header += f" Entity: {ev.entity_id}"
            if ev.hop_count > 0:
                header += f" (depth: {ev.hop_count})"

            lines.append(header)
            lines.append(ev.content)
            lines.append("")
            char_count += len(ev.content) + len(header)

        return "\n".join(lines)

    def _build_paths_section(self, evidence: list[GraphEvidence]) -> str:
        """Build the Graph Paths section."""
        paths = [ev for ev in evidence if ev.path_description]
        if not paths:
            return ""

        lines = ["## Graph Paths"]
        for i, ev in enumerate(paths[:10]):  # Max 10 paths
            lines.append(f"  Path {i + 1}: {ev.path_description}")

        return "\n".join(lines)

    def _build_citations_section(
        self,
        text_evidence: list[TextEvidence],
        graph_evidence: list[GraphEvidence],
    ) -> str:
        """Build the Source Citations section."""
        lines = ["## Source Citations"]
        seen_sources: set[str] = set()

        for i, ev in enumerate(text_evidence):
            source_key = ev.source_uri or ev.chunk_id
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)

            citation = f"  [T{i + 1}] chunk_id={ev.chunk_id}"
            if ev.source_uri:
                citation += f" uri={ev.source_uri}"
            if ev.page is not None:
                citation += f" page={ev.page}"
            lines.append(citation)

        for i, ev in enumerate(graph_evidence):
            if ev.source_chunk_ids:
                chunks_str = ", ".join(ev.source_chunk_ids[:3])
                lines.append(f"  [G{i + 1}] source_chunks=[{chunks_str}]")

        if len(lines) == 1:
            return ""  # No citations to show

        return "\n".join(lines)

    def _build_graph_chunk_text_section(self, evidence: list[GraphEvidence]) -> str:
        """Resolve graph source_chunk_ids to actual chunk text.

        Uses the chunk_text_resolver callback to look up text for chunk_ids
        referenced by graph evidence. This bridges graph → text evidence.
        """
        if not self._chunk_resolver:
            return ""

        # Collect all unique chunk_ids from graph evidence
        all_chunk_ids: list[str] = []
        for ev in evidence:
            all_chunk_ids.extend(ev.source_chunk_ids)
        all_chunk_ids = sorted(set(all_chunk_ids))

        if not all_chunk_ids:
            return ""

        try:
            resolved = self._chunk_resolver(all_chunk_ids)
        except Exception as e:
            logger.warning(f"Chunk text resolver failed: {e}")
            return ""

        if not resolved:
            return ""

        lines = ["## Graph Source Text (resolved from graph evidence)"]
        for chunk_id, text in list(resolved.items())[:5]:  # Max 5 resolved chunks
            lines.append(f"  [{chunk_id}] {text[:200]}")

        return "\n".join(lines)

    def _build_missing_warning(self, fused: FusedContext) -> str:
        """Build missing evidence warning if evidence is insufficient."""
        total = fused.total_evidence_count
        if total >= self.config.min_evidence_threshold:
            return ""

        return (
            "## ⚠ Evidence Warning\n"
            "The retrieved evidence may be insufficient to fully answer this question. "
            "Please indicate areas where further confirmation is needed."
        )
