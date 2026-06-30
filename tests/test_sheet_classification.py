"""Tests for classify_sheet_type with workbook_name fallback."""
import pytest

from hermes_bedrock_agent.parsing.vlm_client import classify_sheet_type


class TestClassifySheetType:
    """Verify sheet type classification from sheet name + workbook name."""

    def test_flowchart_from_sheet_name(self):
        assert classify_sheet_type("API呼出順序") == "flowchart"

    def test_flowchart_from_sheet_name_api_junjo(self):
        assert classify_sheet_type("API実行順序") == "flowchart"

    def test_flowchart_from_workbook_name(self):
        """Sheet tab is generic but workbook name contains フローチャート."""
        assert classify_sheet_type("sheet_02", "M社様_DSSスクリプト改修概要_フローチャート") == "flowchart"

    def test_flowchart_from_workbook_name_all_sheets(self):
        """All sheets in a フローチャート workbook should be classified as flowchart."""
        wb = "M社様_DSSスクリプト改修概要_フローチャート"
        assert classify_sheet_type("sheet_01", wb) == "flowchart"
        assert classify_sheet_type("sheet_02", wb) == "flowchart"
        assert classify_sheet_type("sheet_03", wb) == "flowchart"

    def test_change_history_always_wins(self):
        """変更履歴 in sheet name takes priority over workbook name."""
        assert classify_sheet_type("変更履歴", "フローチャート") == "change_history"

    def test_mapping_from_workbook_name(self):
        """マッピング定義書 in workbook name → mapping."""
        assert classify_sheet_type("sheet_05", "MW_IFマッピング定義書_205") == "mapping"

    def test_mapping_not_triggered_by_standalone_mapping(self):
        """マッピング alone without 定義書 in workbook should NOT be mapping (too broad)."""
        assert classify_sheet_type("sheet_01", "データマッピング概要") == "generic"

    def test_mapping_from_sheet_name(self):
        assert classify_sheet_type("マッピングシート") == "mapping"

    def test_dev_spec_from_sheet_name(self):
        assert classify_sheet_type("DataSpider開発仕様") == "dev_spec"

    def test_dev_spec_from_workbook_name(self):
        assert classify_sheet_type("sheet_01", "DataSpider開発仕様書") == "dev_spec"

    def test_data_condition(self):
        assert classify_sheet_type("データ取得条件") == "data_condition"

    def test_supplementary(self):
        assert classify_sheet_type("補足事項") == "supplementary"

    def test_generic_no_workbook(self):
        assert classify_sheet_type("sheet_01") == "generic"

    def test_generic_unknown_workbook(self):
        assert classify_sheet_type("sheet_01", "unknown_workbook") == "generic"

    def test_backward_compat_no_workbook_arg(self):
        """Old callers passing only sheet_name should still work."""
        assert classify_sheet_type("API呼出順序") == "flowchart"
        assert classify_sheet_type("変更履歴") == "change_history"
        assert classify_sheet_type("マッピングシート") == "mapping"
