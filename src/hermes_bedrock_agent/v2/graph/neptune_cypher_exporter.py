"""
Neptune Cypher Exporter for Stage 09.

Converts linked graph data (nodes, edges, evidence links) into
Neptune-compatible openCypher statements for safe import.

Design decisions:
- Uses MERGE on `~id` key for idempotent upserts
- Uses SET n += {...} for properties (Neptune Analytics style)
- Exports EvidenceChunk nodes for referenced chunks
- Exports HAS_EVIDENCE edges from graph nodes to EvidenceChunk nodes
- Edge evidence kept as relationship properties (no EdgeEvidence nodes)
- Supports layer filtering (business, implementation, evidence, all)
- Deterministic output (sorted by ID)
- No SQL dump content in graph
- Safe string escaping
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any


# Neptune property value limits
MAX_STRING_PROPERTY_LENGTH = 500
MAX_LIST_LENGTH = 50
MAX_TEXT_PREVIEW_LENGTH = 200

# Labels that need renaming for Cypher compatibility
LABEL_SAFE_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def safe_label(label: str) -> str:
    """Ensure label is valid for Cypher."""
    if LABEL_SAFE_PATTERN.match(label):
        return label
    # Replace invalid chars
    cleaned = re.sub(r'[^A-Za-z0-9_]', '_', label)
    if cleaned and cleaned[0].isdigit():
        cleaned = '_' + cleaned
    return cleaned or 'Unknown'


def escape_cypher_string(value: str) -> str:
    """Escape a string for use in Cypher single-quoted literals."""
    if not value:
        return ''
    # Replace backslash first, then single quotes
    escaped = value.replace('\\', '\\\\').replace("'", "\\'")
    # Remove control characters
    escaped = re.sub(r'[\x00-\x1f\x7f]', ' ', escaped)
    return escaped


def truncate_string(value: str, max_len: int = MAX_STRING_PROPERTY_LENGTH) -> str:
    """Truncate string to max length."""
    if len(value) <= max_len:
        return value
    return value[:max_len - 3] + '...'


def format_property_value(value: Any) -> str:
    """Format a property value for Cypher SET clause."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        truncated = truncate_string(value)
        return f"'{escape_cypher_string(truncated)}'"
    if isinstance(value, list):
        # Neptune supports lists of primitives
        if not value:
            return "''"
        # Truncate list
        items = value[:MAX_LIST_LENGTH]
        if all(isinstance(v, (int, float)) for v in items):
            return f"[{', '.join(str(v) for v in items)}]"
        # String list - join as single string for Neptune compatibility
        str_items = [truncate_string(str(v), 100) for v in items]
        joined = '|'.join(str_items)
        return f"'{escape_cypher_string(truncate_string(joined))}'"
    if isinstance(value, dict):
        # Serialize dict as JSON string
        serialized = json.dumps(value, ensure_ascii=False)
        return f"'{escape_cypher_string(truncate_string(serialized))}'"
    return f"'{escape_cypher_string(truncate_string(str(value)))}'"


class NeptuneCypherExporter:
    """Generates Neptune-compatible openCypher from linked graph data."""

    def __init__(
        self,
        linked_nodes: list[dict[str, Any]],
        linked_edges: list[dict[str, Any]],
        evidence_links: list[dict[str, Any]],
        evidence_chunks: list[dict[str, Any]] | None = None,
        layer_filter: str = "all",
        run_id: str = "murata_semantic_v2",
        dataset: str = "murata",
    ):
        self.linked_nodes = linked_nodes
        self.linked_edges = linked_edges
        self.evidence_links = evidence_links
        self.evidence_chunks = evidence_chunks or []
        self.layer_filter = layer_filter
        self.run_id = run_id
        self.dataset = dataset

        # Stats
        self.stats: dict[str, Any] = {}
        self._build_indexes()

    def _build_indexes(self) -> None:
        """Build lookup indexes."""
        self.chunk_by_id: dict[str, dict] = {}
        for c in self.evidence_chunks:
            cid = c.get('chunk_id', '')
            if cid:
                self.chunk_by_id[cid] = c

        self.node_by_id: dict[str, dict] = {}
        for n in self.linked_nodes:
            self.node_by_id[n['node_id']] = n

    def _filter_by_layer(
        self, items: list[dict[str, Any]], layer_key: str = 'layer'
    ) -> list[dict[str, Any]]:
        """Filter items by layer."""
        if self.layer_filter == 'all':
            return items
        return [i for i in items if i.get(layer_key) == self.layer_filter]

    def _is_evidence_layer(self) -> bool:
        """Check if we should export evidence layer."""
        return self.layer_filter in ('all', 'evidence')

    def export(self) -> str:
        """Generate full Cypher export string."""
        now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

        # Filter items by layer
        nodes = self._filter_by_layer(self.linked_nodes)
        edges = self._filter_by_layer(self.linked_edges)

        # Sort for determinism
        nodes = sorted(nodes, key=lambda n: n['node_id'])
        edges = sorted(edges, key=lambda e: e['edge_id'])

        # Collect referenced evidence chunk IDs
        referenced_chunk_ids: set[str] = set()
        for n in nodes:
            for eid in n.get('evidence_chunk_ids', []):
                referenced_chunk_ids.add(eid)
        for e in edges:
            for eid in e.get('evidence_chunk_ids', []):
                referenced_chunk_ids.add(eid)

        # Filter out SQL dump chunks
        safe_chunk_ids = set()
        for cid in referenced_chunk_ids:
            chunk = self.chunk_by_id.get(cid, {})
            sp = (chunk.get('source_path') or '').lower()
            if 'journal_base20180530' in sp:
                continue
            safe_chunk_ids.add(cid)

        lines: list[str] = []

        # Header
        lines.append(f"// Neptune Cypher Export — Stage 09")
        lines.append(f"// Generated: {now}")
        lines.append(f"// Run ID: {self.run_id}")
        lines.append(f"// Dataset: {self.dataset}")
        lines.append(f"// Layer filter: {self.layer_filter}")
        lines.append(f"// Graph nodes: {len(nodes)}")
        lines.append(f"// Graph edges: {len(edges)}")
        lines.append(f"// Evidence chunks referenced: {len(safe_chunk_ids)}")
        lines.append(f"//")
        lines.append(f"// USAGE:")
        lines.append(f"//   This file is for review/documentation.")
        lines.append(f"//   Actual Neptune loading uses parameterized queries via neptune_loader.py.")
        lines.append(f"//   Do NOT execute this file directly against Neptune without review.")
        lines.append('')

        # Section: Graph Nodes
        lines.append('// ============================================================')
        lines.append('// SECTION 1: Graph Nodes')
        lines.append('// ============================================================')
        lines.append('')

        node_count = 0
        label_counts: Counter = Counter()
        for node in nodes:
            cypher = self._export_node(node)
            if cypher:
                lines.append(cypher)
                lines.append('')
                node_count += 1
                label_counts[node['label']] += 1

        # Section: Graph Edges
        lines.append('// ============================================================')
        lines.append('// SECTION 2: Graph Relationships')
        lines.append('// ============================================================')
        lines.append('')

        edge_count = 0
        relation_counts: Counter = Counter()
        skipped_edges: list[str] = []
        for edge in edges:
            # Validate endpoints exist
            src_exists = edge['source_node_id'] in self.node_by_id
            tgt_exists = edge['target_node_id'] in self.node_by_id
            if not src_exists or not tgt_exists:
                skipped_edges.append(
                    f"Edge {edge['edge_id']}: "
                    f"missing {'source' if not src_exists else 'target'} node"
                )
                continue
            cypher = self._export_edge(edge)
            if cypher:
                lines.append(cypher)
                lines.append('')
                edge_count += 1
                relation_counts[edge['relation_type']] += 1

        # Section: Evidence Chunk Nodes
        evidence_node_count = 0
        if self._is_evidence_layer() and safe_chunk_ids:
            lines.append('// ============================================================')
            lines.append('// SECTION 3: Evidence Chunk Nodes')
            lines.append('// ============================================================')
            lines.append('')

            for cid in sorted(safe_chunk_ids):
                chunk = self.chunk_by_id.get(cid)
                if chunk:
                    cypher = self._export_evidence_chunk_node(chunk)
                    if cypher:
                        lines.append(cypher)
                        lines.append('')
                        evidence_node_count += 1

        # Section: HAS_EVIDENCE relationships
        has_evidence_count = 0
        if self._is_evidence_layer() and safe_chunk_ids:
            lines.append('// ============================================================')
            lines.append('// SECTION 4: HAS_EVIDENCE Relationships')
            lines.append('// ============================================================')
            lines.append('')

            for node in nodes:
                for eid in node.get('evidence_chunk_ids', []):
                    if eid in safe_chunk_ids:
                        cypher = self._export_has_evidence(node['node_id'], eid)
                        lines.append(cypher)
                        lines.append('')
                        has_evidence_count += 1

        # Footer
        lines.append('// ============================================================')
        lines.append(f'// EXPORT COMPLETE')
        lines.append(f'// Graph nodes: {node_count}')
        lines.append(f'// Graph edges: {edge_count}')
        lines.append(f'// Evidence chunk nodes: {evidence_node_count}')
        lines.append(f'// HAS_EVIDENCE relationships: {has_evidence_count}')
        lines.append(f'// Skipped edges: {len(skipped_edges)}')
        lines.append(f'// Total statements: {node_count + edge_count + evidence_node_count + has_evidence_count}')
        lines.append('// ============================================================')

        # Collect stats
        self.stats = {
            'layer_filter': self.layer_filter,
            'input_nodes': len(self.linked_nodes),
            'input_edges': len(self.linked_edges),
            'input_evidence_links': len(self.evidence_links),
            'filtered_nodes': len(nodes),
            'filtered_edges': len(edges),
            'exported_graph_nodes': node_count,
            'exported_evidence_chunk_nodes': evidence_node_count,
            'exported_relationships': edge_count,
            'exported_has_evidence': has_evidence_count,
            'total_statements': node_count + edge_count + evidence_node_count + has_evidence_count,
            'skipped_edges': len(skipped_edges),
            'skipped_edge_reasons': skipped_edges,
            'label_counts': dict(label_counts.most_common()),
            'relation_counts': dict(relation_counts.most_common()),
            'referenced_chunk_ids': len(safe_chunk_ids),
            'journal_base_filtered': len(referenced_chunk_ids) - len(safe_chunk_ids),
            'api_node_count': label_counts.get('API', 0),
        }

        return '\n'.join(lines)

    def _export_node(self, node: dict[str, Any]) -> str:
        """Generate MERGE statement for a graph node."""
        label = safe_label(node['label'])
        node_id = node['node_id']

        props: dict[str, Any] = {
            'name': node.get('name', ''),
            'display_name': node.get('display_name', node.get('name', '')),
            'layer': node.get('layer', ''),
            'confidence': node.get('confidence', 0.0),
            'run_id': self.run_id,
            'dataset': self.dataset,
        }

        # Add aliases as pipe-separated string
        aliases = node.get('aliases', [])
        if aliases:
            props['aliases'] = '|'.join(str(a) for a in aliases[:10])

        # Add description
        desc = node.get('description', '')
        if desc:
            props['description'] = desc

        # Add source_ids as pipe-separated
        source_ids = node.get('source_ids', [])
        if source_ids:
            props['source_ids'] = '|'.join(str(s) for s in source_ids[:10])

        # Evidence metadata
        node_props = node.get('properties', {})
        props['evidence_count'] = node_props.get('evidence_count', 0)
        props['evidence_quality_score'] = node_props.get('evidence_quality_score', 1.0)

        # Evidence chunk IDs as pipe-separated
        evi_ids = node.get('evidence_chunk_ids', [])
        if evi_ids:
            props['evidence_chunk_ids'] = '|'.join(evi_ids[:MAX_LIST_LENGTH])

        # Build SET clause
        set_parts = []
        for k, v in sorted(props.items()):
            set_parts.append(f"`{k}`: {format_property_value(v)}")

        set_clause = ', '.join(set_parts)

        return (
            f"MERGE (n:`{label}` {{`~id`: '{escape_cypher_string(node_id)}'}}) "
            f"SET n += {{{set_clause}}};"
        )

    def _export_edge(self, edge: dict[str, Any]) -> str:
        """Generate MERGE statement for a graph edge."""
        rel_type = safe_label(edge['relation_type'])
        edge_id = edge['edge_id']
        src_id = edge['source_node_id']
        tgt_id = edge['target_node_id']

        props: dict[str, Any] = {
            'layer': edge.get('layer', ''),
            'confidence': edge.get('confidence', 0.0),
            'run_id': self.run_id,
            'dataset': self.dataset,
        }

        # Evidence metadata
        edge_props = edge.get('properties', {})
        props['evidence_count'] = edge_props.get('evidence_count', 0)
        props['evidence_quality_score'] = edge_props.get('evidence_quality_score', 1.0)

        # Evidence chunk IDs
        evi_ids = edge.get('evidence_chunk_ids', [])
        if evi_ids:
            props['evidence_chunk_ids'] = '|'.join(evi_ids[:MAX_LIST_LENGTH])

        # Source IDs
        source_ids = edge.get('source_ids', [])
        if source_ids:
            props['source_ids'] = '|'.join(str(s) for s in source_ids[:10])

        set_parts = []
        for k, v in sorted(props.items()):
            set_parts.append(f"`{k}`: {format_property_value(v)}")

        set_clause = ', '.join(set_parts)

        return (
            f"MATCH (a {{`~id`: '{escape_cypher_string(src_id)}'}}), "
            f"(b {{`~id`: '{escape_cypher_string(tgt_id)}'}}) "
            f"MERGE (a)-[r:`{rel_type}` {{`~id`: '{escape_cypher_string(edge_id)}'}}]->(b) "
            f"SET r += {{{set_clause}}};"
        )

    def _export_evidence_chunk_node(self, chunk: dict[str, Any]) -> str:
        """Generate MERGE statement for an EvidenceChunk node."""
        chunk_id = chunk.get('chunk_id', '')

        # Get text preview (no full text in Neptune)
        text = chunk.get('text', '')
        text_preview = truncate_string(text, MAX_TEXT_PREVIEW_LENGTH)

        props: dict[str, Any] = {
            'chunk_type': chunk.get('chunk_type', ''),
            'document_id': chunk.get('document_id', ''),
            'section_id': chunk.get('section_id', ''),
            'title': chunk.get('title', ''),
            'source_path': chunk.get('source_path', ''),
            'heading_path': chunk.get('heading_path', ''),
            'text_preview': text_preview,
            'run_id': self.run_id,
            'dataset': self.dataset,
        }

        # Remove empty values
        props = {k: v for k, v in props.items() if v}

        set_parts = []
        for k, v in sorted(props.items()):
            set_parts.append(f"`{k}`: {format_property_value(v)}")

        set_clause = ', '.join(set_parts)

        return (
            f"MERGE (n:`EvidenceChunk` {{`~id`: '{escape_cypher_string(chunk_id)}'}}) "
            f"SET n += {{{set_clause}}};"
        )

    def _export_has_evidence(self, node_id: str, chunk_id: str) -> str:
        """Generate HAS_EVIDENCE relationship."""
        # Deterministic edge ID
        edge_id = hashlib.md5(
            f"{node_id}|HAS_EVIDENCE|{chunk_id}".encode()
        ).hexdigest()[:16]

        return (
            f"MATCH (a {{`~id`: '{escape_cypher_string(node_id)}'}}), "
            f"(b {{`~id`: '{escape_cypher_string(chunk_id)}'}}) "
            f"MERGE (a)-[r:`HAS_EVIDENCE` {{`~id`: 'he_{edge_id}'}}]->(b) "
            f"SET r += {{`run_id`: '{self.run_id}', `dataset`: '{self.dataset}'}};"
        )

    def get_parameterized_queries(self) -> list[tuple[str, dict[str, Any]]]:
        """Generate parameterized query tuples for actual Neptune execution.

        Returns list of (cypher_template, parameters) suitable for NeptuneClient.execute_query().
        This is the safe execution path (no string interpolation).
        """
        nodes = self._filter_by_layer(self.linked_nodes)
        edges = self._filter_by_layer(self.linked_edges)
        nodes = sorted(nodes, key=lambda n: n['node_id'])
        edges = sorted(edges, key=lambda e: e['edge_id'])

        queries: list[tuple[str, dict[str, Any]]] = []

        # Node MERGE queries
        for node in nodes:
            label = safe_label(node['label'])
            props = self._build_node_props(node)
            cypher = (
                f"MERGE (n:`{label}` {{`~id`: $id}}) "
                f"SET n += $props "
                f"RETURN n.`~id` AS id"
            )
            queries.append((cypher, {'id': node['node_id'], 'props': props}))

        # Edge MERGE queries
        for edge in edges:
            src_exists = edge['source_node_id'] in self.node_by_id
            tgt_exists = edge['target_node_id'] in self.node_by_id
            if not src_exists or not tgt_exists:
                continue
            rel_type = safe_label(edge['relation_type'])
            props = self._build_edge_props(edge)
            props['relation_id'] = edge['edge_id']
            cypher = (
                f"MATCH (a {{`~id`: $from_id}}), (b {{`~id`: $to_id}}) "
                f"MERGE (a)-[r:`{rel_type}` {{relation_id: $edge_id}}]->(b) "
                f"SET r += $props "
                f"RETURN r.relation_id AS id"
            )
            queries.append((cypher, {
                'from_id': edge['source_node_id'],
                'to_id': edge['target_node_id'],
                'edge_id': edge['edge_id'],
                'props': props,
            }))

        # Evidence chunk nodes (if evidence layer)
        if self._is_evidence_layer():
            referenced_chunk_ids = set()
            for n in nodes:
                referenced_chunk_ids.update(n.get('evidence_chunk_ids', []))
            for e in edges:
                referenced_chunk_ids.update(e.get('evidence_chunk_ids', []))

            for cid in sorted(referenced_chunk_ids):
                chunk = self.chunk_by_id.get(cid)
                if not chunk:
                    continue
                sp = (chunk.get('source_path') or '').lower()
                if 'journal_base20180530' in sp:
                    continue
                props = self._build_chunk_props(chunk)
                cypher = (
                    "MERGE (n:`EvidenceChunk` {`~id`: $id}) "
                    "SET n += $props "
                    "RETURN n.`~id` AS id"
                )
                queries.append((cypher, {'id': cid, 'props': props}))

            # HAS_EVIDENCE edges
            for node in nodes:
                for eid in node.get('evidence_chunk_ids', []):
                    if eid in referenced_chunk_ids:
                        chunk = self.chunk_by_id.get(eid, {})
                        sp = (chunk.get('source_path') or '').lower()
                        if 'journal_base20180530' in sp:
                            continue
                        he_id = hashlib.md5(
                            f"{node['node_id']}|HAS_EVIDENCE|{eid}".encode()
                        ).hexdigest()[:16]
                        cypher = (
                            "MATCH (a {`~id`: $from_id}), (b {`~id`: $to_id}) "
                            "MERGE (a)-[r:`HAS_EVIDENCE` {relation_id: $edge_id}]->(b) "
                            "SET r += $props "
                            "RETURN r.relation_id AS id"
                        )
                        queries.append((cypher, {
                            'from_id': node['node_id'],
                            'to_id': eid,
                            'edge_id': f'he_{he_id}',
                            'props': {'run_id': self.run_id, 'dataset': self.dataset, 'relation_id': f'he_{he_id}'},
                        }))

        return queries

    def _build_node_props(self, node: dict[str, Any]) -> dict[str, Any]:
        """Build properties dict for a node (for parameterized queries)."""
        props: dict[str, Any] = {
            'name': node.get('name', ''),
            'display_name': node.get('display_name', node.get('name', '')),
            'layer': node.get('layer', ''),
            'confidence': node.get('confidence', 0.0),
            'run_id': self.run_id,
            'dataset': self.dataset,
        }
        aliases = node.get('aliases', [])
        if aliases:
            props['aliases'] = '|'.join(str(a) for a in aliases[:10])
        desc = node.get('description', '')
        if desc:
            props['description'] = truncate_string(desc)
        source_ids = node.get('source_ids', [])
        if source_ids:
            props['source_ids'] = '|'.join(str(s) for s in source_ids[:10])
        node_props = node.get('properties', {})
        props['evidence_count'] = node_props.get('evidence_count', 0)
        props['evidence_quality_score'] = node_props.get('evidence_quality_score', 1.0)
        evi_ids = node.get('evidence_chunk_ids', [])
        if evi_ids:
            props['evidence_chunk_ids'] = '|'.join(evi_ids[:MAX_LIST_LENGTH])
        return props

    def _build_edge_props(self, edge: dict[str, Any]) -> dict[str, Any]:
        """Build properties dict for an edge (for parameterized queries)."""
        props: dict[str, Any] = {
            'layer': edge.get('layer', ''),
            'confidence': edge.get('confidence', 0.0),
            'run_id': self.run_id,
            'dataset': self.dataset,
        }
        edge_props = edge.get('properties', {})
        props['evidence_count'] = edge_props.get('evidence_count', 0)
        props['evidence_quality_score'] = edge_props.get('evidence_quality_score', 1.0)
        evi_ids = edge.get('evidence_chunk_ids', [])
        if evi_ids:
            props['evidence_chunk_ids'] = '|'.join(evi_ids[:MAX_LIST_LENGTH])
        source_ids = edge.get('source_ids', [])
        if source_ids:
            props['source_ids'] = '|'.join(str(s) for s in source_ids[:10])
        return props

    def _build_chunk_props(self, chunk: dict[str, Any]) -> dict[str, Any]:
        """Build properties dict for an evidence chunk node."""
        text = chunk.get('text', '')
        text_preview = truncate_string(text, MAX_TEXT_PREVIEW_LENGTH)
        heading_path = chunk.get('heading_path', '')
        if isinstance(heading_path, list):
            heading_path = ' > '.join(str(h) for h in heading_path)
        props: dict[str, Any] = {
            'chunk_type': chunk.get('chunk_type', ''),
            'document_id': chunk.get('document_id', ''),
            'section_id': chunk.get('section_id', ''),
            'title': chunk.get('title', ''),
            'source_path': chunk.get('source_path', ''),
            'heading_path': heading_path,
            'text_preview': text_preview,
            'run_id': self.run_id,
            'dataset': self.dataset,
        }
        return {k: v for k, v in props.items() if v}
