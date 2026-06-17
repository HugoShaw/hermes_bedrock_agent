"""MermaidFlowchartStrategy — structure-aware chunking for Mermaid flowcharts.

Phase 2 of the type-aware chunking refactor. Splits the single oversized
Mermaid parsed document into multiple meaningful chunks:

1. Summary chunk: overview stats, linked workbook info
2. Module chunks: one per functional subgraph (grouped if small)
3. Node table chunk: full node reference table
4. Edge table chunk: full edge/connection reference
5. Decision points chunk: branching logic
6. Business flow chunk: sequential process narrative
7. Mermaid source chunk: the original code block (for code-based retrieval)

Design principles:
- Each chunk should be independently useful for retrieval
- Chunk sizes target 2000 chars (configurable) to fit within embedding context
- Related modules are grouped together if individually too small
- The raw Mermaid source is kept as a separate chunk for code-oriented queries
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .protocol import ChunkConfig, ChunkMetadata, ChunkResult, ChunkingStrategy

logger = logging.getLogger(__name__)

# Section headers we split on
_SECTION_PATTERNS = [
    ("summary", re.compile(r"^#\s+Mermaid Flowchart Analysis", re.MULTILINE)),
    ("modules", re.compile(r"^###\s+Functional Modules \(Subgraphs\)", re.MULTILINE)),
    ("nodes", re.compile(r"^###\s+Nodes", re.MULTILINE)),
    ("edges", re.compile(r"^###\s+Edges", re.MULTILINE)),
    ("decisions", re.compile(r"^###\s+Decision Points", re.MULTILINE)),
    ("business_flow", re.compile(r"^###\s+Business Flow", re.MULTILINE)),
    ("mermaid_source", re.compile(r"^###\s+Original Mermaid Source", re.MULTILINE)),
]

# Pattern to split modules into individual subgraphs
_MODULE_HEADER = re.compile(r"^####\s+(.+)$", re.MULTILINE)


@dataclass
class _Section:
    """Internal: a named section extracted from the document."""
    name: str
    text: str
    start: int
    end: int


class MermaidFlowchartStrategy:
    """Chunk Mermaid flowchart documents into structure-aware pieces.

    Produces multiple chunks from a single mermaid_parsed.md file:
    - Summary (overview, stats, linkage)
    - Module groups (functional subgraphs, grouped by target size)
    - Node table (or split if very large)
    - Edge table (or split if very large)
    - Decision points
    - Business flow
    - Mermaid source code
    """

    @property
    def name(self) -> str:
        return "mermaid_flowchart"

    def chunk(
        self,
        body: str,
        metadata: ChunkMetadata,
        config: ChunkConfig,
    ) -> list[ChunkResult]:
        """Split mermaid document into structure-aware chunks."""
        if not body.strip():
            return []

        sections = self._extract_sections(body)
        results: list[ChunkResult] = []

        # 1. Summary chunk (everything before first ### section)
        summary_section = sections.get("summary")
        if summary_section and len(summary_section.text.strip()) >= config.min_chars:
            results.append(ChunkResult(
                text=summary_section.text.strip(),
                chunk_type="mermaid_overview",
                section_name="Mermaid Flowchart Overview",
                embedding_text=self._build_summary_embedding(
                    summary_section.text.strip(), metadata
                ),
            ))

        # 2. Module chunks (split per subgraph, group small ones)
        modules_section = sections.get("modules")
        if modules_section:
            module_chunks = self._split_modules(
                modules_section.text, metadata, config
            )
            results.extend(module_chunks)

        # 3. Node table chunk(s)
        nodes_section = sections.get("nodes")
        if nodes_section and len(nodes_section.text.strip()) >= config.min_chars:
            node_chunks = self._split_table_section(
                nodes_section.text.strip(),
                "mermaid_node_table",
                "Nodes",
                metadata,
                config,
            )
            results.extend(node_chunks)

        # 4. Edge table chunk(s)
        edges_section = sections.get("edges")
        if edges_section and len(edges_section.text.strip()) >= config.min_chars:
            edge_chunks = self._split_table_section(
                edges_section.text.strip(),
                "mermaid_edge_table",
                "Edges",
                metadata,
                config,
            )
            results.extend(edge_chunks)

        # 5. Decision points chunk
        decisions_section = sections.get("decisions")
        if decisions_section and len(decisions_section.text.strip()) >= config.min_chars:
            results.append(ChunkResult(
                text=decisions_section.text.strip(),
                chunk_type="mermaid_decisions",
                section_name="Decision Points",
                embedding_text=self._build_section_embedding(
                    decisions_section.text.strip(), "Decision Points", metadata
                ),
            ))

        # 6. Business flow chunk
        flow_section = sections.get("business_flow")
        if flow_section and len(flow_section.text.strip()) >= config.min_chars:
            flow_chunks = self._split_business_flow(
                flow_section.text.strip(), metadata, config
            )
            results.extend(flow_chunks)

        # 7. Mermaid source chunk — EXCLUDED from embeddable chunks.
        # Raw Mermaid code is stored at intermediates/mermaid/mermaid_raw.mmd
        # and should not be embedded (oversized, low retrieval value for
        # natural-language queries). If code-level retrieval is needed in the
        # future, it can be re-enabled with proper splitting.
        # (source_section intentionally not emitted)

        # If we got nothing (document didn't match expected structure),
        # fall back to single chunk
        if not results and len(body.strip()) >= config.min_chars:
            results.append(ChunkResult(
                text=body.strip(),
                chunk_type="mermaid_flowchart",
                section_name="Mermaid Flowchart",
            ))

        return results

    def _extract_sections(self, body: str) -> dict[str, _Section]:
        """Extract named sections from the mermaid document."""
        # Find all section boundaries
        boundaries: list[tuple[str, int]] = []
        for name, pattern in _SECTION_PATTERNS:
            match = pattern.search(body)
            if match:
                boundaries.append((name, match.start()))

        # Sort by position
        boundaries.sort(key=lambda x: x[1])

        # Extract text between boundaries
        sections: dict[str, _Section] = {}
        for i, (name, start) in enumerate(boundaries):
            end = boundaries[i + 1][1] if i + 1 < len(boundaries) else len(body)
            sections[name] = _Section(
                name=name,
                text=body[start:end],
                start=start,
                end=end,
            )

        # If no sections found, treat whole body as summary
        if not sections and body.strip():
            sections["summary"] = _Section(
                name="summary", text=body, start=0, end=len(body)
            )

        return sections

    def _split_modules(
        self,
        text: str,
        metadata: ChunkMetadata,
        config: ChunkConfig,
    ) -> list[ChunkResult]:
        """Split functional modules section into per-subgraph chunks.

        Groups small adjacent modules together to reach target_chars.
        """
        # Find all #### headers
        splits = list(_MODULE_HEADER.finditer(text))
        if not splits:
            # No sub-headers; emit as single chunk if large enough
            if len(text.strip()) >= config.min_chars:
                return [ChunkResult(
                    text=text.strip(),
                    chunk_type="mermaid_modules",
                    section_name="Functional Modules",
                    embedding_text=self._build_section_embedding(
                        text.strip(), "Functional Modules", metadata
                    ),
                )]
            return []

        # Extract individual module texts
        modules: list[tuple[str, str]] = []  # (title, text)
        for i, match in enumerate(splits):
            title = match.group(1).strip()
            start = match.start()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            module_text = text[start:end].strip()
            modules.append((title, module_text))

        # Group modules by target size
        results: list[ChunkResult] = []
        group_titles: list[str] = []
        group_text: list[str] = []
        group_chars = 0

        for title, module_text in modules:
            module_len = len(module_text)

            # If adding this module exceeds max_chars and we already have content,
            # flush the current group
            if group_chars + module_len > config.max_chars and group_text:
                results.append(self._make_module_chunk(
                    group_titles, group_text, metadata
                ))
                group_titles = []
                group_text = []
                group_chars = 0

            group_titles.append(title)
            group_text.append(module_text)
            group_chars += module_len

            # If this single module exceeds target and we have a group,
            # flush when we reach target
            if group_chars >= config.target_chars:
                results.append(self._make_module_chunk(
                    group_titles, group_text, metadata
                ))
                group_titles = []
                group_text = []
                group_chars = 0

        # Flush remaining
        if group_text:
            combined = "\n\n".join(group_text)
            if len(combined.strip()) >= config.min_chars:
                results.append(self._make_module_chunk(
                    group_titles, group_text, metadata
                ))

        return results

    def _make_module_chunk(
        self,
        titles: list[str],
        texts: list[str],
        metadata: ChunkMetadata,
    ) -> ChunkResult:
        """Create a chunk from grouped modules."""
        combined = "\n\n".join(texts)
        if len(titles) == 1:
            section_name = f"Module: {titles[0]}"
        else:
            section_name = f"Modules: {titles[0]}...{titles[-1]} ({len(titles)} modules)"

        # Extract APIs mentioned in these modules
        apis = self._extract_apis(combined)

        return ChunkResult(
            text=combined,
            chunk_type="mermaid_module",
            section_name=section_name,
            embedding_text=self._build_section_embedding(
                combined, section_name, metadata
            ),
            apis=apis,
        )

    def _split_table_section(
        self,
        text: str,
        chunk_type: str,
        section_label: str,
        metadata: ChunkMetadata,
        config: ChunkConfig,
    ) -> list[ChunkResult]:
        """Split a table section if it exceeds max_chars."""
        if len(text) <= config.max_chars:
            return [ChunkResult(
                text=text,
                chunk_type=chunk_type,
                section_name=section_label,
                embedding_text=self._build_section_embedding(
                    text[:2000], section_label, metadata
                ),
            )]

        # Split table at row boundaries
        lines = text.split("\n")
        header_lines: list[str] = []
        data_lines: list[str] = []
        in_header = True

        for line in lines:
            if in_header:
                header_lines.append(line)
                # After the |---| separator, switch to data
                if re.match(r"^\|[-|]+\|$", line.strip()):
                    in_header = False
            else:
                data_lines.append(line)

        if not data_lines:
            # No table structure found; return as-is
            return [ChunkResult(
                text=text,
                chunk_type=chunk_type,
                section_name=section_label,
            )]

        header_text = "\n".join(header_lines)
        header_len = len(header_text) + 1  # +1 for joining newline

        # Split data rows into chunks
        results: list[ChunkResult] = []
        part_num = 0
        current_rows: list[str] = []
        current_len = header_len

        for row in data_lines:
            row_len = len(row) + 1
            if current_len + row_len > config.max_chars and current_rows:
                part_num += 1
                chunk_text = header_text + "\n" + "\n".join(current_rows)
                results.append(ChunkResult(
                    text=chunk_text,
                    chunk_type=chunk_type,
                    section_name=f"{section_label} (part {part_num})",
                    embedding_text=self._build_section_embedding(
                        chunk_text[:2000], f"{section_label} part {part_num}", metadata
                    ),
                ))
                current_rows = []
                current_len = header_len

            current_rows.append(row)
            current_len += row_len

        # Flush remaining rows
        if current_rows:
            part_num += 1
            chunk_text = header_text + "\n" + "\n".join(current_rows)
            label = f"{section_label} (part {part_num})" if part_num > 1 else section_label
            results.append(ChunkResult(
                text=chunk_text,
                chunk_type=chunk_type,
                section_name=label,
                embedding_text=self._build_section_embedding(
                    chunk_text[:2000], label, metadata
                ),
            ))

        return results

    def _split_business_flow(
        self,
        text: str,
        metadata: ChunkMetadata,
        config: ChunkConfig,
    ) -> list[ChunkResult]:
        """Split business flow section if it exceeds max_chars."""
        if len(text) <= config.max_chars:
            return [ChunkResult(
                text=text,
                chunk_type="mermaid_business_flow",
                section_name="Business Flow",
                embedding_text=self._build_section_embedding(
                    text, "Business Flow", metadata
                ),
            )]

        # Split at numbered items
        items = re.split(r"(?=^\d+\.\s+)", text, flags=re.MULTILINE)
        # First item is the header text before item 1
        header = items[0] if items else ""
        numbered_items = items[1:] if len(items) > 1 else []

        if not numbered_items:
            return [ChunkResult(
                text=text,
                chunk_type="mermaid_business_flow",
                section_name="Business Flow",
            )]

        results: list[ChunkResult] = []
        part_num = 0
        current_items: list[str] = []
        current_len = len(header)

        for item in numbered_items:
            item_len = len(item)
            if current_len + item_len > config.max_chars and current_items:
                part_num += 1
                chunk_text = header + "".join(current_items)
                results.append(ChunkResult(
                    text=chunk_text.strip(),
                    chunk_type="mermaid_business_flow",
                    section_name=f"Business Flow (part {part_num})",
                    embedding_text=self._build_section_embedding(
                        chunk_text.strip()[:2000],
                        f"Business Flow part {part_num}",
                        metadata,
                    ),
                ))
                current_items = []
                current_len = len(header)

            current_items.append(item)
            current_len += item_len

        if current_items:
            part_num += 1
            chunk_text = header + "".join(current_items)
            label = f"Business Flow (part {part_num})" if part_num > 1 else "Business Flow"
            results.append(ChunkResult(
                text=chunk_text.strip(),
                chunk_type="mermaid_business_flow",
                section_name=label,
                embedding_text=self._build_section_embedding(
                    chunk_text.strip()[:2000], label, metadata
                ),
            ))

        return results

    def _build_summary_embedding(self, text: str, metadata: ChunkMetadata) -> str:
        """Build embedding text for the summary chunk."""
        display = metadata.display_name or "Mermaid Flowchart"
        workbook = metadata.workbook_name or ""
        prefix_parts = [
            f"EAIシステム連携フローチャート概要: {display}",
        ]
        if workbook:
            prefix_parts.append(f"関連ワークブック: {workbook}")
        prefix = " | ".join(prefix_parts)
        # Use first 1500 chars of text for embedding
        return f"{prefix}\n{text[:1500]}"

    def _build_section_embedding(
        self, text: str, section_name: str, metadata: ChunkMetadata
    ) -> str:
        """Build embedding text for a named section."""
        display = metadata.display_name or "Mermaid Flowchart"
        prefix = f"EAIフローチャート {display} - {section_name}"
        # Limit text to reasonable embedding size
        return f"{prefix}\n{text[:2000]}"

    def _extract_apis(self, text: str) -> list[str]:
        """Extract API references from module text."""
        # Look for patterns like GET:, POST:, PUT:, DELETE:
        api_pattern = re.compile(
            r"(GET|POST|PUT|DELETE)[:：]\s*([^\n|]+)", re.IGNORECASE
        )
        apis = []
        for match in api_pattern.finditer(text):
            api_name = f"{match.group(1)}:{match.group(2).strip()}"
            if api_name not in apis:
                apis.append(api_name)
        return apis
