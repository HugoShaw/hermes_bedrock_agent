"""Tests for visualization modules with i18n label support.

Phase 10B: Verifies that MermaidGenerator and ReactFlowExporter
correctly resolve multilingual labels based on lang and label_mode.
"""

from __future__ import annotations

import json

import pytest

from hermes_bedrock_agent.schemas.visualization import (
    LayoutAlgorithm,
    SubgraphResult,
    VisualizationEdge,
    VisualizationNode,
)
from hermes_bedrock_agent.visualization.mermaid_generator import (
    MermaidConfig,
    MermaidGenerator,
    resolve_i18n_label,
    _sanitize_id,
)
from hermes_bedrock_agent.visualization.reactflow_exporter import (
    ReactFlowConfig,
    ReactFlowExporter,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def i18n_data() -> dict[str, dict]:
    """Sample i18n data mapping entity_id → i18n fields."""
    return {
        "journal_base": {
            "display_name_zh": "记账基础表",
            "display_name_en": "Journal Base Table",
            "display_name_ja": "仕訳基礎テーブル",
        },
        "payment_req": {
            "display_name_zh": "付款申请表",
            "display_name_en": "Payment Request Table",
            "display_name_ja": "支払申請テーブル",
        },
        "muratapr": {
            "display_name_zh": "Murata PR系统",
            "display_name_en": "Murata PR System",
            "display_name_ja": "Murata PRシステム",
        },
    }


@pytest.fixture
def sample_subgraph() -> SubgraphResult:
    """Create a sample subgraph for testing."""
    nodes = [
        VisualizationNode(
            node_id="journal_base",
            label="JOURNAL_BASE",
            entity_type="table",
            description="Journal base table",
        ),
        VisualizationNode(
            node_id="payment_req",
            label="payment_req",
            entity_type="table",
            description="Payment request table",
        ),
        VisualizationNode(
            node_id="muratapr",
            label="muratapr",
            entity_type="system",
            description="Murata PR system",
        ),
    ]
    edges = [
        VisualizationEdge(
            edge_id="e1",
            source_id="journal_base",
            target_id="payment_req",
            relation_type="contains",
            label="contains",
        ),
        VisualizationEdge(
            edge_id="e2",
            source_id="muratapr",
            target_id="journal_base",
            relation_type="reads_from",
            label="reads_from",
        ),
    ]
    return SubgraphResult(
        nodes=nodes,
        edges=edges,
        query="test query",
        center_entity_id="journal_base",
        max_hops=2,
        layout_algorithm=LayoutAlgorithm.FORCE_DIRECTED,
    )


# ─── Tests: resolve_i18n_label function ──────────────────────────────────────


class TestResolveI18nLabel:
    """Test the resolve_i18n_label helper function."""

    def test_technical_mode_returns_original(self, i18n_data):
        """technical mode always returns the original label."""
        result = resolve_i18n_label(
            "journal_base", "JOURNAL_BASE",
            i18n_data=i18n_data,
            lang="ja",
            label_mode="technical",
        )
        assert result == "JOURNAL_BASE"

    def test_business_mode_returns_display_name_ja(self, i18n_data):
        """business mode with lang=ja returns display_name_ja."""
        result = resolve_i18n_label(
            "journal_base", "JOURNAL_BASE",
            i18n_data=i18n_data,
            lang="ja",
            label_mode="business",
        )
        assert result == "仕訳基礎テーブル"

    def test_business_mode_returns_display_name_zh(self, i18n_data):
        """business mode with lang=zh returns display_name_zh."""
        result = resolve_i18n_label(
            "payment_req", "payment_req",
            i18n_data=i18n_data,
            lang="zh",
            label_mode="business",
        )
        assert result == "付款申请表"

    def test_business_mode_returns_display_name_en(self, i18n_data):
        """business mode with lang=en returns display_name_en."""
        result = resolve_i18n_label(
            "muratapr", "muratapr",
            i18n_data=i18n_data,
            lang="en",
            label_mode="business",
        )
        assert result == "Murata PR System"

    def test_mixed_mode_returns_combined(self, i18n_data):
        """mixed mode returns display_name + canonical in parens."""
        result = resolve_i18n_label(
            "journal_base", "JOURNAL_BASE",
            i18n_data=i18n_data,
            lang="ja",
            label_mode="mixed",
        )
        assert "仕訳基礎テーブル" in result
        assert "JOURNAL_BASE" in result

    def test_mixed_mode_format(self, i18n_data):
        """mixed mode uses \\n(canonical) format."""
        result = resolve_i18n_label(
            "journal_base", "JOURNAL_BASE",
            i18n_data=i18n_data,
            lang="ja",
            label_mode="mixed",
        )
        assert result == "仕訳基礎テーブル\\n(JOURNAL_BASE)"

    def test_business_mode_fallback_when_empty(self, i18n_data):
        """business mode falls back to original label when display_name is empty."""
        # Add an entity with empty display_name
        i18n_data["unknown_entity"] = {
            "display_name_zh": "",
            "display_name_en": "",
            "display_name_ja": "",
        }
        result = resolve_i18n_label(
            "unknown_entity", "UNKNOWN_ENTITY",
            i18n_data=i18n_data,
            lang="ja",
            label_mode="business",
        )
        assert result == "UNKNOWN_ENTITY"

    def test_no_i18n_data_returns_original(self):
        """Without i18n_data, always returns original label."""
        result = resolve_i18n_label(
            "journal_base", "JOURNAL_BASE",
            i18n_data=None,
            lang="ja",
            label_mode="business",
        )
        assert result == "JOURNAL_BASE"

    def test_entity_not_in_i18n_data_returns_original(self, i18n_data):
        """Entity missing from i18n_data falls back to original label."""
        result = resolve_i18n_label(
            "nonexistent_entity", "NONEXISTENT",
            i18n_data=i18n_data,
            lang="ja",
            label_mode="business",
        )
        assert result == "NONEXISTENT"

    def test_mixed_mode_same_display_and_label(self, i18n_data):
        """mixed mode with identical display_name and label just shows label."""
        i18n_data["same_label"] = {"display_name_en": "same_label"}
        result = resolve_i18n_label(
            "same_label", "same_label",
            i18n_data=i18n_data,
            lang="en",
            label_mode="mixed",
        )
        assert result == "same_label"


# ─── Tests: MermaidGenerator i18n ─────────────────────────────────────────────


class TestMermaidGeneratorI18n:
    """Test MermaidGenerator with i18n label resolution."""

    def test_technical_mode_default(self, sample_subgraph):
        """Default technical mode uses canonical names."""
        gen = MermaidGenerator(MermaidConfig(lang="en", label_mode="technical"))
        result = gen.generate_flowchart(sample_subgraph)
        assert "JOURNAL_BASE" in result
        assert "payment_req" in result

    def test_business_mode_ja(self, sample_subgraph, i18n_data):
        """Business mode with ja shows Japanese labels."""
        gen = MermaidGenerator(MermaidConfig(lang="ja", label_mode="business"))
        result = gen.generate_flowchart(
            sample_subgraph,
            i18n_data=i18n_data,
        )
        assert "仕訳基礎テーブル" in result
        assert "支払申請テーブル" in result

    def test_business_mode_zh(self, sample_subgraph, i18n_data):
        """Business mode with zh shows Chinese labels."""
        gen = MermaidGenerator(MermaidConfig(lang="zh", label_mode="business"))
        result = gen.generate_flowchart(
            sample_subgraph,
            i18n_data=i18n_data,
        )
        assert "记账基础表" in result
        assert "付款申请表" in result

    def test_mixed_mode_ja(self, sample_subgraph, i18n_data):
        """Mixed mode shows Japanese name + canonical."""
        gen = MermaidGenerator(MermaidConfig(lang="ja", label_mode="mixed"))
        result = gen.generate_flowchart(
            sample_subgraph,
            i18n_data=i18n_data,
        )
        assert "仕訳基礎テーブル" in result
        assert "JOURNAL_BASE" in result

    def test_node_id_stays_ascii_safe(self, sample_subgraph, i18n_data):
        """Mermaid node IDs must remain ASCII-safe even with i18n labels."""
        gen = MermaidGenerator(MermaidConfig(lang="ja", label_mode="business"))
        result = gen.generate_flowchart(
            sample_subgraph,
            i18n_data=i18n_data,
        )
        # Node IDs in Mermaid syntax are the parts before the shape brackets
        # They should not contain CJK characters
        lines = result.split("\n")
        for line in lines:
            if line.strip().startswith("flowchart") or not line.strip():
                continue
            # Node definition lines have format: sid["label"]
            # Edge lines have format: sid --> sid
            # Neither should have CJK in the ID portion
            parts = line.strip().split("[")
            if len(parts) > 1:
                node_id_part = parts[0].strip()
                # node ID should be ASCII
                assert all(
                    ord(c) < 128 for c in node_id_part
                ), f"Non-ASCII in node ID: {node_id_part}"

    def test_edge_labels_i18n_zh(self, sample_subgraph, i18n_data):
        """Edge labels resolve to Chinese when lang=zh and label_mode=business."""
        gen = MermaidGenerator(MermaidConfig(
            lang="zh",
            label_mode="business",
            show_edge_labels=True,
        ))
        result = gen.generate_flowchart(
            sample_subgraph,
            i18n_data=i18n_data,
        )
        # "contains" → "包含", "reads_from" → "读取"
        assert "包含" in result or "读取" in result

    def test_edge_labels_technical_mode_unchanged(self, sample_subgraph, i18n_data):
        """In technical mode, edge labels stay as original."""
        gen = MermaidGenerator(MermaidConfig(
            lang="zh",
            label_mode="technical",
            show_edge_labels=True,
        ))
        result = gen.generate_flowchart(
            sample_subgraph,
            i18n_data=i18n_data,
        )
        assert "contains" in result

    def test_override_lang_in_generate(self, sample_subgraph, i18n_data):
        """Can override lang per call."""
        gen = MermaidGenerator(MermaidConfig(lang="en", label_mode="business"))
        result = gen.generate_flowchart(
            sample_subgraph,
            i18n_data=i18n_data,
            lang="ja",
        )
        assert "仕訳基礎テーブル" in result

    def test_no_i18n_data_renders_normally(self, sample_subgraph):
        """Without i18n_data, business mode still shows original labels."""
        gen = MermaidGenerator(MermaidConfig(lang="ja", label_mode="business"))
        result = gen.generate_flowchart(sample_subgraph)
        assert "JOURNAL_BASE" in result


# ─── Tests: ReactFlowExporter i18n ───────────────────────────────────────────


class TestReactFlowExporterI18n:
    """Test ReactFlowExporter with i18n label resolution."""

    def test_technical_mode_default(self, sample_subgraph):
        """Default technical mode returns canonical labels."""
        exporter = ReactFlowExporter(ReactFlowConfig(
            lang="en", label_mode="technical"
        ))
        result = exporter.export(sample_subgraph)
        labels = [n["data"]["label"] for n in result["nodes"]]
        assert "JOURNAL_BASE" in labels
        assert "payment_req" in labels

    def test_business_mode_ja(self, sample_subgraph, i18n_data):
        """Business mode with ja returns Japanese labels."""
        exporter = ReactFlowExporter(ReactFlowConfig(
            lang="ja", label_mode="business"
        ))
        result = exporter.export(sample_subgraph, i18n_data=i18n_data)
        labels = [n["data"]["label"] for n in result["nodes"]]
        assert "仕訳基礎テーブル" in labels
        assert "支払申請テーブル" in labels

    def test_business_mode_zh(self, sample_subgraph, i18n_data):
        """Business mode with zh returns Chinese labels."""
        exporter = ReactFlowExporter(ReactFlowConfig(
            lang="zh", label_mode="business"
        ))
        result = exporter.export(sample_subgraph, i18n_data=i18n_data)
        labels = [n["data"]["label"] for n in result["nodes"]]
        assert "记账基础表" in labels
        assert "付款申请表" in labels

    def test_mixed_mode_ja(self, sample_subgraph, i18n_data):
        """Mixed mode contains both Japanese and canonical names."""
        exporter = ReactFlowExporter(ReactFlowConfig(
            lang="ja", label_mode="mixed"
        ))
        result = exporter.export(sample_subgraph, i18n_data=i18n_data)
        labels = [n["data"]["label"] for n in result["nodes"]]
        # At least one label should contain Japanese AND canonical
        found_mixed = any(
            "仕訳基礎テーブル" in lbl and "JOURNAL_BASE" in lbl
            for lbl in labels
        )
        assert found_mixed

    def test_edge_label_i18n_zh(self, sample_subgraph, i18n_data):
        """Edge labels resolve to Chinese in business mode."""
        exporter = ReactFlowExporter(ReactFlowConfig(
            lang="zh", label_mode="business"
        ))
        result = exporter.export(sample_subgraph, i18n_data=i18n_data)
        edge_labels = [e.get("label", "") for e in result["edges"]]
        # "contains" → "包含"
        assert "包含" in edge_labels or "读取" in edge_labels

    def test_node_ids_preserved(self, sample_subgraph, i18n_data):
        """Node IDs remain the original entity_id regardless of label."""
        exporter = ReactFlowExporter(ReactFlowConfig(
            lang="ja", label_mode="business"
        ))
        result = exporter.export(sample_subgraph, i18n_data=i18n_data)
        node_ids = [n["id"] for n in result["nodes"]]
        assert "journal_base" in node_ids
        assert "payment_req" in node_ids
        assert "muratapr" in node_ids

    def test_export_json_i18n(self, sample_subgraph, i18n_data):
        """export_json passes i18n params through."""
        exporter = ReactFlowExporter(ReactFlowConfig(
            lang="ja", label_mode="business"
        ))
        json_str = exporter.export_json(
            sample_subgraph,
            i18n_data=i18n_data,
        )
        data = json.loads(json_str)
        labels = [n["data"]["label"] for n in data["nodes"]]
        assert "仕訳基礎テーブル" in labels

    def test_no_i18n_data_renders_normally(self, sample_subgraph):
        """Without i18n_data, returns original labels."""
        exporter = ReactFlowExporter(ReactFlowConfig(
            lang="ja", label_mode="business"
        ))
        result = exporter.export(sample_subgraph)
        labels = [n["data"]["label"] for n in result["nodes"]]
        assert "JOURNAL_BASE" in labels


# ─── Tests: Safety ────────────────────────────────────────────────────────────


class TestSafety:
    """Test that i18n visualization doesn't break with edge cases."""

    def test_empty_subgraph(self, i18n_data):
        """Empty subgraph doesn't crash."""
        subgraph = SubgraphResult(
            nodes=[],
            edges=[],
            query="empty",
            layout_algorithm=LayoutAlgorithm.FORCE_DIRECTED,
        )
        gen = MermaidGenerator(MermaidConfig(lang="ja", label_mode="business"))
        result = gen.generate_flowchart(subgraph, i18n_data=i18n_data)
        assert "flowchart" in result

    def test_sanitize_id_cjk(self):
        """CJK node IDs get sanitized to ASCII."""
        result = _sanitize_id("仕訳基礎テーブル")
        assert all(ord(c) < 128 for c in result)
        assert len(result) > 0

    def test_sanitize_id_ascii(self):
        """ASCII IDs pass through."""
        result = _sanitize_id("journal_base")
        assert result == "journal_base"

    def test_sanitize_id_empty(self):
        """Empty ID gets fallback."""
        result = _sanitize_id("")
        assert result == "node_00000000"

    def test_mermaid_label_with_cjk(self, i18n_data):
        """Mermaid can contain CJK in labels (not IDs)."""
        node = VisualizationNode(
            node_id="journal_base",
            label="JOURNAL_BASE",
            entity_type="table",
        )
        subgraph = SubgraphResult(
            nodes=[node],
            edges=[],
            query="test",
            layout_algorithm=LayoutAlgorithm.FORCE_DIRECTED,
        )
        gen = MermaidGenerator(MermaidConfig(lang="ja", label_mode="business"))
        result = gen.generate_flowchart(subgraph, i18n_data=i18n_data)
        # Label contains CJK but node ID is ASCII
        assert "仕訳基礎テーブル" in result
        # The node ID line should have ASCII ID
        for line in result.split("\n"):
            if "仕訳基礎テーブル" in line:
                # Extract the ID part (before the shape bracket)
                id_part = line.strip().split("[")[0].strip().split("(")[0].strip()
                assert all(ord(c) < 128 for c in id_part)
