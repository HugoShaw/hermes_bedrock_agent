"""Tests for graph validator."""

import pytest

from flowchart_to_mermaid.graph.models import (
    FlowDocument, FlowEdge, FlowNode, NodeType, PageFlow,
)
from flowchart_to_mermaid.graph.graph_validator import GraphValidator


@pytest.fixture
def valid_doc():
    """Create a valid FlowDocument with start and end."""
    return FlowDocument(
        source_file="test.pdf",
        pages=[
            PageFlow(
                page_index=0,
                width=1000,
                height=1000,
                nodes=[
                    FlowNode(id="N001", label="開始", type=NodeType.TERMINATOR),
                    FlowNode(id="N002", label="処理", type=NodeType.PROCESS),
                    FlowNode(id="N003", label="終了", type=NodeType.TERMINATOR),
                ],
                edges=[
                    FlowEdge(id="E001", source="N001", target="N002"),
                    FlowEdge(id="E002", source="N002", target="N003"),
                ],
            )
        ],
    )


def test_validator_finds_start_end(valid_doc):
    """Test that validator correctly counts start/end nodes."""
    validator = GraphValidator()
    result = validator.validate(valid_doc)
    assert result["start_nodes"] == 1
    assert result["end_nodes"] == 1


def test_validator_counts_nodes_edges(valid_doc):
    """Test node and edge counting."""
    validator = GraphValidator()
    result = validator.validate(valid_doc)
    assert result["total_nodes"] == 3
    assert result["total_edges"] == 2


def test_validator_detects_invalid_edges():
    """Test detection of edges referencing non-existent nodes."""
    doc = FlowDocument(
        source_file="test.pdf",
        pages=[
            PageFlow(
                page_index=0,
                nodes=[
                    FlowNode(id="N001", label="開始", type=NodeType.TERMINATOR),
                ],
                edges=[
                    FlowEdge(id="E001", source="N001", target="N999"),  # N999 doesn't exist
                ],
            )
        ],
    )
    validator = GraphValidator()
    result = validator.validate(doc)
    assert len(result["invalid_edges"]) > 0


def test_validator_detects_orphan_nodes():
    """Test detection of orphan (disconnected) nodes."""
    doc = FlowDocument(
        source_file="test.pdf",
        pages=[
            PageFlow(
                page_index=0,
                nodes=[
                    FlowNode(id="N001", label="開始", type=NodeType.TERMINATOR),
                    FlowNode(id="N002", label="孤立", type=NodeType.PROCESS),
                    FlowNode(id="N003", label="終了", type=NodeType.TERMINATOR),
                ],
                edges=[
                    FlowEdge(id="E001", source="N001", target="N003"),
                    # N002 is not connected to anything
                ],
            )
        ],
    )
    validator = GraphValidator()
    result = validator.validate(doc)
    assert result["orphan_nodes"] >= 1


def test_validator_detects_missing_start():
    """Test warning when no start node exists."""
    doc = FlowDocument(
        source_file="test.pdf",
        pages=[
            PageFlow(
                page_index=0,
                nodes=[
                    FlowNode(id="N001", label="処理A", type=NodeType.PROCESS),
                ],
                edges=[],
            )
        ],
    )
    validator = GraphValidator()
    result = validator.validate(doc)
    assert result["start_nodes"] == 0
    assert any("No start node" in i for i in result["issues"])


def test_validator_function_coverage():
    """Test function number coverage checking."""
    doc = FlowDocument(
        source_file="test.pdf",
        pages=[
            PageFlow(
                page_index=0,
                nodes=[
                    FlowNode(id="N001", label="機能No1：トークン取得", type=NodeType.PROCESS),
                    FlowNode(id="N002", label="機能No6：発注処理", type=NodeType.PROCESS),
                ],
                edges=[],
            )
        ],
    )
    validator = GraphValidator()
    result = validator.validate(doc)
    assert result["function_coverage"]["機能No1"] is True
    assert result["function_coverage"]["機能No6"] is True
    assert result["function_coverage"]["機能No2"] is False


def test_validator_inferred_edge_count():
    """Test counting of inferred edges."""
    doc = FlowDocument(
        source_file="test.pdf",
        pages=[
            PageFlow(
                page_index=0,
                nodes=[
                    FlowNode(id="N001", label="A", type=NodeType.PROCESS),
                    FlowNode(id="N002", label="B", type=NodeType.PROCESS),
                ],
                edges=[
                    FlowEdge(id="E001", source="N001", target="N002", inferred=True),
                ],
            )
        ],
    )
    validator = GraphValidator()
    result = validator.validate(doc)
    assert result["inferred_edges"] == 1
