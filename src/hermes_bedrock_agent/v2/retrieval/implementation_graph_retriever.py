"""
V2 Implementation Graph Retriever — JSONL-backed keyword retrieval over implementation graph.

Retrieves implementation graph nodes (Table, Column, SQL, File, Class, Method, Service, etc.)
and their neighborhoods using keyword matching.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.retrieval.vector_evidence_retriever import tokenize, token_overlap_score
from hermes_bedrock_agent.v2.schemas.retrieval_schema import RetrievalResult


# Implementation layer labels
IMPLEMENTATION_LABELS = {
    'System', 'Module', 'API', 'Service', 'Class', 'Method',
    'Table', 'Column', 'SQL', 'Job', 'File', 'ExternalSystem',
    'Config', 'Message', 'ErrorCode',
}


class ImplementationGraphRetriever:
    """JSONL-backed implementation graph retriever with keyword scoring."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self._nodes: list[dict[str, Any]] | None = None
        self._edges: list[dict[str, Any]] | None = None
        self._node_index: dict[str, dict[str, Any]] | None = None
        self._outgoing: dict[str, list[dict[str, Any]]] | None = None
        self._incoming: dict[str, list[dict[str, Any]]] | None = None
        self._label_index: dict[str, list[dict[str, Any]]] | None = None

    def _load(self) -> None:
        """Lazy-load implementation graph data."""
        if self._nodes is not None:
            return

        self._nodes = []
        self._node_index = {}
        self._label_index = {}
        nodes_path = self.output_dir / 'graph_nodes_linked.jsonl'
        with open(nodes_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                node = json.loads(line)
                if node.get('layer') == 'implementation':
                    self._nodes.append(node)
                    self._node_index[node['node_id']] = node
                    label = node.get('label', '')
                    self._label_index.setdefault(label, []).append(node)

        self._edges = []
        self._outgoing = {}
        self._incoming = {}
        edges_path = self.output_dir / 'graph_edges_linked.jsonl'
        with open(edges_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                edge = json.loads(line)
                if edge.get('layer') == 'implementation':
                    self._edges.append(edge)
                    src = edge['source_node_id']
                    tgt = edge['target_node_id']
                    self._outgoing.setdefault(src, []).append(edge)
                    self._incoming.setdefault(tgt, []).append(edge)

    def _score_node(self, node: dict[str, Any], query_tokens: list[str], query_raw: str) -> float:
        """Score a node's relevance."""
        score = 0.0

        # Name match
        name = node.get('name', '')
        name_score = token_overlap_score(query_tokens, name)
        score += name_score * 3.0

        # Display name match
        display_name = node.get('display_name', '')
        dn_score = token_overlap_score(query_tokens, display_name)
        score += dn_score * 2.5

        # Aliases match
        aliases = node.get('aliases', [])
        if aliases:
            alias_text = ' '.join(str(a) for a in aliases)
            alias_score = token_overlap_score(query_tokens, alias_text)
            score += alias_score * 2.0

        # Label match (e.g., query mentions "table", label is "Table")
        label = node.get('label', '')
        label_score = token_overlap_score(query_tokens, label)
        score += label_score * 1.5

        # Description match
        desc = node.get('description', '')
        if desc:
            desc_score = token_overlap_score(query_tokens, desc)
            score += desc_score * 1.5

        # Properties match
        props = node.get('properties', {})
        if props:
            props_text = json.dumps(props, ensure_ascii=False)
            props_score = token_overlap_score(query_tokens, props_text)
            score += props_score * 1.0

        # Exact substring in name/display_name
        query_lower = query_raw.lower()
        if name.lower() in query_lower or query_lower in name.lower():
            score += 3.0
        if display_name.lower() in query_lower or query_lower in display_name.lower():
            score += 2.0

        for alias in aliases:
            if str(alias).lower() in query_lower:
                score += 2.5
                break

        return score

    def _get_neighbors(
        self, node_id: str, depth: int = 1
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Get neighboring nodes up to given depth."""
        assert self._outgoing is not None and self._incoming is not None and self._node_index is not None

        results: list[tuple[dict[str, Any], dict[str, Any]]] = []
        visited: set[str] = {node_id}
        frontier: set[str] = {node_id}

        for _ in range(depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                for edge in self._outgoing.get(nid, []):
                    tgt = edge['target_node_id']
                    if tgt not in visited and tgt in self._node_index:
                        visited.add(tgt)
                        next_frontier.add(tgt)
                        results.append((edge, self._node_index[tgt]))
                for edge in self._incoming.get(nid, []):
                    src = edge['source_node_id']
                    if src not in visited and src in self._node_index:
                        visited.add(src)
                        next_frontier.add(src)
                        results.append((edge, self._node_index[src]))
            frontier = next_frontier

        return results

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        depth: int = 1,
        labels: list[str] | None = None,
    ) -> RetrievalResult:
        """Retrieve matching implementation graph nodes with optional label filter."""
        self._load()
        assert self._nodes is not None

        query_tokens = tokenize(query)
        if not query_tokens:
            return RetrievalResult(
                source='implementation_graph',
                items=[],
                score=0.0,
                metadata={'query': query, 'reason': 'empty query tokens'},
            )

        # Filter by labels if specified
        candidates = self._nodes
        if labels:
            candidates = [n for n in candidates if n.get('label') in labels]

        # Score
        scored: list[tuple[float, dict[str, Any]]] = []
        for node in candidates:
            s = self._score_node(node, query_tokens, query)
            if s > 0:
                scored.append((s, node))

        scored.sort(key=lambda x: -x[0])
        top_nodes = scored[:top_k]

        # Build results with neighborhoods
        items = []
        seen_node_ids: set[str] = set()
        all_evidence_ids: set[str] = set()

        for score, node in top_nodes:
            nid = node['node_id']
            seen_node_ids.add(nid)
            for eid in node.get('evidence_chunk_ids', []):
                all_evidence_ids.add(eid)

            items.append({
                'type': 'node',
                'node_id': nid,
                'label': node['label'],
                'name': node.get('name', ''),
                'display_name': node.get('display_name', ''),
                'aliases': node.get('aliases', []),
                'score': round(score, 4),
                'evidence_chunk_ids': node.get('evidence_chunk_ids', []),
            })

        # Expand neighborhoods
        neighbor_items = []
        for _, node in top_nodes:
            nid = node['node_id']
            neighbors = self._get_neighbors(nid, depth=depth)
            for edge, neighbor_node in neighbors:
                if neighbor_node['node_id'] not in seen_node_ids:
                    seen_node_ids.add(neighbor_node['node_id'])
                    for eid in neighbor_node.get('evidence_chunk_ids', []):
                        all_evidence_ids.add(eid)
                    neighbor_items.append({
                        'type': 'neighbor',
                        'node_id': neighbor_node['node_id'],
                        'label': neighbor_node['label'],
                        'name': neighbor_node.get('name', ''),
                        'display_name': neighbor_node.get('display_name', ''),
                        'relation': edge['relation_type'],
                        'from_node': edge['source_node_id'],
                        'score': 0.3,
                    })
                items.append({
                    'type': 'edge',
                    'edge_id': edge['edge_id'],
                    'relation_type': edge['relation_type'],
                    'source_node_id': edge['source_node_id'],
                    'target_node_id': edge['target_node_id'],
                    'evidence_chunk_ids': edge.get('evidence_chunk_ids', []),
                })
                for eid in edge.get('evidence_chunk_ids', []):
                    all_evidence_ids.add(eid)

        items.extend(neighbor_items)

        avg_score = sum(s for s, _ in top_nodes) / max(len(top_nodes), 1)

        return RetrievalResult(
            source='implementation_graph',
            items=items,
            score=round(avg_score, 4),
            metadata={
                'query': query,
                'top_k': top_k,
                'depth': depth,
                'labels_filter': labels,
                'total_impl_nodes': len(self._nodes),
                'total_candidates': len(candidates),
                'matched_nodes': len(top_nodes),
                'neighbor_nodes': len(neighbor_items),
                'evidence_chunk_ids': sorted(all_evidence_ids)[:50],
                'total_evidence_ids': len(all_evidence_ids),
            },
        )

    def find_tables(self, query: str) -> RetrievalResult:
        """Find Table nodes matching query."""
        return self.retrieve(query, top_k=10, depth=1, labels=['Table'])

    def find_columns(self, query: str) -> RetrievalResult:
        """Find Column nodes matching query."""
        return self.retrieve(query, top_k=10, depth=0, labels=['Column'])

    def find_sql(self, query: str) -> RetrievalResult:
        """Find SQL nodes matching query."""
        return self.retrieve(query, top_k=10, depth=1, labels=['SQL'])

    def find_files_classes_methods(self, query: str) -> RetrievalResult:
        """Find File, Class, and Method nodes matching query."""
        return self.retrieve(query, top_k=15, depth=1, labels=['File', 'Class', 'Method'])
