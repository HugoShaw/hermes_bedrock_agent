"""Tests for dry-run artifacts output."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from hermes_bedrock_agent.s3_graph_etl.embeddings.bedrock_embedder import MockEmbedder
from hermes_bedrock_agent.s3_graph_etl.graph_builder.builder import GraphBuilder
from hermes_bedrock_agent.s3_graph_etl.graph_builder.loader import GraphLoader
from hermes_bedrock_agent.s3_graph_etl.schemas import (
    ContentType,
    DetectedEntity,
    DetectedRelation,
    DocumentChunk,
    GraphNode,
    GraphEdge,
)


class TestMockEmbedder:
    def test_embed_returns_correct_dimension(self):
        embedder = MockEmbedder(dimension=256)
        result = embedder.embed("hello world")
        assert len(result) == 256
        assert all(isinstance(v, float) for v in result)

    def test_embed_deterministic(self):
        embedder = MockEmbedder(dimension=128)
        r1 = embedder.embed("test")
        r2 = embedder.embed("test")
        assert r1 == r2

    def test_embed_different_inputs_different_outputs(self):
        embedder = MockEmbedder(dimension=128)
        r1 = embedder.embed("hello")
        r2 = embedder.embed("world")
        assert r1 != r2

    def test_embed_batch(self):
        embedder = MockEmbedder(dimension=64)
        results = embedder.embed_batch(["a", "b", "c"])
        assert len(results) == 3
        assert all(len(r) == 64 for r in results)


class TestGraphBuilder:
    def test_build_empty_chunks(self):
        builder = GraphBuilder(skip_embedding=True)
        nodes, edges = builder.build([])
        assert nodes == []
        assert edges == []

    def test_build_creates_document_node(self):
        chunks = [DocumentChunk(
            id="chunk-1",
            source_uri="s3://bucket/test.txt",
            source_file="test.txt",
            text="Hello world",
            title="Introduction",
            confidence=1.0,
        )]
        builder = GraphBuilder(skip_embedding=True)
        nodes, edges = builder.build(chunks)

        # Should have at least a Document node
        doc_nodes = [n for n in nodes if n.label == "Document"]
        assert len(doc_nodes) >= 1
        assert doc_nodes[0].name == "test.txt"

    def test_build_with_entities(self):
        chunks = [DocumentChunk(
            id="chunk-1",
            source_uri="s3://bucket/schema.sql",
            source_file="schema.sql",
            text="CREATE TABLE payment",
            confidence=0.9,
            detected_entities=[
                DetectedEntity(name="payment", label="Table"),
                DetectedEntity(name="amount", label="Column"),
            ],
            detected_relations=[
                DetectedRelation(from_name="payment", to_name="amount", relation_type="CONTAINS"),
            ],
        )]
        builder = GraphBuilder(skip_embedding=True)
        nodes, edges = builder.build(chunks)

        # Should have entity nodes
        table_nodes = [n for n in nodes if n.label == "Table"]
        assert len(table_nodes) >= 1

    def test_build_with_mock_embedder(self):
        chunks = [DocumentChunk(
            id="chunk-1",
            source_uri="s3://bucket/test.txt",
            source_file="test.txt",
            text="Hello",
            confidence=1.0,
        )]
        embedder = MockEmbedder(dimension=64)
        builder = GraphBuilder(embedder=embedder, skip_embedding=False)
        nodes, edges = builder.build(chunks)

        # Check some nodes have embeddings
        nodes_with_embed = [n for n in nodes if n.embedding]
        assert len(nodes_with_embed) >= 1
        assert len(nodes_with_embed[0].embedding) == 64


class TestGraphLoader:
    def test_dry_run_writes_artifacts(self, tmp_path, monkeypatch):
        # Override artifacts dir
        monkeypatch.setattr(
            "hermes_bedrock_agent.s3_graph_etl.graph_builder.loader.ARTIFACTS_DIR",
            tmp_path / "artifacts",
        )
        loader = GraphLoader(dry_run=True)

        nodes = [GraphNode(id="n1", label="Table", name="payment", confidence=0.9)]
        edges = [GraphEdge(id="e1", from_id="n1", to_id="n2", type="CONTAINS", confidence=0.8)]

        result = loader.load(nodes, edges)
        assert result["mode"] == "dry_run"
        assert result["nodes_written"] == 1
        assert result["edges_written"] == 1

        # Check artifact files exist
        nodes_file = tmp_path / "artifacts" / "nodes.jsonl"
        edges_file = tmp_path / "artifacts" / "edges.jsonl"
        assert nodes_file.exists()
        assert edges_file.exists()

        # Parse the JSONL
        node_data = json.loads(nodes_file.read_text().strip())
        assert node_data["name"] == "payment"
        assert "embedding" not in node_data  # excluded from artifacts

        edge_data = json.loads(edges_file.read_text().strip())
        assert edge_data["type"] == "CONTAINS"
