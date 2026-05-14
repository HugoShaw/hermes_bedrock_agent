"""Tests for API routes — query, graph, ingestion.

All tests use FastAPI TestClient with mock services.
No real OpenSearch/Neptune/Bedrock calls.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from hermes_bedrock_agent.main import app
from hermes_bedrock_agent.api.routes_graph import (
    GraphVisualizationService,
    set_graph_service,
)
from hermes_bedrock_agent.api.routes_query import (
    QueryService,
    set_query_service,
)
from hermes_bedrock_agent.schemas.retrieval import AnswerResult


class TestHealthEndpoint(unittest.TestCase):
    """Test the health check endpoint."""

    def setUp(self):
        self.client = TestClient(app)

    def test_health_returns_200(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)

    def test_health_status_healthy(self):
        response = self.client.get("/health")
        data = response.json()
        self.assertEqual(data["status"], "healthy")

    def test_health_has_version(self):
        response = self.client.get("/health")
        data = response.json()
        self.assertIn("version", data)

    def test_health_has_components(self):
        response = self.client.get("/health")
        data = response.json()
        self.assertIn("components", data)
        self.assertEqual(data["components"]["api"], "up")


class TestQueryEndpoint(unittest.TestCase):
    """Test POST /query endpoint."""

    def setUp(self):
        self.client = TestClient(app)
        # Reset service to default (no external deps)
        set_query_service(None)

    def test_query_returns_200(self):
        response = self.client.post("/query", json={"question": "テスト質問"})
        self.assertEqual(response.status_code, 200)

    def test_query_response_structure(self):
        response = self.client.post("/query", json={"question": "仕訳基礎とは"})
        data = response.json()
        self.assertIn("success", data)
        self.assertIn("data", data)

    def test_query_requires_question(self):
        response = self.client.post("/query", json={})
        self.assertEqual(response.status_code, 422)

    def test_query_empty_question_rejected(self):
        response = self.client.post("/query", json={"question": ""})
        self.assertEqual(response.status_code, 422)

    def test_query_with_strategy(self):
        response = self.client.post("/query", json={
            "question": "What is AP?",
            "strategy": "text",
        })
        self.assertEqual(response.status_code, 200)

    def test_query_with_mock_service(self):
        """QueryService with no retrievers returns fallback answer."""
        set_query_service(QueryService())
        response = self.client.post("/query", json={"question": "test"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])

    def test_query_does_not_call_real_services(self):
        """Without configured services, no external calls are made."""
        set_query_service(QueryService())
        response = self.client.post("/query", json={
            "question": "テスト",
            "top_k": 3,
            "graph_depth": 2,
        })
        self.assertEqual(response.status_code, 200)


class TestGraphSubgraphEndpoint(unittest.TestCase):
    """Test GET /graph/subgraph endpoint."""

    def setUp(self):
        self.client = TestClient(app)
        # Use default service (mock mode)
        set_graph_service(None)

    def test_subgraph_requires_center_entity(self):
        response = self.client.get("/graph/subgraph")
        self.assertEqual(response.status_code, 422)

    def test_subgraph_returns_200(self):
        response = self.client.get("/graph/subgraph?center_entity=ent_001")
        self.assertEqual(response.status_code, 200)

    def test_subgraph_response_has_nodes_edges(self):
        response = self.client.get("/graph/subgraph?center_entity=ent_001")
        data = response.json()
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertIn("node_count", data)

    def test_subgraph_max_nodes_param(self):
        response = self.client.get("/graph/subgraph?center_entity=ent_001&max_nodes=2")
        data = response.json()
        self.assertLessEqual(data["node_count"], 2)

    def test_subgraph_depth_param(self):
        response = self.client.get("/graph/subgraph?center_entity=ent_001&depth=3")
        data = response.json()
        self.assertEqual(data["depth"], 3)


class TestGraphMermaidEndpoint(unittest.TestCase):
    """Test GET /graph/mermaid endpoint."""

    def setUp(self):
        self.client = TestClient(app)
        set_graph_service(None)

    def test_mermaid_requires_center_entity(self):
        response = self.client.get("/graph/mermaid")
        self.assertEqual(response.status_code, 422)

    def test_mermaid_returns_200(self):
        response = self.client.get("/graph/mermaid?center_entity=ent_001")
        self.assertEqual(response.status_code, 200)

    def test_mermaid_response_has_code(self):
        response = self.client.get("/graph/mermaid?center_entity=ent_001")
        data = response.json()
        self.assertIn("mermaid_code", data)
        self.assertIn("flowchart", data["mermaid_code"])

    def test_mermaid_direction_param(self):
        response = self.client.get("/graph/mermaid?center_entity=ent_001&direction=TD")
        data = response.json()
        self.assertIn("TD", data["mermaid_code"])

    def test_mermaid_impact_type(self):
        response = self.client.get("/graph/mermaid?center_entity=ent_001&diagram_type=impact")
        data = response.json()
        self.assertIn("Impact", data["mermaid_code"])


class TestGraphReactFlowEndpoint(unittest.TestCase):
    """Test GET /graph/reactflow endpoint."""

    def setUp(self):
        self.client = TestClient(app)
        set_graph_service(None)

    def test_reactflow_requires_center_entity(self):
        response = self.client.get("/graph/reactflow")
        self.assertEqual(response.status_code, 422)

    def test_reactflow_returns_200(self):
        response = self.client.get("/graph/reactflow?center_entity=ent_001")
        self.assertEqual(response.status_code, 200)

    def test_reactflow_has_nodes_edges(self):
        response = self.client.get("/graph/reactflow?center_entity=ent_001")
        data = response.json()
        self.assertIn("nodes", data)
        self.assertIn("edges", data)

    def test_reactflow_nodes_have_positions(self):
        response = self.client.get("/graph/reactflow?center_entity=ent_001")
        data = response.json()
        if data["nodes"]:
            node = data["nodes"][0]
            self.assertIn("position", node)
            self.assertIn("x", node["position"])
            self.assertIn("y", node["position"])

    def test_reactflow_has_metadata(self):
        response = self.client.get("/graph/reactflow?center_entity=ent_001")
        data = response.json()
        self.assertIn("metadata", data)


class TestIngestionEndpoints(unittest.TestCase):
    """Test ingestion status and dry-run endpoints."""

    def setUp(self):
        self.client = TestClient(app)

    def test_status_returns_200(self):
        response = self.client.get("/ingestion/status")
        self.assertEqual(response.status_code, 200)

    def test_status_is_idle(self):
        response = self.client.get("/ingestion/status")
        data = response.json()
        self.assertEqual(data["status"], "idle")

    def test_dry_run_returns_200(self):
        response = self.client.post("/ingestion/dry-run", json={
            "s3_prefix": "murata/docs/",
            "file_types": ["pdf", "md"],
        })
        self.assertEqual(response.status_code, 200)

    def test_dry_run_response_structure(self):
        response = self.client.post("/ingestion/dry-run", json={})
        data = response.json()
        self.assertIn("success", data)
        self.assertIn("files_found", data)
        self.assertIn("message", data)


if __name__ == "__main__":
    unittest.main()
