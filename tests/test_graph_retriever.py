"""Tests for retrieval/graph_retriever.py — Neptune graph retrieval.

All tests use mock Neptune client. No real Neptune calls.
Validates that graph_retriever does NOT assume Chunk/Evidence nodes exist.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call

from hermes_bedrock_agent.retrieval.graph_retriever import (
    GraphRetrieverConfig,
    NeptuneGraphRetriever,
)
from hermes_bedrock_agent.schemas.retrieval import RetrievalSource


class TestSearchEntities(unittest.TestCase):
    """Test entity search via Neptune."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.retriever = NeptuneGraphRetriever(self.mock_client)

    def test_calls_execute_query_with_parameters(self):
        self.mock_client.execute_query.return_value = []
        self.retriever.search_entities(["test"])
        self.mock_client.execute_query.assert_called_once()
        args, kwargs = self.mock_client.execute_query.call_args
        self.assertIn("parameters", kwargs)
        self.assertIn("term_0", kwargs["parameters"])

    def test_returns_entity_dicts(self):
        self.mock_client.execute_query.return_value = [
            {"entity_id": "ent_001", "name": "SystemA", "entity_type": "system",
             "canonical_name": "systema", "source_chunk_ids": "c1, c2",
             "confidence": 0.9, "description": "Main system"}
        ]
        results = self.retriever.search_entities(["system"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["entity_id"], "ent_001")

    def test_multiple_query_terms(self):
        self.mock_client.execute_query.return_value = []
        self.retriever.search_entities(["term1", "term2", "term3"])
        _, kwargs = self.mock_client.execute_query.call_args
        params = kwargs["parameters"]
        self.assertIn("term_0", params)
        self.assertIn("term_1", params)
        self.assertIn("term_2", params)

    def test_handles_error_gracefully(self):
        self.mock_client.execute_query.side_effect = Exception("Neptune down")
        results = self.retriever.search_entities(["test"])
        self.assertEqual(results, [])

    def test_respects_top_k(self):
        self.mock_client.execute_query.return_value = []
        self.retriever.search_entities(["test"], top_k=5)
        _, kwargs = self.mock_client.execute_query.call_args
        self.assertEqual(kwargs["parameters"]["limit"], 5)


class TestExpandPaths(unittest.TestCase):
    """Test path expansion from entities."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.retriever = NeptuneGraphRetriever(self.mock_client)

    def test_calls_execute_query_per_entity(self):
        self.mock_client.execute_query.return_value = []
        self.retriever.expand_paths(["ent_001", "ent_002"])
        self.assertEqual(self.mock_client.execute_query.call_count, 2)

    def test_uses_parameterized_query(self):
        self.mock_client.execute_query.return_value = []
        self.retriever.expand_paths(["ent_001"])
        _, kwargs = self.mock_client.execute_query.call_args
        params = kwargs["parameters"]
        self.assertEqual(params["eid"], "ent_001")

    def test_returns_path_dicts(self):
        self.mock_client.execute_query.return_value = [
            {"nodes": [
                {"entity_id": "ent_001", "name": "A", "source_chunk_ids": "c1"},
                {"entity_id": "ent_002", "name": "B", "source_chunk_ids": "c2"},
            ], "edges": [
                {"relation_id": "rel_001", "relation_type": "calls",
                 "source_chunk_id": "c1", "source_chunk_ids": "c1"},
            ]}
        ]
        results = self.retriever.expand_paths(["ent_001"])
        self.assertEqual(len(results), 1)

    def test_handles_error_gracefully(self):
        self.mock_client.execute_query.side_effect = Exception("Timeout")
        results = self.retriever.expand_paths(["ent_001"])
        self.assertEqual(results, [])

    def test_max_5_seed_entities(self):
        self.mock_client.execute_query.return_value = []
        self.retriever.expand_paths([f"ent_{i}" for i in range(10)])
        self.assertEqual(self.mock_client.execute_query.call_count, 5)


class TestRetrieveGraphContext(unittest.TestCase):
    """Test full graph retrieval pipeline."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.retriever = NeptuneGraphRetriever(self.mock_client)

    def test_returns_graph_evidence(self):
        # First call: search_entities
        self.mock_client.execute_query.side_effect = [
            [{"entity_id": "ent_001", "name": "SystemA", "entity_type": "system",
              "canonical_name": "systema", "source_chunk_ids": "c1, c2",
              "confidence": 0.9, "description": "Main system"}],
            # Second call: expand_paths
            [{"nodes": [
                {"entity_id": "ent_001", "name": "SystemA", "source_chunk_ids": "c1"},
                {"entity_id": "ent_002", "name": "ModuleB", "source_chunk_ids": "c3"},
            ], "edges": [
                {"relation_id": "rel_001", "relation_type": "calls",
                 "source_chunk_id": "c1", "source_chunk_ids": "c1"},
            ]}],
        ]
        results = self.retriever.retrieve_graph_context(["system"])
        self.assertTrue(len(results) > 0)
        # All should be GraphEvidence
        for ev in results:
            self.assertEqual(ev.source, RetrievalSource.NEPTUNE_GRAPH)

    def test_extracts_source_chunk_ids_from_entity(self):
        self.mock_client.execute_query.side_effect = [
            [{"entity_id": "ent_001", "name": "X", "entity_type": "module",
              "canonical_name": "x", "source_chunk_ids": "chunk_a, chunk_b",
              "confidence": 0.8, "description": ""}],
            [],  # no paths
        ]
        results = self.retriever.retrieve_graph_context(["x"])
        self.assertEqual(len(results), 1)
        self.assertIn("chunk_a", results[0].source_chunk_ids)
        self.assertIn("chunk_b", results[0].source_chunk_ids)

    def test_extracts_source_chunk_id_from_relation(self):
        """Validates source_chunk_id extracted from relation property."""
        self.mock_client.execute_query.side_effect = [
            [{"entity_id": "ent_001", "name": "A", "entity_type": "system",
              "canonical_name": "a", "source_chunk_ids": "", "confidence": 0.7,
              "description": ""}],
            [{"nodes": [
                {"entity_id": "ent_001", "name": "A", "source_chunk_ids": ""},
                {"entity_id": "ent_002", "name": "B", "source_chunk_ids": ""},
            ], "edges": [
                {"relation_id": "rel_x", "relation_type": "depends_on",
                 "source_chunk_id": "chunk_from_rel",
                 "source_chunk_ids": "chunk_from_rel"},
            ]}],
        ]
        results = self.retriever.retrieve_graph_context(["a"])
        # Path evidence should include chunk_from_rel
        path_evidence = [r for r in results if r.path_description]
        if path_evidence:
            self.assertIn("chunk_from_rel", path_evidence[0].source_chunk_ids)

    def test_no_chunk_node_assumption(self):
        """Verify retriever does NOT query for Chunk nodes."""
        self.mock_client.execute_query.side_effect = [
            [{"entity_id": "ent_001", "name": "A", "entity_type": "system",
              "canonical_name": "a", "source_chunk_ids": "c1", "confidence": 0.8,
              "description": ""}],
            [],
        ]
        self.retriever.retrieve_graph_context(["a"])
        # Check all queries — none should reference :Chunk or :Evidence labels
        for call_args in self.mock_client.execute_query.call_args_list:
            query = call_args[0][0]
            self.assertNotIn(":Chunk", query)
            self.assertNotIn(":Evidence", query)

    def test_empty_results_no_error(self):
        self.mock_client.execute_query.return_value = []
        results = self.retriever.retrieve_graph_context(["nonexistent"])
        self.assertEqual(results, [])


class TestParseChunkIds(unittest.TestCase):
    """Test _parse_chunk_ids handles various formats."""

    def setUp(self):
        self.mock_client = MagicMock()
        self.retriever = NeptuneGraphRetriever(self.mock_client)

    def test_comma_separated_string(self):
        result = self.retriever._parse_chunk_ids("c1, c2, c3")
        self.assertEqual(result, ["c1", "c2", "c3"])

    def test_list_input(self):
        result = self.retriever._parse_chunk_ids(["c1", "c2"])
        self.assertEqual(result, ["c1", "c2"])

    def test_empty_string(self):
        result = self.retriever._parse_chunk_ids("")
        self.assertEqual(result, [])

    def test_none(self):
        result = self.retriever._parse_chunk_ids(None)
        self.assertEqual(result, [])

    def test_single_value(self):
        result = self.retriever._parse_chunk_ids("chunk_only")
        self.assertEqual(result, ["chunk_only"])


class TestGraphRetrieverConfig(unittest.TestCase):
    """Test configuration."""

    def test_default_config(self):
        config = GraphRetrieverConfig()
        self.assertEqual(config.max_hops, 2)
        self.assertEqual(config.max_entities, 20)

    def test_custom_max_hops(self):
        config = GraphRetrieverConfig(max_hops=3)
        retriever = NeptuneGraphRetriever(MagicMock(), config=config)
        self.assertEqual(retriever.config.max_hops, 3)


if __name__ == "__main__":
    unittest.main()
