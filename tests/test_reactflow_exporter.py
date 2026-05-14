"""Tests for visualization/reactflow_exporter.py.

Validates:
- Export produces nodes/edges/metadata
- Positions are included
- Node types are mapped correctly
- JSON export is valid
"""

from __future__ import annotations

import json
import unittest

from hermes_bedrock_agent.schemas.visualization import (
    SubgraphResult,
    VisualizationEdge,
    VisualizationNode,
)
from hermes_bedrock_agent.visualization.reactflow_exporter import (
    ReactFlowConfig,
    ReactFlowExporter,
)


class TestReactFlowExporter(unittest.TestCase):
    """Tests for ReactFlowExporter."""

    def setUp(self):
        self.exporter = ReactFlowExporter()
        self.subgraph = SubgraphResult(
            query="test query",
            center_entity_id="ent_001",
            max_hops=2,
            nodes=[
                VisualizationNode(
                    node_id="ent_001", label="仕訳基礎",
                    entity_type="module", description="Core module",
                    x=100.0, y=200.0, degree=3,
                ),
                VisualizationNode(
                    node_id="ent_002", label="AP基盤",
                    entity_type="system", description="AP platform",
                    x=300.0, y=200.0, degree=5,
                ),
            ],
            edges=[
                VisualizationEdge(
                    edge_id="rel_001", source_id="ent_001", target_id="ent_002",
                    label="belongs to", relation_type="belongs_to",
                ),
            ],
            layout_computed=True,
        )

    def test_export_has_nodes(self):
        """Export result contains nodes array."""
        result = self.exporter.export(self.subgraph)
        self.assertIn("nodes", result)
        self.assertEqual(len(result["nodes"]), 2)

    def test_export_has_edges(self):
        """Export result contains edges array."""
        result = self.exporter.export(self.subgraph)
        self.assertIn("edges", result)
        self.assertEqual(len(result["edges"]), 1)

    def test_export_has_metadata(self):
        """Export result contains metadata."""
        result = self.exporter.export(self.subgraph)
        self.assertIn("metadata", result)
        self.assertEqual(result["metadata"]["center_entity_id"], "ent_001")
        self.assertEqual(result["metadata"]["node_count"], 2)

    def test_nodes_have_positions(self):
        """Nodes include x/y positions."""
        result = self.exporter.export(self.subgraph)
        node = result["nodes"][0]
        self.assertIn("position", node)
        self.assertEqual(node["position"]["x"], 100.0)
        self.assertEqual(node["position"]["y"], 200.0)

    def test_nodes_have_labels(self):
        """Nodes include label in data."""
        result = self.exporter.export(self.subgraph)
        node = result["nodes"][0]
        self.assertIn("data", node)
        self.assertEqual(node["data"]["label"], "仕訳基礎")

    def test_nodes_have_type(self):
        """Nodes have React Flow type."""
        result = self.exporter.export(self.subgraph)
        node = result["nodes"][0]
        self.assertIn("type", node)
        self.assertEqual(node["type"], "module")

    def test_nodes_have_style(self):
        """Nodes include style with background color."""
        result = self.exporter.export(self.subgraph)
        node = result["nodes"][0]
        self.assertIn("style", node)
        self.assertIn("background", node["style"])

    def test_edges_have_source_target(self):
        """Edges have source and target."""
        result = self.exporter.export(self.subgraph)
        edge = result["edges"][0]
        self.assertEqual(edge["source"], "ent_001")
        self.assertEqual(edge["target"], "ent_002")

    def test_edges_have_label(self):
        """Edges include label."""
        result = self.exporter.export(self.subgraph)
        edge = result["edges"][0]
        self.assertEqual(edge["label"], "belongs to")

    def test_edges_have_type(self):
        """Edges have React Flow edge type."""
        result = self.exporter.export(self.subgraph)
        edge = result["edges"][0]
        self.assertIn("type", edge)
        self.assertEqual(edge["type"], "smoothstep")

    def test_json_export_valid(self):
        """JSON export produces valid JSON."""
        json_str = self.exporter.export_json(self.subgraph)
        parsed = json.loads(json_str)
        self.assertIn("nodes", parsed)
        self.assertIn("edges", parsed)

    def test_json_export_utf8(self):
        """JSON export preserves Japanese text."""
        json_str = self.exporter.export_json(self.subgraph)
        self.assertIn("仕訳基礎", json_str)

    def test_no_positions_mode(self):
        """When include_positions=False, positions default to 0,0."""
        result = self.exporter.export(self.subgraph, include_positions=False)
        node = result["nodes"][0]
        self.assertEqual(node["position"], {"x": 0, "y": 0})

    def test_metadata_disabled(self):
        """Metadata can be disabled via config."""
        exporter = ReactFlowExporter(ReactFlowConfig(include_metadata=False))
        result = exporter.export(self.subgraph)
        self.assertNotIn("metadata", result)

    def test_animated_edges(self):
        """Animated edges config is applied."""
        exporter = ReactFlowExporter(ReactFlowConfig(animated_edges=True))
        result = exporter.export(self.subgraph)
        edge = result["edges"][0]
        self.assertTrue(edge.get("animated"))

    def test_dashed_edge_style(self):
        """Dashed edges have strokeDasharray."""
        subgraph = SubgraphResult(
            query="test",
            nodes=[
                VisualizationNode(node_id="a", label="A", entity_type="module"),
                VisualizationNode(node_id="b", label="B", entity_type="table"),
            ],
            edges=[
                VisualizationEdge(
                    edge_id="r1", source_id="a", target_id="b",
                    label="reads", relation_type="reads_from", style="dashed",
                ),
            ],
        )
        result = self.exporter.export(subgraph)
        edge = result["edges"][0]
        self.assertIn("style", edge)
        self.assertIn("strokeDasharray", edge["style"])

    def test_empty_subgraph(self):
        """Empty subgraph produces empty arrays."""
        empty = SubgraphResult(query="empty")
        result = self.exporter.export(empty)
        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["edges"], [])


if __name__ == "__main__":
    unittest.main()
