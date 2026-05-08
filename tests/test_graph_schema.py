"""Tests for graph schema definitions."""
from __future__ import annotations

from hermes_bedrock_agent.s3_graph_etl.graph_builder.schema import (
    DEFAULT_EDGE_SCHEMAS,
    DEFAULT_NODE_SCHEMAS,
    VALID_NODE_LABELS,
    VALID_RELATION_TYPES,
)
from hermes_bedrock_agent.s3_graph_etl.schemas import RelationType


class TestGraphSchema:
    def test_node_schemas_not_empty(self):
        assert len(DEFAULT_NODE_SCHEMAS) >= 10

    def test_edge_schemas_not_empty(self):
        assert len(DEFAULT_EDGE_SCHEMAS) >= 11

    def test_valid_node_labels(self):
        assert "Document" in VALID_NODE_LABELS
        assert "Table" in VALID_NODE_LABELS
        assert "Column" in VALID_NODE_LABELS
        assert "API" in VALID_NODE_LABELS
        assert "Process" in VALID_NODE_LABELS

    def test_valid_relation_types(self):
        assert "CONTAINS" in VALID_RELATION_TYPES
        assert "REFERENCES" in VALID_RELATION_TYPES
        assert "USES_TABLE" in VALID_RELATION_TYPES
        assert "FLOWS_TO" in VALID_RELATION_TYPES

    def test_relation_types_match_enum(self):
        for rt in RelationType:
            assert rt.value in VALID_RELATION_TYPES

    def test_node_schemas_have_name_required(self):
        for schema in DEFAULT_NODE_SCHEMAS:
            assert "name" in schema.required_properties
