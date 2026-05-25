"""
Excel Neptune Graph Exporter — export full graph from Neptune to JSON/JSONL.

Queries Neptune for all nodes and relationships matching the given run_id/dataset,
then exports them in a format suitable for visualization.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExcelNeptuneGraphExporter:
    """Export graph data from Neptune for visualization."""

    def __init__(
        self,
        neptune_client: Any,
        run_id: str,
        dataset: str,
        output_dir: str | Path,
    ):
        self.client = neptune_client
        self.run_id = run_id
        self.dataset = dataset
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.nodes: list[dict] = []
        self.edges: list[dict] = []

    def export_all(self) -> dict[str, Any]:
        """Export all nodes and edges from Neptune."""
        logger.info("Exporting nodes from Neptune...")
        self._export_nodes()
        logger.info("Exported %d nodes", len(self.nodes))

        logger.info("Exporting edges from Neptune...")
        self._export_edges()
        logger.info("Exported %d edges", len(self.edges))

        # Write outputs
        self._write_outputs()

        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes": self.nodes,
            "edges": self.edges,
        }

    def _export_nodes(self):
        """Query all nodes matching run_id."""
        query = (
            "MATCH (n) WHERE n.run_id = $run_id AND n.dataset = $dataset "
            "RETURN n"
        )
        result = self.client.execute_query(
            query, {"run_id": self.run_id, "dataset": self.dataset}
        )
        for row in result.get("results", []):
            node_raw = row.get("n", {})
            node = self._parse_node(node_raw)
            if node:
                self.nodes.append(node)

    def _export_edges(self):
        """Query all relationships matching run_id."""
        query = (
            "MATCH (a)-[r]->(b) WHERE r.run_id = $run_id AND r.dataset = $dataset "
            "RETURN a.`~id` AS src_id, b.`~id` AS tgt_id, "
            "type(r) AS rel_type, properties(r) AS props"
        )
        result = self.client.execute_query(
            query, {"run_id": self.run_id, "dataset": self.dataset}
        )
        for row in result.get("results", []):
            edge = self._parse_edge(row)
            if edge:
                self.edges.append(edge)

    def _parse_node(self, raw: dict) -> dict | None:
        """Parse Neptune node response into flat dict."""
        node_id = raw.get("~id")
        if not node_id:
            return None
        labels = raw.get("~labels", [])
        props = raw.get("~properties", {})
        return {
            "id": node_id,
            "label": labels[0] if labels else "Unknown",
            "name": props.get("name", ""),
            "display_name": props.get("display_name", props.get("name", "")),
            "layer": props.get("layer", ""),
            "dataset": props.get("dataset", ""),
            "run_id": props.get("run_id", ""),
            "confidence": props.get("confidence", 0.0),
            "evidence_count": props.get("evidence_count", 0),
            "evidence_chunk_ids": props.get("evidence_chunk_ids", ""),
            "source_ids": props.get("source_ids", ""),
            "sheet_name": props.get("sheet_name", ""),
            "cell_range": props.get("cell_range", ""),
            "text_preview": props.get("text_preview", ""),
            "description": props.get("description", ""),
            "chunk_type": props.get("chunk_type", ""),
            "heading_path": props.get("heading_path", ""),
            "title": props.get("title", ""),
            "evidence_quality_score": props.get("evidence_quality_score", 0.0),
            "properties": {k: v for k, v in props.items() if k not in (
                "name", "display_name", "layer", "dataset", "run_id",
                "confidence", "evidence_count", "evidence_chunk_ids",
                "source_ids", "sheet_name", "cell_range", "text_preview",
                "description", "chunk_type", "heading_path", "title",
                "evidence_quality_score",
            )},
        }

    def _parse_edge(self, row: dict) -> dict | None:
        """Parse Neptune edge query row into flat dict."""
        src_id = row.get("src_id")
        tgt_id = row.get("tgt_id")
        rel_type = row.get("rel_type", "")
        props = row.get("props", {})
        if not src_id or not tgt_id:
            return None
        return {
            "id": props.get("relation_id", f"{src_id}_{rel_type}_{tgt_id}"),
            "source": src_id,
            "target": tgt_id,
            "type": rel_type,
            "relation_type": rel_type,
            "layer": props.get("layer", ""),
            "dataset": props.get("dataset", ""),
            "run_id": props.get("run_id", ""),
            "confidence": props.get("confidence", 0.0),
            "evidence_count": props.get("evidence_count", 0),
            "evidence_chunk_ids": props.get("evidence_chunk_ids", ""),
            "evidence_quality_score": props.get("evidence_quality_score", 0.0),
            "sheet_name": props.get("sheet_name", ""),
            "cell_range": props.get("cell_range", ""),
        }

    def _write_outputs(self):
        """Write export files."""
        # Full JSON
        full_path = self.output_dir / "neptune_graph_export.json"
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(
                {"nodes": self.nodes, "edges": self.edges},
                f, ensure_ascii=False, indent=2,
            )
        logger.info("Wrote %s", full_path)

        # Nodes JSONL
        nodes_path = self.output_dir / "neptune_graph_nodes.jsonl"
        with open(nodes_path, "w", encoding="utf-8") as f:
            for n in self.nodes:
                f.write(json.dumps(n, ensure_ascii=False) + "\n")

        # Edges JSONL
        edges_path = self.output_dir / "neptune_graph_edges.jsonl"
        with open(edges_path, "w", encoding="utf-8") as f:
            for e in self.edges:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")


class LocalJSONLGraphExporter:
    """Fallback: export graph from local JSONL files."""

    def __init__(
        self,
        nodes_path: str | Path,
        edges_path: str | Path,
        chunks_path: str | Path,
        run_id: str,
        dataset: str,
        output_dir: str | Path,
    ):
        self.nodes_path = Path(nodes_path)
        self.edges_path = Path(edges_path)
        self.chunks_path = Path(chunks_path)
        self.run_id = run_id
        self.dataset = dataset
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.nodes: list[dict] = []
        self.edges: list[dict] = []

    def export_all(self) -> dict[str, Any]:
        """Load nodes/edges from local JSONL."""
        # Load graph nodes
        with open(self.nodes_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    node = json.loads(line)
                    self.nodes.append({
                        "id": node.get("node_id", ""),
                        "label": node.get("label", "Unknown"),
                        "name": node.get("name", ""),
                        "display_name": node.get("display_name", node.get("name", "")),
                        "layer": node.get("layer", ""),
                        "dataset": node.get("dataset", self.dataset),
                        "run_id": node.get("run_id", self.run_id),
                        "confidence": node.get("confidence", 0.0),
                        "evidence_count": len(node.get("evidence_chunk_ids", [])),
                        "evidence_chunk_ids": "|".join(node.get("evidence_chunk_ids", [])),
                        "source_ids": "|".join(str(s) for s in node.get("source_ids", [])),
                        "sheet_name": node.get("properties", {}).get("sheet_name", ""),
                        "cell_range": node.get("properties", {}).get("cell_range", ""),
                        "text_preview": "",
                        "description": node.get("properties", {}).get("description", ""),
                        "chunk_type": "",
                        "heading_path": "",
                        "title": "",
                        "evidence_quality_score": node.get("properties", {}).get("evidence_quality_score", 0.0),
                        "properties": node.get("properties", {}),
                    })

        # Load evidence chunks as nodes
        if self.chunks_path.exists():
            with open(self.chunks_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        chunk = json.loads(line)
                        self.nodes.append({
                            "id": chunk.get("chunk_id", ""),
                            "label": "EvidenceChunk",
                            "name": chunk.get("title", chunk.get("chunk_id", "")[:20]),
                            "display_name": chunk.get("title", ""),
                            "layer": "evidence",
                            "dataset": self.dataset,
                            "run_id": self.run_id,
                            "confidence": 1.0,
                            "evidence_count": 0,
                            "evidence_chunk_ids": "",
                            "source_ids": "",
                            "sheet_name": chunk.get("metadata", {}).get("sheet_name", ""),
                            "cell_range": chunk.get("metadata", {}).get("cell_range", ""),
                            "text_preview": chunk.get("text", "")[:200],
                            "description": "",
                            "chunk_type": chunk.get("chunk_type", ""),
                            "heading_path": str(chunk.get("heading_path", "")),
                            "title": chunk.get("title", ""),
                            "evidence_quality_score": 1.0,
                            "properties": {},
                        })

        # Load edges
        with open(self.edges_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    edge = json.loads(line)
                    self.edges.append({
                        "id": edge.get("edge_id", ""),
                        "source": edge.get("source_node_id", ""),
                        "target": edge.get("target_node_id", ""),
                        "type": edge.get("relation_type", ""),
                        "relation_type": edge.get("relation_type", ""),
                        "layer": edge.get("layer", ""),
                        "dataset": edge.get("dataset", self.dataset),
                        "run_id": edge.get("run_id", self.run_id),
                        "confidence": edge.get("confidence", 0.0),
                        "evidence_count": len(edge.get("evidence_chunk_ids", [])),
                        "evidence_chunk_ids": "|".join(edge.get("evidence_chunk_ids", [])),
                        "evidence_quality_score": edge.get("properties", {}).get("evidence_quality_score", 0.0),
                        "sheet_name": edge.get("properties", {}).get("sheet_name", ""),
                        "cell_range": edge.get("properties", {}).get("cell_range", ""),
                    })

        # Write outputs
        full_path = self.output_dir / "neptune_graph_export.json"
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(
                {"nodes": self.nodes, "edges": self.edges},
                f, ensure_ascii=False, indent=2,
            )
        nodes_path = self.output_dir / "neptune_graph_nodes.jsonl"
        with open(nodes_path, "w", encoding="utf-8") as f:
            for n in self.nodes:
                f.write(json.dumps(n, ensure_ascii=False) + "\n")
        edges_path = self.output_dir / "neptune_graph_edges.jsonl"
        with open(edges_path, "w", encoding="utf-8") as f:
            for e in self.edges:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "nodes": self.nodes,
            "edges": self.edges,
        }
