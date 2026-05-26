#!/usr/bin/env python3
"""Export Mermaid — query Neptune subgraph and render as Mermaid diagram.

Usage:
    python scripts/export_mermaid.py --center-entity "仕訳基礎" --depth 2
    python scripts/export_mermaid.py --from-artifacts --run-id murata_full_vlm_live_001
    python scripts/export_mermaid.py --center-entity "PaymentReqAction" --output graph.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hermes_bedrock_agent.configs.logging import get_logger

logger = get_logger("export_mermaid")

DEFAULT_RUN_ID = "murata_full_vlm_live_001"
DEFAULT_ARTIFACT_BASE = Path.home() / "projects/data/enterprise_graphrag/runs"
DEFAULT_NEPTUNE_ENDPOINT = "g-nbuyck5yl8.ap-northeast-1.neptune-graph.amazonaws.com"


def main():
    parser = argparse.ArgumentParser(description="Export Mermaid diagrams from Neptune or artifacts")
    parser.add_argument("--center-entity", help="Entity name or ID to center the subgraph on")
    parser.add_argument("--depth", type=int, default=2, help="Traversal depth (default: 2)")
    parser.add_argument("--max-nodes", type=int, default=30, help="Max nodes (default: 30)")
    parser.add_argument("--direction", default="LR", choices=["LR", "TD"], help="Graph direction")
    parser.add_argument("--from-artifacts", action="store_true", help="Build from local artifacts (no Neptune)")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run ID for artifact lookup")
    parser.add_argument("--artifact-base", type=Path, default=DEFAULT_ARTIFACT_BASE)
    parser.add_argument("--neptune-endpoint", default=DEFAULT_NEPTUNE_ENDPOINT)
    parser.add_argument("--output", "-o", type=Path, help="Output file (default: stdout)")
    parser.add_argument("--entity-types", nargs="*", help="Filter by entity types")
    args = parser.parse_args()

    os.environ.setdefault("AWS_DEFAULT_REGION", "ap-northeast-1")

    from hermes_bedrock_agent.visualization.mermaid_generator import MermaidGenerator, MermaidConfig
    from hermes_bedrock_agent.schemas.visualization import SubgraphResult, VisualizationNode, VisualizationEdge

    generator = MermaidGenerator(config=MermaidConfig(
        direction=args.direction,
        max_nodes=args.max_nodes,
        show_edge_labels=True,
    ))

    if args.from_artifacts:
        subgraph = _build_from_artifacts(args)
    elif args.center_entity:
        subgraph = _query_neptune(args)
    else:
        print("ERROR: Provide --center-entity or --from-artifacts", file=sys.stderr)
        sys.exit(1)

    mermaid_code = generator.generate(subgraph)

    # Output
    output_md = (
        f"# Mermaid Graph Export\n\n"
        f"**Center:** {args.center_entity or 'all'}\n"
        f"**Depth:** {args.depth}\n"
        f"**Nodes:** {len(subgraph.nodes)}\n"
        f"**Edges:** {len(subgraph.edges)}\n\n"
        f"```mermaid\n{mermaid_code}\n```\n"
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_md, encoding="utf-8")
        print(f"Written to: {args.output}")
    else:
        print(output_md)


def _build_from_artifacts(args) -> "SubgraphResult":
    """Build subgraph from local JSONL artifacts."""
    from hermes_bedrock_agent.schemas.visualization import SubgraphResult, VisualizationNode, VisualizationEdge

    artifact_dir = args.artifact_base / args.run_id / "artifacts"
    entities_path = artifact_dir / "entities.jsonl"
    relations_path = artifact_dir / "relations.jsonl"

    if not entities_path.exists():
        print(f"ERROR: {entities_path} not found", file=sys.stderr)
        sys.exit(1)

    entities = _load_jsonl(entities_path)
    relations = _load_jsonl(relations_path) if relations_path.exists() else []

    # Filter by entity types if specified
    if args.entity_types:
        entities = [e for e in entities if e.get("entity_type") in args.entity_types]

    # Filter by center entity if specified
    if args.center_entity:
        entities, relations = _filter_by_center(entities, relations, args.center_entity, args.depth)

    # Limit
    entities = entities[:args.max_nodes]
    entity_ids = {e["entity_id"] for e in entities}

    nodes = [
        VisualizationNode(
            node_id=e["entity_id"],
            label=e.get("name", e.get("canonical_name", "?")),
            node_type=e.get("entity_type", "unknown"),
            properties={"description": e.get("description", "")[:100]},
        )
        for e in entities
    ]

    edges = [
        VisualizationEdge(
            edge_id=r.get("relation_id", ""),
            source_id=r["source_entity_id"],
            target_id=r["target_entity_id"],
            edge_type=r.get("relation_type", "related_to"),
            label=r.get("description", "")[:30],
        )
        for r in relations
        if r.get("source_entity_id") in entity_ids and r.get("target_entity_id") in entity_ids
    ]

    return SubgraphResult(
        nodes=nodes,
        edges=edges,
        center_entity=args.center_entity or "all",
        depth=args.depth,
        query_time_ms=0,
    )


def _query_neptune(args) -> "SubgraphResult":
    """Query Neptune for a live subgraph."""
    from hermes_bedrock_agent.clients.neptune_client import NeptuneClient
    from hermes_bedrock_agent.visualization.subgraph_query import SubgraphQueryService

    graph_id = args.neptune_endpoint.split(".")[0]
    neptune = NeptuneClient(graph_id=graph_id, region="ap-northeast-1")
    query_svc = SubgraphQueryService(neptune)

    return query_svc.query_subgraph(
        args.center_entity,
        depth=args.depth,
        max_nodes=args.max_nodes,
    )


def _filter_by_center(entities, relations, center: str, depth: int):
    """BFS filter around a center entity."""
    # Find center by name or ID
    center_ids = set()
    for e in entities:
        if (center.lower() in e.get("name", "").lower()
                or center.lower() in e.get("canonical_name", "").lower()
                or e.get("entity_id") == center):
            center_ids.add(e["entity_id"])

    if not center_ids:
        return entities[:30], relations  # No match, return all limited

    # BFS expansion
    visited = set(center_ids)
    frontier = set(center_ids)

    for _ in range(depth):
        next_frontier = set()
        for r in relations:
            src = r.get("source_entity_id", "")
            tgt = r.get("target_entity_id", "")
            if src in frontier and tgt not in visited:
                next_frontier.add(tgt)
                visited.add(tgt)
            if tgt in frontier and src not in visited:
                next_frontier.add(src)
                visited.add(src)
        frontier = next_frontier
        if not frontier:
            break

    filtered_entities = [e for e in entities if e["entity_id"] in visited]
    filtered_relations = [
        r for r in relations
        if r.get("source_entity_id") in visited and r.get("target_entity_id") in visited
    ]
    return filtered_entities, filtered_relations


def _load_jsonl(path: Path) -> list[dict]:
    """Load JSONL file."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


if __name__ == "__main__":
    main()
