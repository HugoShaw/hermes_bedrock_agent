"""Tests for s3_graph_etl schemas (DocumentChunk, GraphNode, GraphEdge)."""
from __future__ import annotations

import pytest

from hermes_bedrock_agent.s3_graph_etl.schemas import (
    ContentType,
    DetectedEntity,
    DetectedRelation,
    DocumentChunk,
    FileRecord,
    GraphEdge,
    GraphNode,
    ParserType,
    RelationType,
)


class TestDocumentChunk:
    def test_create_minimal(self):
        chunk = DocumentChunk(
            id="chunk-001",
            source_uri="s3://bucket/file.txt",
            source_file="file.txt",
        )
        assert chunk.id == "chunk-001"
        assert chunk.content_type == ContentType.TEXT
        assert chunk.parser_type == ParserType.PYTHON_PARSER
        assert chunk.confidence == 0.0
        assert chunk.needs_review is False

    def test_create_full(self):
        chunk = DocumentChunk(
            id="chunk-002",
            source_uri="s3://bucket/doc.pdf",
            source_file="doc.pdf",
            page_number=3,
            chunk_index=1,
            content_type=ContentType.TABLE,
            title="Payment Table",
            heading_path=["Chapter 1", "Section 1.1"],
            text="CREATE TABLE payment...",
            structured_content={"columns": ["id", "amount"]},
            visual_description="",
            detected_entities=[DetectedEntity(name="payment", label="Table")],
            detected_relations=[DetectedRelation(from_name="payment", to_name="user", relation_type="REFERENCES")],
            evidence_text="Found in section 1.1",
            confidence=0.95,
            parser_type=ParserType.LLM_VISION_PARSER,
            needs_review=True,
        )
        assert chunk.page_number == 3
        assert len(chunk.detected_entities) == 1
        assert chunk.detected_entities[0].name == "payment"
        assert len(chunk.detected_relations) == 1
        assert chunk.confidence == 0.95

    def test_content_type_enum(self):
        assert ContentType.TEXT == "text"
        assert ContentType.TABLE == "table"
        assert ContentType.IMAGE == "image"
        assert ContentType.DIAGRAM == "diagram"
        assert ContentType.CODE == "code"
        assert ContentType.DDL == "ddl"

    def test_parser_type_enum(self):
        assert ParserType.PYTHON_PARSER == "python_parser"
        assert ParserType.LLM_TEXT_PARSER == "llm_text_parser"
        assert ParserType.LLM_VISION_PARSER == "llm_vision_parser"


class TestGraphNode:
    def test_create_minimal(self):
        node = GraphNode(id="table:payment", label="Table", name="payment")
        assert node.id == "table:payment"
        assert node.label == "Table"
        assert node.name == "payment"
        assert node.embedding == []
        assert node.properties == {}

    def test_create_with_embedding(self):
        embedding = [0.1, 0.2, 0.3]
        node = GraphNode(
            id="table:payment",
            label="Table",
            name="payment",
            text="Payment table for AP system",
            source_uri="s3://bucket/schema.sql",
            source_file="schema.sql",
            evidence_text="CREATE TABLE payment",
            confidence=0.9,
            embedding=embedding,
            properties={"schema": "public"},
        )
        assert node.embedding == [0.1, 0.2, 0.3]
        assert node.properties == {"schema": "public"}

    def test_model_dump(self):
        node = GraphNode(id="n1", label="Entity", name="test")
        data = node.model_dump()
        assert "id" in data
        assert "label" in data
        assert "name" in data
        assert "embedding" in data


class TestGraphEdge:
    def test_create_minimal(self):
        edge = GraphEdge(
            id="rel:a->b",
            from_id="table:payment",
            to_id="column:amount",
            type="CONTAINS",
        )
        assert edge.from_id == "table:payment"
        assert edge.to_id == "column:amount"
        assert edge.type == "CONTAINS"

    def test_create_full(self):
        edge = GraphEdge(
            id="rel:a->b",
            from_id="process:ap",
            to_id="table:payment",
            type=RelationType.USES_TABLE,
            evidence_text="AP process writes to payment table",
            confidence=0.85,
            source_uri="s3://bucket/design.pdf",
            properties={"verified": "true"},
        )
        assert edge.type == "USES_TABLE"
        assert edge.confidence == 0.85


class TestRelationType:
    def test_all_types_exist(self):
        assert RelationType.CONTAINS == "CONTAINS"
        assert RelationType.REFERENCES == "REFERENCES"
        assert RelationType.USES_TABLE == "USES_TABLE"
        assert RelationType.USES_COLUMN == "USES_COLUMN"
        assert RelationType.CALLS_API == "CALLS_API"
        assert RelationType.IMPLEMENTS_PROCESS == "IMPLEMENTS_PROCESS"
        assert RelationType.DESCRIBES_RULE == "DESCRIBES_RULE"
        assert RelationType.DEPENDS_ON == "DEPENDS_ON"
        assert RelationType.SAME_AS == "SAME_AS"
        assert RelationType.RELATED_TO == "RELATED_TO"
        assert RelationType.FLOWS_TO == "FLOWS_TO"


class TestFileRecord:
    def test_create(self):
        record = FileRecord(
            uri="s3://bucket/file.pdf",
            bucket="bucket",
            key="file.pdf",
            size=1024,
            etag="abc123",
        )
        assert record.status == "pending"
        assert record.chunk_count == 0
