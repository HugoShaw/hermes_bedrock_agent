"""Tests for Mermaid renderer."""

import pytest
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

from flowchart_to_mermaid.graph.models import (
    FlowDocument, FlowEdge, FlowGroup, FlowNode, NodeType, PageFlow,
)
from flowchart_to_mermaid.renderers.mermaid_renderer import MermaidRenderer


@pytest.fixture
def sample_doc():
    """Create a sample FlowDocument for testing."""
    return FlowDocument(
        source_file="test.pdf",
        source_type="pdf",
        pages=[
            PageFlow(
                page_index=0,
                width=2000,
                height=1000,
                nodes=[
                    FlowNode(id="N001", label="開始", type=NodeType.TERMINATOR),
                    FlowNode(id="N002", label="処理A", type=NodeType.PROCESS),
                    FlowNode(id="N003", label="条件分岐", type=NodeType.DECISION),
                    FlowNode(id="N004", label="POST：登録API", type=NodeType.API),
                    FlowNode(id="N005", label="終了", type=NodeType.TERMINATOR),
                ],
                edges=[
                    FlowEdge(id="E001", source="N001", target="N002"),
                    FlowEdge(id="E002", source="N002", target="N003"),
                    FlowEdge(id="E003", source="N003", target="N004", label="Yes"),
                    FlowEdge(id="E004", source="N003", target="N005", label="No",
                            uncertain=True, confidence=0.5),
                    FlowEdge(id="E005", source="N004", target="N005",
                            inferred=True, confidence=0.6),
                ],
                groups=[
                    FlowGroup(
                        id="G001",
                        label="機能No6：発注処理",
                        node_ids=["N003", "N004"],
                    ),
                ],
            )
        ],
        direction="TD",
    )


def test_renderer_generates_nodes(sample_doc):
    """Test that renderer generates node definitions."""
    renderer = MermaidRenderer()
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.mmd"
        content = renderer.render(sample_doc, output)

        assert "N001" in content
        assert "N002" in content
        assert "開始" in content
        assert "処理A" in content


def test_renderer_generates_edges(sample_doc):
    """Test that renderer generates edge connections."""
    renderer = MermaidRenderer()
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.mmd"
        content = renderer.render(sample_doc, output)

        assert "N001" in content
        assert "N002" in content
        # Check arrow syntax
        assert "-->" in content or "-.->" in content


def test_renderer_generates_subgraph(sample_doc):
    """Test that renderer generates subgraph for groups."""
    renderer = MermaidRenderer()
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.mmd"
        content = renderer.render(sample_doc, output)

        assert "subgraph G001" in content
        assert "機能No6" in content
        assert "end" in content


def test_renderer_handles_uncertain_edge(sample_doc):
    """Test that uncertain edges use dashed arrows."""
    renderer = MermaidRenderer()
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.mmd"
        content = renderer.render(sample_doc, output)

        assert "uncertain" in content or "-.->" in content


def test_renderer_no_duplicate_ids(sample_doc):
    """Test that node IDs are not duplicated in output."""
    renderer = MermaidRenderer()
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.mmd"
        content = renderer.render(sample_doc, output)

        # Each node should appear exactly in its definition (once)
        lines = content.split("\n")
        node_defs = [l for l in lines if l.strip().startswith("N001[") or l.strip().startswith("N001(")]
        # N001 should be defined once (in subgraph or standalone)
        assert len([l for l in lines if "N001([" in l]) <= 1


def test_renderer_classdef(sample_doc):
    """Test that classDef styles are generated."""
    renderer = MermaidRenderer()
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.mmd"
        content = renderer.render(sample_doc, output)

        assert "classDef api" in content
        assert "classDef decision" in content
        assert "classDef terminator" in content


def test_renderer_direction():
    """Test that flow direction is correctly set."""
    doc = FlowDocument(
        source_file="test.pdf",
        pages=[PageFlow(page_index=0, width=100, height=100)],
        direction="LR",
    )
    renderer = MermaidRenderer()
    with TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "test.mmd"
        content = renderer.render(doc, output)
        assert "flowchart LR" in content
