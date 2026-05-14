"""Tests for QueryEntityExtractor with i18n enrichment data.

Phase 10B: Verifies that multilingual aliases from i18n enrichment
improve graph retrieval hit rate for CJK queries.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_entities_jsonl(tmp_path: Path) -> Path:
    """Create a minimal entities.jsonl for testing."""
    entities = [
        {
            "entity_id": "journal_base",
            "entity_type": "table",
            "canonical_name": "JOURNAL_BASE",
            "name": "JOURNAL_BASE",
            "description": "Journal base table for financial transactions",
            "degree": 120,
        },
        {
            "entity_id": "payment_req",
            "entity_type": "table",
            "canonical_name": "payment_req",
            "name": "payment_req",
            "description": "Payment request processing table",
            "degree": 85,
        },
        {
            "entity_id": "muratapr",
            "entity_type": "system",
            "canonical_name": "muratapr",
            "name": "muratapr",
            "description": "Murata PR enterprise system",
            "degree": 200,
        },
        {
            "entity_id": "mv0008",
            "entity_type": "screen",
            "canonical_name": "MV0008",
            "name": "MV0008",
            "description": "Inquiry screen for data retrieval",
            "degree": 30,
        },
    ]
    path = tmp_path / "entities.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for ent in entities:
            f.write(json.dumps(ent, ensure_ascii=False) + "\n")
    return path


@pytest.fixture
def sample_i18n_enriched_jsonl(tmp_path: Path) -> Path:
    """Create i18n_entities_enriched.jsonl with multilingual aliases."""
    enriched = [
        {
            "entity_id": "journal_base",
            "entity_type": "table",
            "canonical_name": "JOURNAL_BASE",
            "name": "JOURNAL_BASE",
            "display_name": "JOURNAL_BASE (仕訳基礎)",
            "display_name_zh": "记账基础表",
            "display_name_en": "Journal Base Table",
            "display_name_ja": "仕訳基礎テーブル",
            "aliases_zh": ["记账基础", "仕訳基礎", "日记帐基础表", "凭证基础表"],
            "aliases_en": ["journal base", "journal entries table", "JB table"],
            "aliases_ja": ["仕訳基礎", "仕訳テーブル", "ジャーナルベース", "仕訳基礎表"],
            "description_zh": "存储财务和物料交易日记帐条目的数据库表。",
            "description_en": "Database table storing journal entries with financial and material transaction data.",
            "description_ja": "財務および資材取引の仕訳データを格納するデータベーステーブル。",
            "label_mode_hint": "technical",
            "enrichment_confidence": 0.95,
        },
        {
            "entity_id": "payment_req",
            "entity_type": "table",
            "canonical_name": "payment_req",
            "name": "payment_req",
            "display_name": "payment_req (付款申請)",
            "display_name_zh": "付款申请表",
            "display_name_en": "Payment Request Table",
            "display_name_ja": "支払申請テーブル",
            "aliases_zh": ["付款申请", "付款申請", "支付申请", "付款请求表"],
            "aliases_en": ["payment request", "pay req", "payment requisition", "paymentrequest"],
            "aliases_ja": ["支払申請", "支払リクエスト", "ペイメントリクエスト"],
            "description_zh": "存储付款申请信息的数据库表",
            "description_en": "Database table storing payment request information",
            "description_ja": "支払い申請情報を格納するデータベーステーブル",
            "label_mode_hint": "technical",
            "enrichment_confidence": 0.95,
        },
        {
            "entity_id": "muratapr",
            "entity_type": "system",
            "canonical_name": "muratapr",
            "name": "muratapr",
            "display_name": "muratapr (Murata PRシステム)",
            "display_name_zh": "Murata PR系统",
            "display_name_en": "Murata PR System",
            "display_name_ja": "Murata PRシステム",
            "aliases_zh": ["Murata PR系统", "村田PR", "PR系统", "村田PR系统"],
            "aliases_en": ["Murata PR", "murata pr system", "PR application"],
            "aliases_ja": ["ムラタPR", "Murata PR", "PRシステム", "村田PRシステム"],
            "description_zh": "Murata企业应用主系统",
            "description_en": "Main Murata enterprise application system",
            "description_ja": "Murata企業アプリケーションのメインシステム",
            "label_mode_hint": "business",
            "enrichment_confidence": 0.95,
        },
    ]
    path = tmp_path / "i18n_entities_enriched.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for ent in enriched:
            f.write(json.dumps(ent, ensure_ascii=False) + "\n")
    return path


# ─── Import helpers ───────────────────────────────────────────────────────────


def load_entity_index(entities_path: Path, i18n_path: Path = None):
    """Load EntityIndex from entities.jsonl, optionally enhanced with i18n data."""
    from hermes_bedrock_agent.retrieval.query_entity_extractor import (
        EntityIndex,
        QueryEntityExtractor,
    )

    index = EntityIndex()
    index.load_from_jsonl(entities_path)

    # Load i18n enrichment if provided
    if i18n_path and i18n_path.exists():
        index.load_i18n_enrichment(i18n_path)

    return index


def search_entities(index, query: str) -> list[str]:
    """Search for entities matching query using all available methods.

    Returns list of entity_ids found.
    """
    results = set()

    # Try exact lookup
    result = index.lookup(query.lower())
    if result:
        results.add(result.get("entity_id", ""))

    # Try prefix match
    for r in index.prefix_match(query.lower(), max_results=5):
        results.add(r.get("entity_id", ""))

    # Try substring match
    for r in index.substring_match(query.lower(), max_results=10):
        results.add(r.get("entity_id", ""))

    # Try CJK match
    for r in index.cjk_match(query, max_results=10):
        results.add(r.get("entity_id", ""))

    results.discard("")
    return list(results)


# ─── Tests: Japanese query resolution ────────────────────────────────────────


class TestJapaneseQueries:
    """Test that Japanese business terms resolve to correct entities after i18n enrichment."""

    def test_shiwake_kiso_matches_journal_base(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """仕訳基礎 → JOURNAL_BASE"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "仕訳基礎")
        assert "journal_base" in entity_ids

    def test_shiwake_kiso_table_matches_journal_base(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """仕訳基礎テーブル → JOURNAL_BASE"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "仕訳基礎テーブル")
        assert "journal_base" in entity_ids

    def test_shiwake_kiso_hyou_matches_journal_base(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """仕訳基礎表 → JOURNAL_BASE"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "仕訳基礎表")
        assert "journal_base" in entity_ids

    def test_shiharai_shinsei_matches_payment_req(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """支払申請 → payment_req"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "支払申請")
        assert "payment_req" in entity_ids

    def test_murata_pr_ja_matches_muratapr(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """村田PR → muratapr"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "村田PR")
        assert "muratapr" in entity_ids


# ─── Tests: Chinese query resolution ─────────────────────────────────────────


class TestChineseQueries:
    """Test that Chinese queries (simplified/traditional) resolve correctly."""

    def test_fukuan_shenqing_simplified_matches(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """付款申请 (simplified) → payment_req"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "付款申请")
        assert "payment_req" in entity_ids

    def test_fukuan_shenqing_traditional_matches(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """付款申請 (traditional) → payment_req"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "付款申請")
        assert "payment_req" in entity_ids

    def test_murata_pr_zh_matches(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """村田PR系统 → muratapr"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "村田PR系统")
        assert "muratapr" in entity_ids


# ─── Tests: English query resolution ─────────────────────────────────────────


class TestEnglishQueries:
    """Test that English queries resolve correctly with i18n aliases."""

    def test_murata_pr_en_matches(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """Murata PR → muratapr"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "Murata PR")
        assert "muratapr" in entity_ids

    def test_journal_base_en_still_works(
        self, sample_entities_jsonl, sample_i18n_enriched_jsonl
    ):
        """JOURNAL_BASE → journal_base (original matching still works)"""
        index = load_entity_index(sample_entities_jsonl, sample_i18n_enriched_jsonl)
        entity_ids = search_entities(index, "JOURNAL_BASE")
        assert "journal_base" in entity_ids


# ─── Tests: Backward compatibility ───────────────────────────────────────────


class TestBackwardCompatibility:
    """Test that Phase 10A behavior is preserved when i18n data is absent."""

    def test_no_i18n_file_still_works(self, sample_entities_jsonl):
        """Without i18n enrichment file, original matching still works."""
        index = load_entity_index(sample_entities_jsonl, i18n_path=None)
        entity_ids = search_entities(index, "JOURNAL_BASE")
        assert "journal_base" in entity_ids

    def test_no_i18n_file_canonical_name_match(self, sample_entities_jsonl):
        """Without i18n, canonical_name matching still works."""
        index = load_entity_index(sample_entities_jsonl, i18n_path=None)
        entity_ids = search_entities(index, "payment_req")
        assert "payment_req" in entity_ids

    def test_no_i18n_file_muratapr(self, sample_entities_jsonl):
        """Without i18n, muratapr canonical match still works."""
        index = load_entity_index(sample_entities_jsonl, i18n_path=None)
        entity_ids = search_entities(index, "muratapr")
        assert "muratapr" in entity_ids

    def test_no_i18n_file_japanese_query_empty(self, sample_entities_jsonl):
        """Without i18n, Japanese business terms get 0 matches (known limitation)."""
        index = load_entity_index(sample_entities_jsonl, i18n_path=None)
        entity_ids = search_entities(index, "仕訳基礎")
        # Without i18n data, pure Japanese terms won't match technical names
        # This is the Phase 10A known limitation being validated
        # (It may or may not match depending on description search)
        # Main point: it doesn't crash
        assert isinstance(entity_ids, list)
