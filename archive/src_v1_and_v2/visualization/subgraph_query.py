"""Subgraph query service — bounded Neptune subgraph retrieval for visualization.

Provides:
- SubgraphQueryService: query subgraphs with center_entity, depth, max_nodes
- Does NOT query full graph — always bounded by center + depth + limit
- Uses clients/neptune_client.py via dependency injection
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.visualization import (
    SubgraphResult,
    VisualizationEdge,
    VisualizationNode,
)

logger = get_logger(__name__)

# Node type → color mapping for visualization
_NODE_COLORS: dict[str, str] = {
    "system": "#4A90D9",
    "module": "#67B7DC",
    "business_process": "#6794DC",
    "process_step": "#8B67DC",
    "data_source": "#DC6788",
    "table": "#DC8B67",
    "api": "#67DC8B",
    "service": "#DCB767",
    "unknown": "#999999",
}

# Edge type → style mapping
_EDGE_STYLES: dict[str, str] = {
    "belongs_to": "solid",
    "calls": "solid",
    "reads_from": "dashed",
    "writes_to": "dashed",
    "depends_on": "dotted",
    "implemented_by": "solid",
}


@dataclass
class SubgraphQueryConfig:
    """Configuration for subgraph queries."""

    default_depth: int = 2
    default_max_nodes: int = 50
    max_allowed_depth: int = 5
    max_allowed_nodes: int = 200


class SubgraphQueryService:
    """Bounded subgraph query service for visualization.

    Always requires center_entity or explicit bounds. Never queries full graph.
    Uses parameterized queries via neptune_client.
    """

    def __init__(
        self,
        neptune_client=None,
        config: Optional[SubgraphQueryConfig] = None,
        mock_mode: bool = False,
    ):
        """Initialize subgraph query service.

        Args:
            neptune_client: Instance of NeptuneClient from clients/.
            config: Query configuration.
            mock_mode: If True, return mock data without Neptune calls.
        """
        self._client = neptune_client
        self.config = config or SubgraphQueryConfig()
        self._mock_mode = mock_mode

    def query_subgraph(
        self,
        center_entity: str,
        *,
        depth: int = 2,
        node_types: Optional[list[str]] = None,
        edge_types: Optional[list[str]] = None,
        max_nodes: Optional[int] = None,
        exclude_node_types: Optional[list[str]] = None,
    ) -> SubgraphResult:
        """Query a bounded subgraph centered on an entity.

        Args:
            center_entity: Entity ID or name to center the subgraph on.
            depth: Maximum traversal depth (hops). Capped by config.
            node_types: Optional filter — only include these node types.
            edge_types: Optional filter — only include these edge types.
            max_nodes: Maximum nodes to return. Capped by config.
            exclude_node_types: Node types to exclude from results.

        Returns:
            SubgraphResult with nodes, edges, and query metadata.
        """
        # Apply bounds
        effective_depth = min(depth, self.config.max_allowed_depth)
        effective_max = min(
            max_nodes or self.config.default_max_nodes,
            self.config.max_allowed_nodes,
        )

        if self._mock_mode:
            return self._mock_subgraph(center_entity, effective_depth, effective_max)

        start_time = time.time()

        # Build parameterized query
        query, params = self._build_subgraph_query(
            center_entity,
            effective_depth,
            effective_max,
            node_types=node_types,
            edge_types=edge_types,
            exclude_node_types=exclude_node_types,
        )

        # Execute query
        try:
            raw_results = self._client.execute_query(query, parameters=params)
        except Exception as e:
            logger.error(f"Subgraph query failed: {e}")
            return SubgraphResult(
                query=center_entity,
                center_entity_id=center_entity,
                max_hops=effective_depth,
            )

        elapsed_ms = int((time.time() - start_time) * 1000)

        # Parse results into visualization nodes/edges
        nodes, edges = self._parse_results(raw_results, exclude_node_types)

        return SubgraphResult(
            query=center_entity,
            center_entity_id=center_entity,
            max_hops=effective_depth,
            nodes=nodes[:effective_max],
            edges=edges,
            node_count=len(nodes[:effective_max]),
            edge_count=len(edges),
            cypher_query=query,
            query_time_ms=elapsed_ms,
        )

    def _build_subgraph_query(
        self,
        center_entity: str,
        depth: int,
        max_nodes: int,
        *,
        node_types: Optional[list[str]] = None,
        edge_types: Optional[list[str]] = None,
        exclude_node_types: Optional[list[str]] = None,
    ) -> tuple[str, dict]:
        """Build parameterized Cypher query for subgraph traversal."""
        # Build path pattern based on depth
        query_parts = [
            "MATCH path = (center {entity_id: $center_id})-[*1..",
            str(depth),
            "]-(neighbor)",
            "\nWHERE center <> neighbor",
        ]

        params: dict = {
            "center_id": center_entity,
            "limit": max_nodes,
        }

        # Optional node type filter
        if node_types:
            type_conditions = " OR ".join(
                f"neighbor.entity_type = $ntype_{i}" for i in range(len(node_types))
            )
            query_parts.append(f"\n  AND ({type_conditions})")
            for i, nt in enumerate(node_types):
                params[f"ntype_{i}"] = nt

        # Optional exclude node types
        if exclude_node_types:
            for i, ent in enumerate(exclude_node_types):
                query_parts.append(f"\n  AND neighbor.entity_type <> $excl_{i}")
                params[f"excl_{i}"] = ent

        query_parts.append(
            "\nWITH center, neighbor, path"
            "\nLIMIT $limit"
            "\nRETURN center, neighbor,"
            "\n  relationships(path) AS rels,"
            "\n  [n IN nodes(path) | properties(n)] AS node_props"
        )

        query = "".join(query_parts)
        return query, params

    def _parse_results(
        self,
        raw_results: list[dict],
        exclude_node_types: Optional[list[str]] = None,
    ) -> tuple[list[VisualizationNode], list[VisualizationEdge]]:
        """Parse raw Neptune results into visualization nodes and edges."""
        nodes_map: dict[str, VisualizationNode] = {}
        edges_map: dict[str, VisualizationEdge] = {}
        exclude_set = set(exclude_node_types or [])

        for row in raw_results:
            # Parse node properties from path
            node_props_list = row.get("node_props", [])
            for props in node_props_list:
                if not isinstance(props, dict):
                    continue
                nid = props.get("entity_id", "")
                if not nid or nid in nodes_map:
                    continue
                etype = props.get("entity_type", "unknown")
                if etype in exclude_set:
                    continue

                nodes_map[nid] = VisualizationNode(
                    node_id=nid,
                    label=props.get("name", props.get("canonical_name", nid)),
                    entity_type=etype,
                    description=props.get("description", ""),
                    color=_NODE_COLORS.get(etype, _NODE_COLORS["unknown"]),
                    properties={
                        k: str(v) for k, v in props.items()
                        if k not in {"entity_id", "name", "entity_type", "description"}
                    },
                )

            # Parse relationships
            rels = row.get("rels", [])
            for rel in rels:
                if not isinstance(rel, dict):
                    continue
                rid = rel.get("relation_id", f"rel_{len(edges_map)}")
                if rid in edges_map:
                    continue
                rtype = rel.get("relation_type", "related_to")
                src = rel.get("from_entity_id", rel.get("source", ""))
                tgt = rel.get("to_entity_id", rel.get("target", ""))

                if src and tgt:
                    edges_map[rid] = VisualizationEdge(
                        edge_id=rid,
                        source_id=src,
                        target_id=tgt,
                        label=rtype.replace("_", " "),
                        relation_type=rtype,
                        style=_EDGE_STYLES.get(rtype, "solid"),
                    )

        return list(nodes_map.values()), list(edges_map.values())

    def _mock_subgraph(
        self,
        center_entity: str,
        depth: int,
        max_nodes: int,
    ) -> SubgraphResult:
        """Generate mock subgraph data for testing."""
        nodes = [
            VisualizationNode(
                node_id=center_entity,
                label=center_entity.replace("ent_", ""),
                entity_type="system",
                description="Center node",
                color=_NODE_COLORS["system"],
            ),
            VisualizationNode(
                node_id="ent_module_a",
                label="ModuleA",
                entity_type="module",
                description="A module",
                color=_NODE_COLORS["module"],
            ),
            VisualizationNode(
                node_id="ent_module_b",
                label="ModuleB",
                entity_type="module",
                description="B module",
                color=_NODE_COLORS["module"],
            ),
            VisualizationNode(
                node_id="ent_table_x",
                label="TableX",
                entity_type="data_source",
                description="Data table",
                color=_NODE_COLORS["data_source"],
            ),
        ]
        edges = [
            VisualizationEdge(
                edge_id="rel_001",
                source_id=center_entity,
                target_id="ent_module_a",
                label="belongs to",
                relation_type="belongs_to",
            ),
            VisualizationEdge(
                edge_id="rel_002",
                source_id=center_entity,
                target_id="ent_module_b",
                label="calls",
                relation_type="calls",
            ),
            VisualizationEdge(
                edge_id="rel_003",
                source_id="ent_module_a",
                target_id="ent_table_x",
                label="reads from",
                relation_type="reads_from",
                style="dashed",
            ),
        ]

        return SubgraphResult(
            query=center_entity,
            center_entity_id=center_entity,
            max_hops=depth,
            nodes=nodes[:max_nodes],
            edges=edges,
            node_count=min(len(nodes), max_nodes),
            edge_count=len(edges),
            cypher_query="MOCK",
            query_time_ms=1,
        )
