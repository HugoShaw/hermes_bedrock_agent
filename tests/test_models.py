"""Tests for Pydantic models."""

import json
import pytest

from flowchart_to_mermaid.graph.models import (
    FlowDocument, FlowEdge, FlowGroup, FlowNode, NodeType,
    PageFlow, Shape, ShapeType, TextBlock, TextSource,
    UncertainPoint, UncertaintyType,
)


def test_text_block_serialization():
    """Test TextBlock can serialize to JSON."""
    tb = TextBlock(
        id="txt_001",
        text="開始",
        bbox=[10.0, 20.0, 100.0, 50.0],
        confidence=0.95,
        source=TextSource.PDF_TEXT,
    )
    data = tb.model_dump(mode="json")
    assert data["id"] == "txt_001"
    assert data["text"] == "開始"
    assert data["bbox"] == [10.0, 20.0, 100.0, 50.0]
    assert data["source"] == "pdf_text"

    # Round-trip
    tb2 = TextBlock.model_validate(data)
    assert tb2.text == "開始"


def test_flow_node_serialization():
    """Test FlowNode serialization."""
    node = FlowNode(
        id="N001",
        label="伝票データファイルを読取",
        type=NodeType.FILE,
        bbox=[100, 200, 300, 250],
        confidence=0.9,
    )
    data = node.model_dump(mode="json")
    assert data["type"] == "file"
    assert data["label"] == "伝票データファイルを読取"


def test_flow_edge_serialization():
    """Test FlowEdge serialization."""
    edge = FlowEdge(
        id="E001",
        source="N001",
        target="N002",
        label="1（登録）の場合",
        confidence=0.8,
        inferred=True,
    )
    data = edge.model_dump(mode="json")
    assert data["source"] == "N001"
    assert data["target"] == "N002"
    assert data["inferred"] is True


def test_flow_group_serialization():
    """Test FlowGroup serialization."""
    group = FlowGroup(
        id="G001",
        label="機能No6：発注処理",
        bbox=[100, 100, 500, 400],
        node_ids=["N010", "N011", "N012"],
    )
    data = group.model_dump(mode="json")
    assert data["node_ids"] == ["N010", "N011", "N012"]


def test_full_document_serialization():
    """Test complete FlowDocument can be serialized to JSON."""
    doc = FlowDocument(
        source_file="test.pdf",
        source_type="pdf",
        pages=[
            PageFlow(
                page_index=0,
                width=2000,
                height=1000,
                text_blocks=[
                    TextBlock(id="txt_001", text="開始", bbox=[10, 10, 50, 30]),
                ],
                nodes=[
                    FlowNode(id="N001", label="開始", type=NodeType.TERMINATOR),
                    FlowNode(id="N002", label="処理A", type=NodeType.PROCESS),
                ],
                edges=[
                    FlowEdge(id="E001", source="N001", target="N002"),
                ],
                groups=[],
                uncertain_points=[
                    UncertainPoint(
                        type=UncertaintyType.EDGE,
                        message="Direction unclear",
                        related_ids=["N001", "N002"],
                    ),
                ],
            )
        ],
        direction="TD",
    )

    json_str = json.dumps(doc.model_dump(mode="json"), ensure_ascii=False)
    assert "開始" in json_str
    assert "N001" in json_str

    # Can deserialize back
    doc2 = FlowDocument.model_validate(json.loads(json_str))
    assert len(doc2.pages) == 1
    assert len(doc2.pages[0].nodes) == 2
