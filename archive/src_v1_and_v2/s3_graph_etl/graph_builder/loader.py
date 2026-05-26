"""Graph loader - write nodes/edges to Neptune or artifact files."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from hermes_bedrock_agent.config import NeptuneConfig
from hermes_bedrock_agent.graph.neptune_client import NeptuneClient
from hermes_bedrock_agent.s3_graph_etl.schemas import GraphEdge, GraphNode

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path("data/artifacts")


class GraphLoader:
    """Load graph data to Neptune Analytics or write to artifact files."""

    def __init__(self, dry_run: bool = True, neptune_config: NeptuneConfig | None = None) -> None:
        self.dry_run = dry_run
        self._neptune: NeptuneClient | None = None
        self._neptune_config = neptune_config

    @property
    def neptune(self) -> NeptuneClient:
        if self._neptune is None:
            self._neptune = NeptuneClient(self._neptune_config)
        return self._neptune

    def load(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> dict[str, int]:
        """Load graph data. In dry-run mode, writes to artifacts. Otherwise, writes to Neptune."""
        # Always write artifacts
        self._write_artifacts(nodes, edges)

        if self.dry_run:
            logger.info("[DRY-RUN] Wrote %d nodes and %d edges to artifacts", len(nodes), len(edges))
            return {"nodes_written": len(nodes), "edges_written": len(edges), "mode": "dry_run"}

        # Write to Neptune
        return self._load_to_neptune(nodes, edges)

    def _write_artifacts(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
        """Write nodes and edges to JSONL artifact files."""
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

        nodes_path = ARTIFACTS_DIR / "nodes.jsonl"
        with open(nodes_path, "w") as f:
            for node in nodes:
                # Exclude embedding from artifacts for readability
                data = node.model_dump(exclude={"embedding"})
                f.write(json.dumps(data, ensure_ascii=False) + "\n")

        edges_path = ARTIFACTS_DIR / "edges.jsonl"
        with open(edges_path, "w") as f:
            for edge in edges:
                f.write(json.dumps(edge.model_dump(), ensure_ascii=False) + "\n")

        logger.info("Artifacts written: %s (%d nodes), %s (%d edges)",
                    nodes_path, len(nodes), edges_path, len(edges))

    def _load_to_neptune(self, nodes: list[GraphNode], edges: list[GraphEdge]) -> dict[str, int]:
        """Write nodes and edges to Neptune Analytics."""
        nodes_ok = 0
        nodes_fail = 0
        edges_ok = 0
        edges_fail = 0

        for node in nodes:
            props = {
                "name": node.name,
                "text": node.text,
                "source_uri": node.source_uri,
                "source_file": node.source_file,
                "evidence_text": node.evidence_text,
                "confidence": node.confidence,
            }
            props.update(node.properties)
            if node.embedding:
                props["embedding"] = node.embedding

            if self.neptune.upsert_node(node.id, node.label, props):
                nodes_ok += 1
            else:
                nodes_fail += 1

        for edge in edges:
            props = {
                "evidence_text": edge.evidence_text,
                "confidence": edge.confidence,
                "source_uri": edge.source_uri,
            }
            props.update(edge.properties)

            if self.neptune.upsert_edge(edge.id, edge.from_id, edge.to_id, edge.type, props):
                edges_ok += 1
            else:
                edges_fail += 1

        logger.info("Neptune load: nodes=%d/%d ok, edges=%d/%d ok",
                    nodes_ok, nodes_ok + nodes_fail, edges_ok, edges_ok + edges_fail)

        return {
            "nodes_written": nodes_ok,
            "nodes_failed": nodes_fail,
            "edges_written": edges_ok,
            "edges_failed": edges_fail,
            "mode": "neptune",
        }
