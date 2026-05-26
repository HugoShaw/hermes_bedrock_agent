"""Mermaid diagram generator — produces Mermaid flowchart syntax from subgraphs.

Provides:
- MermaidGenerator: generate flowcharts, impact maps, dependency maps
- Automatic label escaping and node/edge deduplication
- Support for LR/TD direction and max_nodes limiting
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.visualization import (
    SubgraphResult,
    VisualizationEdge,
    VisualizationNode,
)

logger = get_logger(__name__)


@dataclass
class MermaidConfig:
    """Configuration for Mermaid generation."""

    direction: str = "LR"  # LR (left-right) or TD (top-down)
    max_nodes: int = 30
    show_edge_labels: bool = True
    node_shape: str = "rounded"  # rounded, box, circle, stadium
    theme: str = ""  # Optional: dark, forest, neutral
    lang: str = "en"  # zh | en | ja
    label_mode: str = "technical"  # technical | business | mixed


# Node type → Mermaid shape
_SHAPES: dict[str, tuple[str, str]] = {
    "system": ("([", "])"),       # stadium
    "module": ("[", "]"),         # box
    "business_process": ("[[", "]]"),  # subroutine
    "process_step": ("(", ")"),   # rounded
    "data_source": ("[(", ")]"),  # cylinder
    "table": ("[(", ")]"),        # cylinder
    "api": ("{{", "}}"),          # hexagon
    "service": (">", "]"),        # asymmetric
    "unknown": ("[", "]"),        # box
}


def escape_mermaid_label(text: str) -> str:
    """Escape text for safe use in Mermaid labels.

    Handles special characters that break Mermaid syntax.
    """
    if not text:
        return "?"
    # Replace chars that break Mermaid
    text = text.replace('"', "'")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    text = text.replace("{", "&#123;")
    text = text.replace("}", "&#125;")
    text = text.replace("|", "&#124;")
    text = text.replace("[", "&#91;")
    text = text.replace("]", "&#93;")
    text = text.replace("(", "&#40;")
    text = text.replace(")", "&#41;")
    # Truncate long labels
    if len(text) > 40:
        text = text[:37] + "..."
    return text


def _sanitize_id(node_id: str) -> str:
    """Convert node_id to valid Mermaid node identifier.

    Rules:
    - Uses node_id directly if already ASCII-alphanumeric + underscore
    - For non-ASCII IDs (Japanese/Chinese), generates a stable hash-based ID
    - Never returns empty string — falls back to node_<8-char-hash>
    - Same input always produces same output (deterministic)
    """
    if not node_id:
        return "node_00000000"

    # First try: strip non-alnum to see if anything survives
    ascii_id = re.sub(r"[^a-zA-Z0-9_]", "_", node_id)
    # Collapse multiple underscores
    ascii_id = re.sub(r"_+", "_", ascii_id).strip("_")

    # Check if the ID is fully or predominantly ASCII
    has_non_ascii = any(ord(c) > 127 for c in node_id)

    if ascii_id and len(ascii_id) >= 3 and not has_non_ascii:
        # Good — fully ASCII node_id (e.g. "ent_shiwake", "module_001")
        return ascii_id

    # Non-ASCII content exists — use hash-based ID for stability
    import hashlib
    hash_hex = hashlib.md5(node_id.encode("utf-8")).hexdigest()[:8]
    # Try to keep a recognizable ASCII prefix if any alnum chars exist
    prefix = re.sub(r"[^a-zA-Z0-9]", "", node_id)[:6]
    if prefix and len(prefix) >= 2:
        return f"{prefix}_{hash_hex}"
    return f"node_{hash_hex}"


def resolve_i18n_label(
    node_id: str,
    node_label: str,
    *,
    i18n_data: Optional[dict[str, dict]] = None,
    lang: str = "en",
    label_mode: str = "technical",
) -> str:
    """Resolve display label based on i18n data, lang, and label_mode.

    Args:
        node_id: Entity ID or canonical_name to look up in i18n_data.
        node_label: Default label (typically canonical_name or name).
        i18n_data: Mapping of entity_id/canonical_name → i18n fields.
        lang: Target language (zh/en/ja).
        label_mode: Display mode (technical/business/mixed).

    Returns:
        Resolved display label string.
    """
    if label_mode == "technical" or not i18n_data:
        return node_label

    # Try to find i18n data by node_id or node_label (canonical_name)
    entry = i18n_data.get(node_id) or i18n_data.get(node_label.lower()) or {}

    display_name = entry.get(f"display_name_{lang}", "") or ""

    if label_mode == "business":
        return display_name if display_name else node_label

    if label_mode == "mixed":
        if display_name and display_name != node_label:
            return f"{display_name}\\n({node_label})"
        return node_label

    return node_label


class MermaidGenerator:
    """Generates Mermaid diagram syntax from visualization data.

    Supports flowcharts, impact maps, and dependency maps.
    All output is copy-paste ready for Markdown/PPT.
    """

    def __init__(self, config: Optional[MermaidConfig] = None):
        self.config = config or MermaidConfig()

    def generate_flowchart(
        self,
        subgraph: SubgraphResult,
        *,
        direction: Optional[str] = None,
        max_nodes: Optional[int] = None,
        title: str = "",
        i18n_data: Optional[dict[str, dict]] = None,
        lang: Optional[str] = None,
        label_mode: Optional[str] = None,
    ) -> str:
        """Generate a Mermaid flowchart from a subgraph.

        Args:
            subgraph: SubgraphResult with nodes and edges.
            direction: Override direction (LR/TD).
            max_nodes: Override max nodes.
            title: Optional diagram title.
            i18n_data: Optional mapping of entity_id/canonical → i18n fields.
            lang: Override language (zh/en/ja).
            label_mode: Override label mode (technical/business/mixed).

        Returns:
            Mermaid flowchart source code.
        """
        direction = direction or self.config.direction
        limit = max_nodes or self.config.max_nodes
        use_lang = lang or self.config.lang
        use_label_mode = label_mode or self.config.label_mode

        nodes = subgraph.nodes[:limit]
        node_ids = {n.node_id for n in nodes}
        edges = [e for e in subgraph.edges
                 if e.source_id in node_ids and e.target_id in node_ids]

        lines: list[str] = []

        if title:
            lines.append(f"---")
            lines.append(f"title: {title}")
            lines.append(f"---")

        lines.append(f"flowchart {direction}")

        # Generate nodes
        seen_nodes: set[str] = set()
        for node in nodes:
            sid = _sanitize_id(node.node_id)
            if sid in seen_nodes:
                continue
            seen_nodes.add(sid)

            raw_label = node.label
            # Apply i18n label resolution
            resolved_label = resolve_i18n_label(
                node.node_id, raw_label,
                i18n_data=i18n_data,
                lang=use_lang,
                label_mode=use_label_mode,
            )
            label = escape_mermaid_label(resolved_label)
            shape_open, shape_close = _SHAPES.get(
                node.entity_type, _SHAPES["unknown"]
            )
            lines.append(f"    {sid}{shape_open}\"{label}\"{shape_close}")

        # Generate edges
        seen_edges: set[str] = set()
        for edge in edges:
            src = _sanitize_id(edge.source_id)
            tgt = _sanitize_id(edge.target_id)
            edge_key = f"{src}-{tgt}-{edge.relation_type}"
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            if self.config.show_edge_labels and edge.label:
                # Resolve edge label via i18n if available
                raw_elabel = edge.label
                if i18n_data and use_label_mode != "technical":
                    from hermes_bedrock_agent.graph.i18n_enricher import (
                        BUILTIN_RELATION_I18N_MAP,
                    )
                    rel_key = edge.relation_type.lower() if edge.relation_type else ""
                    if rel_key in BUILTIN_RELATION_I18N_MAP:
                        raw_elabel = BUILTIN_RELATION_I18N_MAP[rel_key].get(
                            use_lang, raw_elabel
                        )
                elabel = escape_mermaid_label(raw_elabel)
                if edge.style == "dashed":
                    lines.append(f"    {src} -.\"{elabel}\".-> {tgt}")
                elif edge.style == "dotted":
                    lines.append(f"    {src} -..\"{elabel}\"..-> {tgt}")
                else:
                    lines.append(f"    {src} -->|\"{elabel}\"| {tgt}")
            else:
                if edge.style == "dashed":
                    lines.append(f"    {src} -.-> {tgt}")
                else:
                    lines.append(f"    {src} --> {tgt}")

        return "\n".join(lines)

    def generate_impact_map(
        self,
        subgraph: SubgraphResult,
        center_label: str = "",
        *,
        direction: str = "LR",
        max_nodes: Optional[int] = None,
    ) -> str:
        """Generate an impact analysis map.

        Shows a center entity and all entities it impacts (outgoing).

        Args:
            subgraph: SubgraphResult to visualize.
            center_label: Label for the center entity.
            direction: Diagram direction.
            max_nodes: Maximum nodes.

        Returns:
            Mermaid source for impact visualization.
        """
        return self.generate_flowchart(
            subgraph,
            direction=direction,
            max_nodes=max_nodes,
            title=f"Impact Map: {center_label}" if center_label else "Impact Map",
        )

    def generate_dependency_map(
        self,
        subgraph: SubgraphResult,
        center_label: str = "",
        *,
        direction: str = "TD",
        max_nodes: Optional[int] = None,
    ) -> str:
        """Generate a dependency map.

        Shows what a center entity depends on (incoming).

        Args:
            subgraph: SubgraphResult to visualize.
            center_label: Label for the center entity.
            direction: Diagram direction (TD recommended for dependencies).
            max_nodes: Maximum nodes.

        Returns:
            Mermaid source for dependency visualization.
        """
        return self.generate_flowchart(
            subgraph,
            direction=direction,
            max_nodes=max_nodes,
            title=f"Dependencies: {center_label}" if center_label else "Dependency Map",
        )
