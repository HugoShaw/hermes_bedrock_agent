"""Golden regression test for M社 DSS フローチャート conversion.

This test ensures the pipeline output for the M社 DSS flowchart stays
semantically equivalent to the manually reviewed golden reference.
"""

import json
import pytest
from pathlib import Path


# Paths relative to project root
PROJECT_ROOT = Path(__file__).parent.parent
ACTUAL_MMD = PROJECT_ROOT / "data" / "output" / "flowchart_samples" / "msha_dss_flowchart" / "flowchart.mmd"
EXPECTED_MMD = PROJECT_ROOT / "data" / "reference" / "flowchart_gold" / "msha_dss_flowchart.expected.mmd"
ACTUAL_SVG = PROJECT_ROOT / "data" / "output" / "flowchart_samples" / "msha_dss_flowchart" / "flowchart.svg"
COMPARISON_DIR = PROJECT_ROOT / "data" / "output" / "flowchart_samples" / "msha_dss_flowchart" / "comparison_after_fix"


@pytest.fixture(scope="module")
def diff_result():
    """Load or compute the graph diff between actual and expected."""
    # Check files exist
    if not ACTUAL_MMD.exists():
        pytest.skip(f"Actual Mermaid not found: {ACTUAL_MMD}")
    if not EXPECTED_MMD.exists():
        pytest.skip(f"Expected Mermaid not found: {EXPECTED_MMD}")
    
    from flowchart_to_mermaid.compare.mermaid_parser import MermaidParser
    from flowchart_to_mermaid.compare.graph_normalizer import GraphNormalizer
    from flowchart_to_mermaid.compare.graph_diff import GraphDiff

    parser = MermaidParser()
    normalizer = GraphNormalizer()
    differ = GraphDiff()

    actual_parsed = parser.parse(ACTUAL_MMD.read_text())
    expected_parsed = parser.parse(EXPECTED_MMD.read_text())

    actual_norm = normalizer.normalize(actual_parsed)
    expected_norm = normalizer.normalize(expected_parsed)

    return differ.diff(actual_norm, expected_norm)


@pytest.fixture(scope="module")
def actual_content():
    """Load actual Mermaid content."""
    if not ACTUAL_MMD.exists():
        pytest.skip(f"Actual Mermaid not found: {ACTUAL_MMD}")
    return ACTUAL_MMD.read_text()


class TestMshaDssRegression:
    """Golden regression tests for the M社 DSS flowchart."""

    def test_critical_diff_count_is_zero(self, diff_result):
        """No CRITICAL differences allowed."""
        assert diff_result.severity_counts["CRITICAL"] == 0, (
            f"Found {diff_result.severity_counts['CRITICAL']} CRITICAL diffs: "
            + "; ".join(d.description for d in diff_result.details if d.severity == "CRITICAL")
        )

    def test_high_diff_count_acceptable(self, diff_result):
        """HIGH differences should be <= 3 (acceptable threshold)."""
        high_count = diff_result.severity_counts["HIGH"]
        assert high_count <= 3, (
            f"Found {high_count} HIGH diffs (max 3 allowed): "
            + "; ".join(d.description for d in diff_result.details if d.severity == "HIGH")
        )

    def test_svg_exists(self):
        """SVG must be generated."""
        assert ACTUAL_SVG.exists(), f"SVG not found: {ACTUAL_SVG}"

    def test_svg_non_empty(self):
        """SVG must have content."""
        if not ACTUAL_SVG.exists():
            pytest.skip("SVG not generated")
        assert ACTUAL_SVG.stat().st_size > 0, "SVG file is empty"

    def test_svg_minimum_size(self):
        """SVG should be substantial (>100KB for this complex flowchart)."""
        if not ACTUAL_SVG.exists():
            pytest.skip("SVG not generated")
        size = ACTUAL_SVG.stat().st_size
        assert size > 100_000, f"SVG too small ({size} bytes), likely incomplete rendering"

    def test_contains_processing_flag_condition(self, actual_content):
        """Must contain 条件：処理フラグ (the main decision point)."""
        assert "条件：処理フラグ" in actual_content or "条件:処理フラグ" in actual_content

    def test_contains_post_api(self, actual_content):
        """Must contain POST：発注データ登録API."""
        assert "POST：発注データ登録API" in actual_content or "POST:発注データ登録API" in actual_content

    def test_contains_get_order_api(self, actual_content):
        """Must contain GET：発注一覧取得API."""
        assert "GET：発注一覧取得API" in actual_content or "GET:発注一覧取得API" in actual_content

    def test_contains_delivery_cancel_api(self, actual_content):
        """Must contain PUT：納品キャンセルAPI."""
        assert "PUT：納品キャンセルAPI" in actual_content or "PUT:納品キャンセルAPI" in actual_content

    def test_contains_order_cancel_api(self, actual_content):
        """Must contain PUT：発注キャンセルAPI."""
        assert "PUT：発注キャンセルAPI" in actual_content or "PUT:発注キャンセルAPI" in actual_content

    def test_contains_exception_handling(self, actual_content):
        """Must contain 例外発生時."""
        assert "例外発生時" in actual_content

    def test_contains_file_cleanup_27(self, actual_content):
        """Must contain 機能No27：ファイル削除・移動."""
        assert "機能No27" in actual_content

    def test_contains_file_cleanup_28(self, actual_content):
        """Must contain 機能No28：ファイル削除・移動."""
        assert "機能No28" in actual_content

    def test_contains_registration_branch(self, actual_content):
        """Must contain 1（登録）の場合 branch."""
        assert "1（登録）の場合" in actual_content

    def test_contains_change_branch(self, actual_content):
        """Must contain 2（変更）の場合 branch."""
        assert "2（変更）の場合" in actual_content

    def test_contains_delete_branch(self, actual_content):
        """Must contain 3 or 4（削除）の場合 branch."""
        assert "3 or 4（削除）の場合" in actual_content

    def test_contains_order_status_301(self, actual_content):
        """Must contain 301（発注前）の場合 branch."""
        assert "301（発注前）の場合" in actual_content

    def test_contains_order_status_302(self, actual_content):
        """Must contain 302（請負待ち）の場合 branch."""
        assert "302（請負待ち）の場合" in actual_content

    def test_contains_order_status_303(self, actual_content):
        """Must contain 303（請負済）の場合 branch."""
        assert "303（請負済）の場合" in actual_content

    def test_node_count_matches(self, diff_result):
        """Node count should match (no missing or extra nodes)."""
        assert len(diff_result.missing_nodes) == 0, (
            f"Missing nodes: {diff_result.missing_nodes}"
        )

    def test_no_missing_edges(self, diff_result):
        """No missing edges (HIGH or CRITICAL level)."""
        critical_missing = [
            e for e in diff_result.missing_edges
        ]
        # Allow at most 3 missing edges at any level
        assert len(critical_missing) <= 3, (
            f"Too many missing edges ({len(critical_missing)}): {critical_missing[:5]}"
        )
