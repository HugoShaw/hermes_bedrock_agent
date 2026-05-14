"""Tests for visualization/mermaid_generator.py.

Validates:
- Label escaping
- Node/edge deduplication
- max_nodes enforcement
- Correct Mermaid syntax generation
- Direction support (LR/TD)
"""

from __future__ import annotations

import unittest

from hermes_bedrock_agent.schemas.visualization import (
    SubgraphResult,
    VisualizationEdge,
    VisualizationNode,
)
from hermes_bedrock_agent.visualization.mermaid_generator import (
    MermaidConfig,
    MermaidGenerator,
    escape_mermaid_label,
)


class TestEscapeMermaidLabel(unittest.TestCase):
    """Tests for label escaping."""

    def test_empty_string(self):
        self.assertEqual(escape_mermaid_label(""), "?")

    def test_normal_text(self):
        self.assertEqual(escape_mermaid_label("hello"), "hello")

    def test_escapes_angle_brackets(self):
        result = escape_mermaid_label("List<String>")
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)

    def test_escapes_braces(self):
        result = escape_mermaid_label("{config}")
        self.assertNotIn("{", result)
        self.assertNotIn("}", result)

    def test_escapes_brackets(self):
        result = escape_mermaid_label("[array]")
        self.assertNotIn("[", result)
        self.assertNotIn("]", result)

    def test_escapes_pipes(self):
        result = escape_mermaid_label("A|B")
        self.assertNotIn("|", result)

    def test_escapes_parentheses(self):
        result = escape_mermaid_label("func(x)")
        self.assertNotIn("(", result)
        self.assertNotIn(")", result)

    def test_escapes_quotes(self):
        result = escape_mermaid_label('say "hello"')
        self.assertNotIn('"', result)

    def test_truncates_long_labels(self):
        long_text = "a" * 100
        result = escape_mermaid_label(long_text)
        self.assertLessEqual(len(result), 40)
        self.assertTrue(result.endswith("..."))

    def test_japanese_text_preserved(self):
        result = escape_mermaid_label("仕訳基礎")
        self.assertEqual(result, "仕訳基礎")


class TestMermaidGenerator(unittest.TestCase):
    """Tests for MermaidGenerator."""

    def setUp(self):
        self.gen = MermaidGenerator()
        self.subgraph = SubgraphResult(
            query="test",
            center_entity_id="ent_001",
            nodes=[
                VisualizationNode(node_id="ent_001", label="仕訳基礎", entity_type="module"),
                VisualizationNode(node_id="ent_002", label="AP基盤", entity_type="system"),
                VisualizationNode(node_id="ent_003", label="対帳単", entity_type="module"),
            ],
            edges=[
                VisualizationEdge(
                    edge_id="rel_001", source_id="ent_001", target_id="ent_002",
                    label="belongs to", relation_type="belongs_to",
                ),
                VisualizationEdge(
                    edge_id="rel_002", source_id="ent_001", target_id="ent_003",
                    label="calls", relation_type="calls",
                ),
            ],
        )

    def test_generates_flowchart_header(self):
        """Output starts with 'flowchart LR' or 'flowchart TD'."""
        code = self.gen.generate_flowchart(self.subgraph)
        self.assertIn("flowchart LR", code)

    def test_td_direction(self):
        """TD direction is respected."""
        code = self.gen.generate_flowchart(self.subgraph, direction="TD")
        self.assertIn("flowchart TD", code)

    def test_nodes_in_output(self):
        """All nodes appear in the output."""
        code = self.gen.generate_flowchart(self.subgraph)
        self.assertIn("ent_001", code)
        self.assertIn("ent_002", code)
        self.assertIn("ent_003", code)

    def test_edges_in_output(self):
        """Edges appear as connections."""
        code = self.gen.generate_flowchart(self.subgraph)
        self.assertIn("ent_001", code)
        self.assertIn("ent_002", code)
        self.assertIn("-->", code)

    def test_max_nodes_enforced(self):
        """max_nodes limits node count in output."""
        code = self.gen.generate_flowchart(self.subgraph, max_nodes=2)
        # Only 2 nodes should be in the output
        node_count = code.count("[") + code.count("([") + code.count("[[")
        # At most 2 node definitions
        lines_with_labels = [l for l in code.split("\n") if '"' in l and "-->" not in l]
        self.assertLessEqual(len(lines_with_labels), 2)

    def test_no_duplicate_nodes(self):
        """Duplicate node IDs are deduplicated."""
        dup_subgraph = SubgraphResult(
            query="test",
            nodes=[
                VisualizationNode(node_id="ent_001", label="A", entity_type="module"),
                VisualizationNode(node_id="ent_001", label="A", entity_type="module"),
            ],
            edges=[],
        )
        code = self.gen.generate_flowchart(dup_subgraph)
        # Should only define ent_001 once
        lines = [l for l in code.split("\n") if "ent_001" in l and '"' in l]
        self.assertEqual(len(lines), 1)

    def test_no_duplicate_edges(self):
        """Duplicate edges are deduplicated."""
        dup_subgraph = SubgraphResult(
            query="test",
            nodes=[
                VisualizationNode(node_id="a", label="A", entity_type="module"),
                VisualizationNode(node_id="b", label="B", entity_type="module"),
            ],
            edges=[
                VisualizationEdge(edge_id="r1", source_id="a", target_id="b",
                                  label="x", relation_type="calls"),
                VisualizationEdge(edge_id="r2", source_id="a", target_id="b",
                                  label="x", relation_type="calls"),
            ],
        )
        code = self.gen.generate_flowchart(dup_subgraph)
        edge_lines = [l for l in code.split("\n") if "-->" in l or ".->" in l]
        self.assertEqual(len(edge_lines), 1)

    def test_impact_map_title(self):
        """Impact map includes title."""
        code = self.gen.generate_impact_map(self.subgraph, center_label="仕訳基礎")
        self.assertIn("Impact Map", code)

    def test_dependency_map_title(self):
        """Dependency map includes title."""
        code = self.gen.generate_dependency_map(self.subgraph, center_label="AP基盤")
        self.assertIn("Dependencies", code)

    def test_dashed_edge_style(self):
        """Dashed edges use -.- syntax."""
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
        code = self.gen.generate_flowchart(subgraph)
        self.assertIn("-.", code)

    def test_labels_are_escaped(self):
        """Special characters in labels are escaped."""
        subgraph = SubgraphResult(
            query="test",
            nodes=[
                VisualizationNode(node_id="x", label="List<T>", entity_type="module"),
            ],
            edges=[],
        )
        code = self.gen.generate_flowchart(subgraph)
        self.assertNotIn("<T>", code)  # Should be escaped


class TestMermaidNoEdgeLabels(unittest.TestCase):
    """Test with edge labels disabled."""

    def test_no_labels(self):
        gen = MermaidGenerator(MermaidConfig(show_edge_labels=False))
        subgraph = SubgraphResult(
            query="test",
            nodes=[
                VisualizationNode(node_id="a", label="A", entity_type="module"),
                VisualizationNode(node_id="b", label="B", entity_type="module"),
            ],
            edges=[
                VisualizationEdge(
                    edge_id="r1", source_id="a", target_id="b",
                    label="calls", relation_type="calls",
                ),
            ],
        )
        code = gen.generate_flowchart(subgraph)
        self.assertIn("-->", code)
        self.assertNotIn("|", code)  # No edge label syntax


class TestMermaidNodeIdSanitize(unittest.TestCase):
    """Tests for node ID sanitization — Phase 8.5 fix.

    Validates:
    - Japanese/Chinese node_ids produce stable hash-based IDs, not ____
    - ASCII node_ids pass through cleanly
    - Same input always produces same output
    - Labels remain intact (original text preserved)
    """

    def setUp(self):
        self.gen = MermaidGenerator()

    def test_japanese_node_id_not_underscores(self):
        """Japanese node_id must NOT become ____ or empty."""
        from hermes_bedrock_agent.visualization.mermaid_generator import _sanitize_id
        result = _sanitize_id("仕訳基礎")
        self.assertNotEqual(result, "____")
        self.assertNotEqual(result, "_")
        self.assertNotEqual(result, "")
        self.assertTrue(len(result) >= 4)

    def test_chinese_node_id_not_empty(self):
        """Chinese node_id must NOT become empty."""
        from hermes_bedrock_agent.visualization.mermaid_generator import _sanitize_id
        result = _sanitize_id("付款申請")
        self.assertNotEqual(result, "")
        self.assertNotEqual(result, "____")
        self.assertTrue(result.startswith("node_"))

    def test_mixed_jp_ascii_node_id(self):
        """Mixed JP+ASCII node_id uses ASCII prefix + hash."""
        from hermes_bedrock_agent.visualization.mermaid_generator import _sanitize_id
        result = _sanitize_id("AP仕訳基礎")
        self.assertNotEqual(result, "")
        # "AP" is the ASCII prefix, with hash suffix
        self.assertTrue(result.startswith("AP_"))
        self.assertEqual(len(result), 11)  # "AP_" + 8 hex chars

    def test_ascii_node_id_passes_through(self):
        """Standard ASCII node_id passes through unchanged."""
        from hermes_bedrock_agent.visualization.mermaid_generator import _sanitize_id
        result = _sanitize_id("ent_shiwake_001")
        self.assertEqual(result, "ent_shiwake_001")

    def test_same_input_produces_same_output(self):
        """Deterministic: same node_id always produces same sanitized ID."""
        from hermes_bedrock_agent.visualization.mermaid_generator import _sanitize_id
        id1 = _sanitize_id("仕訳基礎")
        id2 = _sanitize_id("仕訳基礎")
        self.assertEqual(id1, id2)

    def test_different_jp_ids_produce_different_outputs(self):
        """Different Japanese IDs must produce different sanitized IDs."""
        from hermes_bedrock_agent.visualization.mermaid_generator import _sanitize_id
        id1 = _sanitize_id("仕訳基礎")
        id2 = _sanitize_id("対帳単")
        id3 = _sanitize_id("付款申請")
        self.assertNotEqual(id1, id2)
        self.assertNotEqual(id2, id3)
        self.assertNotEqual(id1, id3)

    def test_empty_node_id_fallback(self):
        """Empty node_id gets a stable fallback."""
        from hermes_bedrock_agent.visualization.mermaid_generator import _sanitize_id
        result = _sanitize_id("")
        self.assertEqual(result, "node_00000000")

    def test_japanese_label_preserved_in_mermaid(self):
        """Mermaid output preserves Japanese label text."""
        subgraph = SubgraphResult(
            query="test",
            nodes=[
                VisualizationNode(
                    node_id="仕訳基礎", label="仕訳基礎モジュール",
                    entity_type="module",
                ),
            ],
            edges=[],
        )
        code = self.gen.generate_flowchart(subgraph)
        self.assertIn("仕訳基礎モジュール", code)  # label preserved
        self.assertNotIn("____", code)  # no underscores-only ID

    def test_chinese_label_preserved_in_mermaid(self):
        """Mermaid output preserves Chinese label text."""
        subgraph = SubgraphResult(
            query="test",
            nodes=[
                VisualizationNode(
                    node_id="付款申請", label="付款申請流程",
                    entity_type="business_process",
                ),
            ],
            edges=[],
        )
        code = self.gen.generate_flowchart(subgraph)
        self.assertIn("付款申請流程", code)  # label preserved

    def test_mermaid_flowchart_with_jp_nodes(self):
        """Full flowchart with Japanese node_ids is valid Mermaid syntax."""
        subgraph = SubgraphResult(
            query="test",
            nodes=[
                VisualizationNode(node_id="仕訳基礎", label="仕訳基礎", entity_type="module"),
                VisualizationNode(node_id="AP基盤", label="AP基盤", entity_type="system"),
            ],
            edges=[
                VisualizationEdge(
                    edge_id="r1", source_id="仕訳基礎", target_id="AP基盤",
                    label="belongs_to", relation_type="belongs_to",
                ),
            ],
        )
        code = self.gen.generate_flowchart(subgraph)
        # Must have flowchart header
        self.assertIn("flowchart LR", code)
        # Must have an edge (-->)
        self.assertIn("-->", code)
        # No ____ IDs
        self.assertNotIn("____", code)
        # Labels preserved
        self.assertIn("仕訳基礎", code)
        self.assertIn("AP基盤", code)

    def test_node_id_all_valid_mermaid_chars(self):
        """Sanitized IDs contain only valid Mermaid chars (a-z, A-Z, 0-9, _)."""
        from hermes_bedrock_agent.visualization.mermaid_generator import _sanitize_id
        test_ids = ["仕訳基礎", "AP基盤", "対帳単", "テスト", "abc123", "ent_001"]
        for node_id in test_ids:
            sanitized = _sanitize_id(node_id)
            self.assertRegex(
                sanitized, r"^[a-zA-Z0-9_]+$",
                f"Sanitized ID '{sanitized}' from '{node_id}' has invalid chars",
            )


if __name__ == "__main__":
    unittest.main()
