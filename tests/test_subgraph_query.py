"""Tests for visualization/subgraph_query.py.

Validates:
- Never queries full graph (always requires center_entity)
- max_nodes is enforced
- Mock mode returns bounded data
- Parameterized query is built correctly
"""

from __future__ import annotations

import unittest

from hermes_bedrock_agent.visualization.subgraph_query import (
    SubgraphQueryConfig,
    SubgraphQueryService,
)


class TestSubgraphQueryMockMode(unittest.TestCase):
    """Tests for SubgraphQueryService in mock mode."""

    def setUp(self):
        self.service = SubgraphQueryService(mock_mode=True)

    def test_requires_center_entity(self):
        """Must always have center_entity — never full graph scan."""
        result = self.service.query_subgraph("ent_shiwake")
        self.assertEqual(result.center_entity_id, "ent_shiwake")
        self.assertGreater(result.node_count, 0)

    def test_mock_returns_bounded_nodes(self):
        """Mock mode returns a small bounded subgraph."""
        result = self.service.query_subgraph("ent_center", depth=2)
        self.assertLessEqual(result.node_count, 50)
        self.assertGreater(result.node_count, 0)

    def test_max_nodes_enforced(self):
        """max_nodes limits the result set."""
        result = self.service.query_subgraph("ent_center", max_nodes=2)
        self.assertLessEqual(result.node_count, 2)
        self.assertLessEqual(len(result.nodes), 2)

    def test_max_nodes_capped_by_config(self):
        """max_nodes cannot exceed config.max_allowed_nodes."""
        config = SubgraphQueryConfig(max_allowed_nodes=10)
        service = SubgraphQueryService(config=config, mock_mode=True)
        result = service.query_subgraph("ent_center", max_nodes=999)
        self.assertLessEqual(len(result.nodes), 10)

    def test_depth_capped_by_config(self):
        """depth cannot exceed config.max_allowed_depth."""
        config = SubgraphQueryConfig(max_allowed_depth=3)
        service = SubgraphQueryService(config=config, mock_mode=True)
        result = service.query_subgraph("ent_center", depth=99)
        self.assertEqual(result.max_hops, 3)

    def test_nodes_have_required_fields(self):
        """Each node has node_id, label, entity_type."""
        result = self.service.query_subgraph("ent_center")
        for node in result.nodes:
            self.assertTrue(node.node_id)
            self.assertTrue(node.label)
            self.assertTrue(node.entity_type)

    def test_edges_have_required_fields(self):
        """Each edge has edge_id, source_id, target_id."""
        result = self.service.query_subgraph("ent_center")
        for edge in result.edges:
            self.assertTrue(edge.edge_id)
            self.assertTrue(edge.source_id)
            self.assertTrue(edge.target_id)

    def test_center_entity_in_results(self):
        """The center entity should be in the result nodes."""
        result = self.service.query_subgraph("ent_center")
        node_ids = [n.node_id for n in result.nodes]
        self.assertIn("ent_center", node_ids)

    def test_query_time_present(self):
        """Mock queries should have query_time_ms."""
        result = self.service.query_subgraph("ent_center")
        self.assertIsNotNone(result.query_time_ms)


class TestSubgraphQueryBuild(unittest.TestCase):
    """Tests for query building (without executing)."""

    def setUp(self):
        self.service = SubgraphQueryService(mock_mode=False)

    def test_build_query_has_center_param(self):
        """Built query must use parameterized center_id."""
        query, params = self.service._build_subgraph_query(
            "ent_test", depth=2, max_nodes=50
        )
        self.assertIn("$center_id", query)
        self.assertEqual(params["center_id"], "ent_test")

    def test_build_query_has_limit(self):
        """Built query must include LIMIT."""
        query, params = self.service._build_subgraph_query(
            "ent_test", depth=2, max_nodes=25
        )
        self.assertIn("LIMIT", query)
        self.assertEqual(params["limit"], 25)

    def test_build_query_with_node_types(self):
        """Node type filters become parameterized."""
        query, params = self.service._build_subgraph_query(
            "ent_test", depth=2, max_nodes=50,
            node_types=["module", "system"],
        )
        self.assertIn("$ntype_0", query)
        self.assertEqual(params["ntype_0"], "module")
        self.assertEqual(params["ntype_1"], "system")

    def test_build_query_with_exclude_types(self):
        """Exclude types become parameterized."""
        query, params = self.service._build_subgraph_query(
            "ent_test", depth=2, max_nodes=50,
            exclude_node_types=["unknown"],
        )
        self.assertIn("$excl_0", query)
        self.assertEqual(params["excl_0"], "unknown")

    def test_no_full_graph_scan(self):
        """Query always has center constraint, never scans all nodes."""
        query, _ = self.service._build_subgraph_query(
            "ent_test", depth=2, max_nodes=50
        )
        # Must have a starting point constraint
        self.assertIn("center", query)
        self.assertIn("$center_id", query)


class TestSubgraphQueryWithMockClient(unittest.TestCase):
    """Tests with a mock Neptune client."""

    def test_empty_results(self):
        """Empty Neptune results produce empty subgraph."""

        class MockClient:
            def execute_query(self, query, parameters=None):
                return []

        service = SubgraphQueryService(neptune_client=MockClient())
        result = service.query_subgraph("ent_missing")
        self.assertEqual(result.node_count, 0)
        self.assertEqual(result.edge_count, 0)

    def test_client_error_returns_empty(self):
        """Neptune client errors are caught, return empty subgraph."""

        class ErrorClient:
            def execute_query(self, query, parameters=None):
                raise ConnectionError("Neptune down")

        service = SubgraphQueryService(neptune_client=ErrorClient())
        result = service.query_subgraph("ent_test")
        self.assertEqual(result.node_count, 0)

    def test_parses_node_properties(self):
        """Nodes are parsed from node_props in results."""

        class MockClient:
            def execute_query(self, query, parameters=None):
                return [
                    {
                        "node_props": [
                            {
                                "entity_id": "ent_001",
                                "name": "TestEntity",
                                "entity_type": "module",
                                "description": "A test",
                            }
                        ],
                        "rels": [],
                    }
                ]

        service = SubgraphQueryService(neptune_client=MockClient())
        result = service.query_subgraph("ent_001")
        self.assertEqual(len(result.nodes), 1)
        self.assertEqual(result.nodes[0].node_id, "ent_001")
        self.assertEqual(result.nodes[0].label, "TestEntity")
        self.assertEqual(result.nodes[0].entity_type, "module")


if __name__ == "__main__":
    unittest.main()
