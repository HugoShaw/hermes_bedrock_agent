"""Graph retriever — Neptune-based entity/relation/path retrieval.

Provides:
- NeptuneGraphRetriever: search entities, expand paths, build graph evidence
- Extracts source_chunk_id/source_chunk_ids from entity/relation properties
- Does NOT assume Chunk/Evidence nodes exist in Neptune
- Integrates QueryEntityExtractor for CJK-aware query preprocessing (Phase 10A)

Uses clients/neptune_client.py for all Neptune communication.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.retrieval.query_entity_extractor import (
    EntityIndex,
    QueryEntityExtractor,
    QueryExtractionResult,
    QueryLanguage,
)
from hermes_bedrock_agent.schemas.retrieval import GraphEvidence, RetrievalSource

logger = get_logger(__name__)


@dataclass
class GraphRetrieverConfig:
    """Configuration for graph retrieval."""

    max_hops: int = 2
    max_entities: int = 20
    max_paths: int = 10
    min_confidence: float = 0.3
    include_descriptions: bool = True
    use_query_extractor: bool = True  # Phase 10A: enable CJK-aware extraction
    entity_index_path: Optional[str] = None  # Path to entities.jsonl for index


class NeptuneGraphRetriever:
    """Neptune-based graph retriever for entity/relation/path search.

    Queries Neptune Analytics for entities and their relationships,
    then extracts source_chunk_ids from graph element properties for
    context building.

    Does NOT assume Chunk or Evidence nodes exist — only Entity nodes
    and Relation edges with source_chunk_id/source_chunk_ids properties.

    Phase 10A: Integrates QueryEntityExtractor for CJK-aware query
    preprocessing. When enabled, natural language questions are first
    analyzed to extract entity mentions before searching Neptune.
    """

    def __init__(
        self,
        neptune_client,
        config: Optional[GraphRetrieverConfig] = None,
        entity_index: Optional[EntityIndex] = None,
    ):
        """Initialize with injected Neptune client.

        Args:
            neptune_client: Instance of NeptuneClient from clients/.
            config: Retrieval configuration.
            entity_index: Pre-built EntityIndex for query extraction.
                         If None and config.entity_index_path is set,
                         loads from that path. Otherwise extraction uses
                         regex patterns only.
        """
        self._client = neptune_client
        self.config = config or GraphRetrieverConfig()

        # Phase 10A: Initialize query entity extractor
        self._entity_index = entity_index
        if self._entity_index is None and self.config.entity_index_path:
            self._entity_index = EntityIndex()
            count = self._entity_index.load_from_jsonl(self.config.entity_index_path)
            logger.info(f"Loaded entity index: {count} entities from {self.config.entity_index_path}")

        self._extractor = QueryEntityExtractor(self._entity_index) if self.config.use_query_extractor else None

    def extract_query_terms(self, question: str) -> QueryExtractionResult:
        """Extract entity search terms from a natural language question.

        Phase 10A: CJK-aware query preprocessing.

        Args:
            question: User's natural language question.

        Returns:
            QueryExtractionResult with extracted graph search terms.
        """
        if self._extractor:
            return self._extractor.extract(question)
        # Fallback: return question as-is
        return QueryExtractionResult(
            original_question=question,
            detected_language=QueryLanguage.AUTO,
            graph_search_terms=[question],
        )

    def search_entities(
        self,
        query_terms: list[str],
        *,
        entity_types: Optional[list[str]] = None,
        top_k: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Search for entities matching query terms.

        Uses case-insensitive matching on name/canonical_name/aliases.

        Args:
            query_terms: Keywords to search for in entity properties.
            entity_types: Optional filter for specific entity types.
            top_k: Maximum entities to return.

        Returns:
            List of entity property dicts from Neptune.
        """
        k = top_k or self.config.max_entities

        # Build CASE-INSENSITIVE search query
        conditions = []
        params: dict[str, Any] = {"limit": k}

        for i, term in enumerate(query_terms[:5]):  # Max 5 terms
            param_name = f"term_{i}"
            params[param_name] = term.lower()
            conditions.append(
                f"(toLower(n.name) CONTAINS ${param_name} "
                f"OR toLower(n.canonical_name) CONTAINS ${param_name} "
                f"OR toLower(n.aliases) CONTAINS ${param_name})"
            )

        where_clause = " OR ".join(conditions) if conditions else "true"

        if entity_types:
            # Filter by label (entity_type)
            label_filter = " OR ".join(f"n:{et}" for et in entity_types)
            where_clause = f"({where_clause}) AND ({label_filter})"

        query = (
            f"MATCH (n) WHERE {where_clause} "
            f"RETURN n LIMIT $limit"
        )

        try:
            results = self._client.execute_query(query, parameters=params)
            return self._extract_nodes(results)
        except Exception as e:
            logger.warning(f"Entity search failed: {e}")
            return []

    def expand_paths(
        self,
        entity_ids: list[str],
        *,
        max_hops: Optional[int] = None,
        relation_types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Expand paths from given entities through their relations.

        Traverses 1-N hops from seed entities to discover connected subgraph.

        Args:
            entity_ids: Starting entity IDs to expand from.
            max_hops: Maximum traversal depth (default: config.max_hops).
            relation_types: Optional filter for specific relation types.

        Returns:
            List of path dicts with nodes, edges, and properties.
        """
        hops = max_hops or self.config.max_hops
        all_paths: list[dict[str, Any]] = []

        for eid in entity_ids[:5]:  # Max 5 seed entities
            query = (
                f"MATCH path = (a {{entity_id: $eid}})-[r*1..{hops}]-(b) "
                f"WHERE a.confidence >= $min_conf "
                f"RETURN path LIMIT $limit"
            )
            params: dict[str, Any] = {
                "eid": eid,
                "min_conf": self.config.min_confidence,
                "limit": self.config.max_paths,
            }

            try:
                results = self._client.execute_query(query, parameters=params)
                paths = self._extract_paths(results, seed_entity_id=eid)
                all_paths.extend(paths)
            except Exception as e:
                logger.warning(f"Path expansion failed for {eid}: {e}")

        return all_paths

    def retrieve_graph_context(
        self,
        query_terms: list[str],
        *,
        entity_types: Optional[list[str]] = None,
        max_hops: Optional[int] = None,
    ) -> list[GraphEvidence]:
        """Full graph retrieval pipeline: search → expand → build evidence.

        1. Search for entities matching query terms
        2. Expand paths from found entities
        3. Extract source_chunk_ids from entity/relation properties
        4. Build GraphEvidence objects

        Args:
            query_terms: Keywords from user query.
            entity_types: Optional entity type filter.
            max_hops: Optional max traversal depth.

        Returns:
            List of GraphEvidence objects with source_chunk_ids.
        """
        # Step 1: Find seed entities
        entities = self.search_entities(
            query_terms, entity_types=entity_types
        )

        if not entities:
            return []

        # Step 2: Expand paths from found entities
        entity_ids = [e.get("entity_id", "") for e in entities if e.get("entity_id")]
        paths = self.expand_paths(entity_ids, max_hops=max_hops)

        # Step 3: Build graph evidence
        evidence_list: list[GraphEvidence] = []

        # Evidence from entities themselves
        for rank, entity in enumerate(entities):
            ev = self._entity_to_evidence(entity, rank=rank)
            if ev:
                evidence_list.append(ev)

        # Evidence from paths
        for rank, path in enumerate(paths):
            ev = self._path_to_evidence(path, rank=len(entities) + rank)
            if ev:
                evidence_list.append(ev)

        return evidence_list

    def retrieve_from_question(
        self,
        question: str,
        *,
        entity_types: Optional[list[str]] = None,
        max_hops: Optional[int] = None,
    ) -> tuple[list[GraphEvidence], QueryExtractionResult]:
        """Full pipeline: question → extract terms → retrieve graph context.

        Phase 10A enhancement: Uses QueryEntityExtractor to preprocess the
        natural language question before searching Neptune.

        Falls back to direct query_terms search if extraction yields nothing.

        Args:
            question: User's natural language question.
            entity_types: Optional entity type filter.
            max_hops: Optional max traversal depth.

        Returns:
            Tuple of (GraphEvidence list, QueryExtractionResult).
        """
        # Step 1: Extract entity mentions from question
        extraction = self.extract_query_terms(question)
        graph_terms = extraction.graph_search_terms

        logger.info(
            f"Query extraction: lang={extraction.detected_language.value}, "
            f"mentions={len(extraction.entity_mentions)}, "
            f"terms={graph_terms[:5]}"
        )

        # Step 2: Retrieve with extracted terms
        evidence = self.retrieve_graph_context(
            graph_terms, entity_types=entity_types, max_hops=max_hops
        )

        # Step 3: Fallback — if no results, try normalized terms
        if not evidence and extraction.normalized_terms:
            logger.info("No results with graph_search_terms, trying normalized_terms")
            evidence = self.retrieve_graph_context(
                extraction.normalized_terms[:5],
                entity_types=entity_types,
                max_hops=max_hops,
            )

        return evidence, extraction

    def _entity_to_evidence(
        self, entity: dict[str, Any], rank: int = 0
    ) -> Optional[GraphEvidence]:
        """Convert an entity dict to GraphEvidence."""
        entity_id = entity.get("entity_id", "")
        if not entity_id:
            return None

        # Extract source_chunk_ids from entity property
        source_chunk_ids = self._parse_chunk_ids(
            entity.get("source_chunk_ids", "")
        )

        # Build content description
        name = entity.get("name", entity.get("canonical_name", ""))
        entity_type = entity.get("entity_type", "unknown")
        description = entity.get("description", "")
        content = f"[{entity_type}] {name}"
        if description:
            content += f": {description}"

        evidence_id = hashlib.sha256(
            f"ge_{entity_id}".encode()
        ).hexdigest()[:16]

        return GraphEvidence(
            evidence_id=f"ge_{evidence_id}",
            entity_id=entity_id,
            content=content,
            entities_involved=[entity_id],
            source_chunk_ids=source_chunk_ids,
            source=RetrievalSource.NEPTUNE_GRAPH,
            score=entity.get("confidence", 0.5),
            rank=rank,
            hop_count=0,
        )

    def _path_to_evidence(
        self, path: dict[str, Any], rank: int = 0
    ) -> Optional[GraphEvidence]:
        """Convert a path dict to GraphEvidence."""
        nodes = path.get("nodes", [])
        edges = path.get("edges", [])

        if not nodes:
            return None

        # Collect entity IDs and source_chunk_ids from all path elements
        entity_ids: list[str] = []
        relation_ids: list[str] = []
        source_chunk_ids: list[str] = []

        for node in nodes:
            eid = node.get("entity_id", "")
            if eid:
                entity_ids.append(eid)
            source_chunk_ids.extend(
                self._parse_chunk_ids(node.get("source_chunk_ids", ""))
            )

        for edge in edges:
            rid = edge.get("relation_id", "")
            if rid:
                relation_ids.append(rid)
            # Extract source_chunk_id from relation property
            src_cid = edge.get("source_chunk_id", "")
            if src_cid:
                source_chunk_ids.append(src_cid)
            source_chunk_ids.extend(
                self._parse_chunk_ids(edge.get("source_chunk_ids", ""))
            )

        # Deduplicate
        source_chunk_ids = list(dict.fromkeys(source_chunk_ids))

        # Build path description
        path_desc = path.get("description", "")
        if not path_desc:
            path_desc = self._build_path_description(nodes, edges)

        content = f"Path: {path_desc}" if path_desc else "Graph path"

        evidence_id = hashlib.sha256(
            f"gp_{'_'.join(entity_ids[:3])}".encode()
        ).hexdigest()[:16]

        return GraphEvidence(
            evidence_id=f"gp_{evidence_id}",
            content=content,
            path_description=path_desc,
            entities_involved=entity_ids,
            relations_involved=relation_ids,
            source_chunk_ids=source_chunk_ids,
            source=RetrievalSource.NEPTUNE_GRAPH,
            score=path.get("score", 0.3),
            rank=rank,
            hop_count=len(edges),
        )

    def _build_path_description(
        self, nodes: list[dict], edges: list[dict]
    ) -> str:
        """Build human-readable path: 'NodeA --rel--> NodeB --rel--> NodeC'."""
        if not nodes:
            return ""

        parts = []
        for i, node in enumerate(nodes):
            name = node.get("name", node.get("canonical_name", "?"))
            parts.append(name)
            if i < len(edges):
                rel_type = edges[i].get("relation_type", "related_to")
                parts.append(f"--{rel_type}-->")

        return " ".join(parts)

    def _parse_chunk_ids(self, value: Any) -> list[str]:
        """Parse source_chunk_ids from property value.

        Handles both list format and comma-separated string format
        (Neptune stores lists as comma strings via serialize_property_value).
        """
        if isinstance(value, list):
            return [str(v).strip() for v in value if v]
        if isinstance(value, str) and value.strip():
            return [cid.strip() for cid in value.split(",") if cid.strip()]
        return []

    def _extract_nodes(self, results: Any) -> list[dict[str, Any]]:
        """Extract node property dicts from Neptune query results.

        Handles various Neptune response formats including:
        - {'results': [{'n': {~id, ~properties: {...}}}]}  (Neptune Analytics)
        - [{'n': {...}}]  (flat list)
        - [{'entity_id': ...}]  (direct properties)
        """
        if not results:
            return []

        # Unwrap {'results': [...]} envelope from Neptune Analytics
        if isinstance(results, dict) and "results" in results:
            results = results["results"]

        # If results is already a list of dicts
        if isinstance(results, list):
            nodes = []
            for item in results:
                if isinstance(item, dict):
                    # Direct node properties
                    if "entity_id" in item:
                        nodes.append(item)
                    # Wrapped in 'n' key (Neptune Analytics format)
                    elif "n" in item and isinstance(item["n"], dict):
                        node_data = item["n"]
                        # Neptune Analytics wraps properties in ~properties
                        if "~properties" in node_data:
                            props = node_data["~properties"]
                            # Include labels and id from outer
                            props["_neptune_id"] = node_data.get("~id", "")
                            props["_labels"] = node_data.get("~labels", [])
                            nodes.append(props)
                        else:
                            nodes.append(node_data)
            return nodes

        return []

    def _extract_paths(
        self, results: Any, seed_entity_id: str = ""
    ) -> list[dict[str, Any]]:
        """Extract path structures from Neptune query results.

        Neptune Analytics returns paths as alternating node/edge lists:
        {'results': [{'path': [node, edge, node, ...]}]}
        """
        if not results:
            return []

        # Unwrap {'results': [...]} envelope from Neptune Analytics
        if isinstance(results, dict) and "results" in results:
            results = results["results"]

        if isinstance(results, list):
            paths = []
            for item in results:
                if isinstance(item, dict):
                    path_data = item.get("path")
                    if path_data is None:
                        # Direct structure with nodes/edges keys
                        if "nodes" in item and "edges" in item:
                            paths.append(item)
                        continue

                    # Neptune Analytics: path is a list of alternating nodes/edges
                    if isinstance(path_data, list):
                        nodes = []
                        edges = []
                        for elem in path_data:
                            if isinstance(elem, dict):
                                entity_type = elem.get("~entityType", "")
                                props = elem.get("~properties", elem)
                                if entity_type == "node":
                                    nodes.append(props)
                                elif entity_type == "relationship":
                                    edges.append(props)
                                elif "entity_id" in props:
                                    nodes.append(props)
                                elif "relation_id" in props:
                                    edges.append(props)
                        if nodes:
                            paths.append({"nodes": nodes, "edges": edges})
                    # Dict with nodes/edges keys
                    elif isinstance(path_data, dict):
                        if "nodes" in path_data and "edges" in path_data:
                            paths.append(path_data)
            return paths

        return []
