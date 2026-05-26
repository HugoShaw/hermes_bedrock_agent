"""
V2 Business Graph Retriever — JSONL-backed keyword retrieval over business graph.

Retrieves business semantic graph nodes and their neighborhoods using keyword matching.
Supports business process discovery, business rule lookup, and graph path expansion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.retrieval.vector_evidence_retriever import tokenize, token_overlap_score
from hermes_bedrock_agent.v2.schemas.retrieval_schema import RetrievalResult


# Business layer labels
BUSINESS_LABELS = {
    'Project', 'BusinessDomain', 'BusinessProcess', 'BusinessStep',
    'BusinessRule', 'BusinessTerm', 'Function', 'Screen', 'Role', 'Organization',
}


class BusinessGraphRetriever:
    """JSONL-backed business graph retriever with keyword scoring and neighborhood expansion."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self._nodes: list[dict[str, Any]] | None = None
        self._edges: list[dict[str, Any]] | None = None
        self._node_index: dict[str, dict[str, Any]] | None = None
        self._outgoing: dict[str, list[dict[str, Any]]] | None = None
        self._incoming: dict[str, list[dict[str, Any]]] | None = None

    def _load(self) -> None:
        """Lazy-load business graph data."""
        if self._nodes is not None:
            return

        # Load nodes (business layer only)
        self._nodes = []
        self._node_index = {}
        nodes_path = self.output_dir / 'graph_nodes_linked.jsonl'
        with open(nodes_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                node = json.loads(line)
                if node.get('layer') == 'business':
                    self._nodes.append(node)
                    self._node_index[node['node_id']] = node

        # Load edges (business layer only)
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
                if edge.get('layer') == 'business':
                    self._edges.append(edge)
                    src = edge['source_node_id']
                    tgt = edge['target_node_id']
                    self._outgoing.setdefault(src, []).append(edge)
                    self._incoming.setdefault(tgt, []).append(edge)

    def _score_node(self, node: dict[str, Any], query_tokens: list[str], query_raw: str) -> float:
        """Score a node's relevance to a query."""
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

        # Alias exact match
        for alias in aliases:
            if str(alias).lower() in query_lower:
                score += 2.5
                break

        return score

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        depth: int = 1,
    ) -> RetrievalResult:
        """Retrieve matching business graph nodes with neighborhood expansion."""
        self._load()
        assert self._nodes is not None

        query_tokens = tokenize(query)
        if not query_tokens:
            return RetrievalResult(
                source='business_graph',
                items=[],
                score=0.0,
                metadata={'query': query, 'reason': 'empty query tokens'},
            )

        # Score all business nodes
        scored: list[tuple[float, dict[str, Any]]] = []
        for node in self._nodes:
            s = self._score_node(node, query_tokens, query)
            if s > 0:
                scored.append((s, node))

        scored.sort(key=lambda x: -x[0])
        top_nodes = scored[:top_k]

        # Expand neighborhoods
        items = []
        seen_node_ids: set[str] = set()
        all_evidence_ids: set[str] = set()

        for score, node in top_nodes:
            nid = node['node_id']
            seen_node_ids.add(nid)

            # Collect evidence
            for eid in node.get('evidence_chunk_ids', []):
                all_evidence_ids.add(eid)

            item = {
                'type': 'node',
                'node_id': nid,
                'label': node['label'],
                'name': node.get('name', ''),
                'display_name': node.get('display_name', ''),
                'aliases': node.get('aliases', []),
                'score': round(score, 4),
                'evidence_chunk_ids': node.get('evidence_chunk_ids', []),
            }
            items.append(item)

        # Get neighborhood edges
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
                        'score': 0.5,
                        'evidence_chunk_ids': neighbor_node.get('evidence_chunk_ids', []),
                    })
                # Add edge as item too
                for eid in edge.get('evidence_chunk_ids', []):
                    all_evidence_ids.add(eid)
                items.append({
                    'type': 'edge',
                    'edge_id': edge['edge_id'],
                    'relation_type': edge['relation_type'],
                    'source_node_id': edge['source_node_id'],
                    'target_node_id': edge['target_node_id'],
                    'evidence_chunk_ids': edge.get('evidence_chunk_ids', []),
                })

        items.extend(neighbor_items)

        avg_score = sum(s for s, _ in top_nodes) / max(len(top_nodes), 1)

        return RetrievalResult(
            source='business_graph',
            items=items,
            score=round(avg_score, 4),
            metadata={
                'query': query,
                'top_k': top_k,
                'depth': depth,
                'total_business_nodes': len(self._nodes),
                'matched_nodes': len(top_nodes),
                'neighbor_nodes': len(neighbor_items),
                'evidence_chunk_ids': sorted(all_evidence_ids)[:50],
                'total_evidence_ids': len(all_evidence_ids),
            },
        )

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
                # Outgoing edges
                for edge in self._outgoing.get(nid, []):
                    tgt = edge['target_node_id']
                    if tgt not in visited and tgt in self._node_index:
                        visited.add(tgt)
                        next_frontier.add(tgt)
                        results.append((edge, self._node_index[tgt]))
                # Incoming edges
                for edge in self._incoming.get(nid, []):
                    src = edge['source_node_id']
                    if src not in visited and src in self._node_index:
                        visited.add(src)
                        next_frontier.add(src)
                        results.append((edge, self._node_index[src]))
            frontier = next_frontier

        return results

    def get_node_neighborhood(self, node_id: str, depth: int = 1) -> RetrievalResult:
        """Get full neighborhood of a specific node."""
        self._load()
        assert self._node_index is not None

        node = self._node_index.get(node_id)
        if not node:
            return RetrievalResult(
                source='business_graph',
                items=[],
                score=0.0,
                metadata={'node_id': node_id, 'reason': 'node not found'},
            )

        neighbors = self._get_neighbors(node_id, depth=depth)
        items = [{
            'type': 'center_node',
            'node_id': node_id,
            'label': node['label'],
            'name': node.get('name', ''),
            'display_name': node.get('display_name', ''),
        }]

        for edge, neighbor_node in neighbors:
            items.append({
                'type': 'neighbor',
                'node_id': neighbor_node['node_id'],
                'label': neighbor_node['label'],
                'name': neighbor_node.get('name', ''),
                'relation': edge['relation_type'],
            })

        return RetrievalResult(
            source='business_graph',
            items=items,
            score=1.0,
            metadata={'node_id': node_id, 'depth': depth, 'neighbors': len(neighbors)},
        )

    def find_business_processes(self, query: str) -> RetrievalResult:
        """Find business process nodes matching query."""
        self._load()
        assert self._nodes is not None

        process_nodes = [n for n in self._nodes if n['label'] == 'BusinessProcess']
        query_tokens = tokenize(query)

        scored = [(self._score_node(n, query_tokens, query), n) for n in process_nodes]
        scored.sort(key=lambda x: -x[0])
        scored = [(s, n) for s, n in scored if s > 0]

        items = [{
            'node_id': n['node_id'],
            'label': n['label'],
            'name': n.get('name', ''),
            'display_name': n.get('display_name', ''),
            'score': round(s, 4),
        } for s, n in scored[:10]]

        return RetrievalResult(
            source='business_graph',
            items=items,
            score=items[0]['score'] if items else 0.0,
            metadata={'filter': 'BusinessProcess', 'total': len(process_nodes), 'matched': len(items)},
        )

    def find_business_rules(self, query: str) -> RetrievalResult:
        """Find business rule nodes matching query."""
        self._load()
        assert self._nodes is not None

        rule_nodes = [n for n in self._nodes if n['label'] == 'BusinessRule']
        query_tokens = tokenize(query)

        scored = [(self._score_node(n, query_tokens, query), n) for n in rule_nodes]
        scored.sort(key=lambda x: -x[0])
        scored = [(s, n) for s, n in scored if s > 0]

        items = [{
            'node_id': n['node_id'],
            'label': n['label'],
            'name': n.get('name', ''),
            'display_name': n.get('display_name', ''),
            'score': round(s, 4),
        } for s, n in scored[:10]]

        return RetrievalResult(
            source='business_graph',
            items=items,
            score=items[0]['score'] if items else 0.0,
            metadata={'filter': 'BusinessRule', 'total': len(rule_nodes), 'matched': len(items)},
        )

    def find_business_terms(self, query: str) -> RetrievalResult:
        """Find business term nodes matching query."""
        self._load()
        assert self._nodes is not None

        term_nodes = [n for n in self._nodes if n['label'] == 'BusinessTerm']
        query_tokens = tokenize(query)

        scored = [(self._score_node(n, query_tokens, query), n) for n in term_nodes]
        scored.sort(key=lambda x: -x[0])
        scored = [(s, n) for s, n in scored if s > 0]

        items = [{
            'node_id': n['node_id'],
            'label': n['label'],
            'name': n.get('name', ''),
            'display_name': n.get('display_name', ''),
            'score': round(s, 4),
        } for s, n in scored[:10]]

        return RetrievalResult(
            source='business_graph',
            items=items,
            score=items[0]['score'] if items else 0.0,
            metadata={'filter': 'BusinessTerm', 'total': len(term_nodes), 'matched': len(items)},
        )
