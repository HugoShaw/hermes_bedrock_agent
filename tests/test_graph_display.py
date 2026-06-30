"""Tests for graph_display.py — readable formatting and export."""
import pytest

from hermes_bedrock_agent.qa.graph_display import (
    GRAPH_FORMATS,
    format_graph,
    format_graph_compact,
    format_graph_table,
    format_graph_network,
    format_graph_raw,
    export_graph_mermaid,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

SAMPLE_NODES = [
    {"id": "n1", "label": "DataField", "properties": {"name": "顧客コード", "sheet_name": "Sheet_1"}},
    {"id": "n2", "label": "API", "properties": {"name": "GetCustomer", "sheet_name": "Sheet_2"}},
    {"id": "n3", "label": "Process", "properties": {"name": "支払処理フロー"}},
]

SAMPLE_EDGES = [
    {"from": "n1", "to": "n2", "relationship": "CALLS_API"},
    {"from": "n2", "to": "n3", "relationship": "NEXT_STEP"},
    {"from": "n1", "to": "n3", "relationship": "HAS_PARAMETER"},
]


class TestGraphFormats:
    """Test each display format produces valid output."""

    def test_graph_formats_tuple(self):
        assert "compact" in GRAPH_FORMATS
        assert "table" in GRAPH_FORMATS
        assert "network" in GRAPH_FORMATS
        assert "raw" in GRAPH_FORMATS

    def test_format_graph_compact(self):
        lines = format_graph_compact(SAMPLE_NODES, SAMPLE_EDGES)
        text = "\n".join(lines)
        # Should show readable names, not raw IDs
        assert "顧客コード" in text
        assert "GetCustomer" in text
        assert "支払処理フロー" in text
        # Should show relationships
        assert "CALLS_API" in text or "Calls Api" in text

    def test_format_graph_compact_show_raw(self):
        lines = format_graph_compact(SAMPLE_NODES, SAMPLE_EDGES, show_raw_ids=True)
        text = "\n".join(lines)
        # Should show node IDs
        assert "n1" in text
        assert "n2" in text

    def test_format_graph_table(self):
        lines = format_graph_table(SAMPLE_NODES, SAMPLE_EDGES)
        text = "\n".join(lines)
        assert "顧客コード" in text
        # Table should have separator lines
        assert "─" in text or "━" in text or "|" in text or "│" in text

    def test_format_graph_network(self):
        lines = format_graph_network(SAMPLE_NODES, SAMPLE_EDGES)
        text = "\n".join(lines)
        # Network/tree shows "from" → "to" style
        assert "→" in text or "-->" in text or "├" in text or "└" in text

    def test_format_graph_raw(self):
        lines = format_graph_raw(SAMPLE_NODES, SAMPLE_EDGES)
        text = "\n".join(lines)
        # Raw should always show IDs
        assert "n1" in text
        assert "n2" in text
        assert "n3" in text

    def test_format_graph_dispatcher(self):
        """format_graph() dispatches to the correct function."""
        for fmt in GRAPH_FORMATS:
            lines = format_graph(SAMPLE_NODES, SAMPLE_EDGES, fmt=fmt)
            assert isinstance(lines, list)
            assert len(lines) > 0

    def test_format_graph_invalid_format_falls_back(self):
        lines = format_graph(SAMPLE_NODES, SAMPLE_EDGES, fmt="nonexistent")
        # Should fall back to compact
        assert len(lines) > 0

    def test_empty_nodes_edges(self):
        """No crash on empty data."""
        for fmt in GRAPH_FORMATS:
            lines = format_graph([], [], fmt=fmt)
            assert isinstance(lines, list)


class TestMermaidExport:
    """Test Mermaid .mmd export."""

    def test_export_basic(self):
        mmd = export_graph_mermaid(SAMPLE_NODES, SAMPLE_EDGES)
        assert mmd.startswith("flowchart")
        assert "顧客コード" in mmd or "n1" in mmd
        assert "-->" in mmd

    def test_export_empty(self):
        mmd = export_graph_mermaid([], [])
        assert "flowchart" in mmd

    def test_export_special_chars_escaped(self):
        """Mermaid node labels with special chars should not break syntax."""
        nodes = [{"id": "x1", "label": "API", "properties": {"name": 'Foo"Bar'}}]
        edges = []
        mmd = export_graph_mermaid(nodes, edges)
        # Should not have unescaped quotes that break mermaid
        assert "Foo" in mmd


class TestProjectMapping:
    """Test centralized project mapping module."""

    def test_known_project(self):
        from hermes_bedrock_agent.retrieval.project_mapping import to_neptune_project_alias
        assert to_neptune_project_alias("sample_20260519") == "サンプル20260519"
        assert to_neptune_project_alias("saimu_bugyo_cloud") == "14_債務奉行クラウド"

    def test_unknown_project_passthrough(self):
        from hermes_bedrock_agent.retrieval.project_mapping import to_neptune_project_alias
        assert to_neptune_project_alias("unknown_project") == "unknown_project"

    def test_empty_project(self):
        from hermes_bedrock_agent.retrieval.project_mapping import to_neptune_project_alias
        assert to_neptune_project_alias("") == ""

    def test_reverse_lookup(self):
        from hermes_bedrock_agent.retrieval.project_mapping import to_lancedb_project_id
        assert to_lancedb_project_id("サンプル20260519") == "sample_20260519"
        assert to_lancedb_project_id("14_債務奉行クラウド") == "saimu_bugyo_cloud"


class TestSafeStr:
    """Test centralized _safe_str utility."""

    def test_none(self):
        from hermes_bedrock_agent.retrieval._utils import _safe_str
        assert _safe_str(None) == ""

    def test_nan(self):
        from hermes_bedrock_agent.retrieval._utils import _safe_str
        assert _safe_str(float("nan")) == ""

    def test_normal_string(self):
        from hermes_bedrock_agent.retrieval._utils import _safe_str
        assert _safe_str("hello") == "hello"

    def test_float_value(self):
        from hermes_bedrock_agent.retrieval._utils import _safe_str
        assert _safe_str(42.5) == "42.5"

    def test_nan_string(self):
        from hermes_bedrock_agent.retrieval._utils import _safe_str
        assert _safe_str("nan") == ""
        assert _safe_str("None") == ""
        assert _safe_str("null") == ""


class TestKeywordScanLimit:
    """Test keyword retriever truncation detection."""

    def test_constant_exported(self):
        from hermes_bedrock_agent.retrieval.keyword_retriever import KEYWORD_SCAN_LIMIT
        assert KEYWORD_SCAN_LIMIT == 2000

    def test_trace_has_truncation_fields(self):
        from hermes_bedrock_agent.retrieval.trace import HybridTrace
        t = HybridTrace()
        assert hasattr(t, "keyword_scan_limit")
        assert hasattr(t, "keyword_scan_rows")
        assert hasattr(t, "keyword_scan_truncated")
        assert t.keyword_scan_truncated is False
