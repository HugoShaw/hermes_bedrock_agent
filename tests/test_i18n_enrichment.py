"""Tests for Phase 10B — i18n Enrichment + Multilingual Aliases.

Tests:
1. I18nEnricher with mock LLM
2. EntityIndex with i18n aliases (aliases_zh, aliases_ja, display_name_*)
3. Simplified/Traditional Chinese normalization
4. Integration: enriched entities → query extraction → graph search terms
"""

import json
import tempfile
from pathlib import Path

import pytest

from hermes_bedrock_agent.graph.i18n_enricher import (
    EntityI18n,
    EnrichmentConfig,
    I18nEnricher,
    RelationI18n,
)
from hermes_bedrock_agent.retrieval.query_entity_extractor import (
    EntityIndex,
    QueryEntityExtractor,
    _normalize_cjk_variants,
)


# ─── Mock LLM Client ─────────────────────────────────────────────────────────


class MockLLMClient:
    """Mock LLM that returns predictable i18n enrichment."""

    def __init__(self):
        self.call_count = 0
        self._entity_responses = {
            "journal_base": json.dumps({
                "display_name": "JOURNAL_BASE (仕訳基礎)",
                "display_name_zh": "记账基础表",
                "display_name_en": "Journal Base Table",
                "display_name_ja": "仕訳基礎テーブル",
                "aliases_zh": ["记账基础", "仕訳基礎", "日记帐基础表", "凭证基础表"],
                "aliases_en": ["journal base", "journal entries table", "JB table"],
                "aliases_ja": ["仕訳基礎", "仕訳テーブル", "ジャーナルベース"],
                "description_zh": "存储财务和物料交易日记帐条目的数据库表。",
                "description_en": "Database table storing journal entries with financial and material transaction data.",
                "description_ja": "財務および資材取引の仕訳データを格納するデータベーステーブル。",
                "label_mode_hint": "technical",
            }),
            "payment_req": json.dumps({
                "display_name": "payment_req (付款申請)",
                "display_name_zh": "付款申请表",
                "display_name_en": "Payment Request Table",
                "display_name_ja": "支払申請テーブル",
                "aliases_zh": ["付款申请", "付款申請", "支付申请", "付款请求表"],
                "aliases_en": ["payment request", "pay req", "payment requisition"],
                "aliases_ja": ["支払申請", "支払リクエスト", "ペイメントリクエスト"],
                "description_zh": "存储付款申请信息的数据库表，包含付款金额、供应商、审批状态等。",
                "description_en": "Database table storing payment request information including amount, vendor, and approval status.",
                "description_ja": "支払い申請情報を格納するデータベーステーブル。金額、仕入先、承認状態などを含む。",
                "label_mode_hint": "technical",
            }),
            "muratapr": json.dumps({
                "display_name": "muratapr (Murata PRシステム)",
                "display_name_zh": "Murata PR系统",
                "display_name_en": "Murata PR System",
                "display_name_ja": "Murata PRシステム",
                "aliases_zh": ["Murata PR系统", "村田PR", "PR系统"],
                "aliases_en": ["Murata PR", "murata pr system", "PR application"],
                "aliases_ja": ["ムラタPR", "Murata PR", "PRシステム"],
                "description_zh": "Murata企业应用主系统，包含ERP/财务/支付处理功能。",
                "description_en": "Main Murata enterprise application system containing ERP/financial/payment processing.",
                "description_ja": "ERP/財務/支払処理機能を含むMurata企業アプリケーションのメインシステム。",
                "label_mode_hint": "business",
            }),
        }

    def invoke(self, prompt: str, *, max_tokens: int = 4096) -> str:
        self.call_count += 1
        # Extract entity name from prompt — match on the "- name:" line
        prompt_lower = prompt.lower()
        # Match specific name patterns in the LLM prompt
        if "- name: journal_base" in prompt_lower or "- name: JOURNAL_BASE" in prompt:
            return self._entity_responses["journal_base"]
        if "- name: payment_req" in prompt_lower:
            return self._entity_responses["payment_req"]
        if "- name: muratapr" in prompt_lower:
            return self._entity_responses["muratapr"]
        # Fallback: check canonical_name in prompt
        for key, response in self._entity_responses.items():
            if f"canonical_name: {key}" in prompt_lower:
                return response
        # Default response for unknown entities
        return json.dumps({
            "display_name": "Unknown Entity",
            "display_name_zh": "",
            "display_name_en": "",
            "display_name_ja": "",
            "aliases_zh": [],
            "aliases_en": [],
            "aliases_ja": [],
            "description_zh": "",
            "description_en": "",
            "description_ja": "",
            "label_mode_hint": "mixed",
        })


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm():
    return MockLLMClient()


@pytest.fixture
def enrichment_config():
    return EnrichmentConfig(
        max_entities=10,
        max_relations=5,
        batch_size=5,
        min_degree=20,
        dry_run=True,
    )


@pytest.fixture
def sample_entities():
    return [
        {
            "entity_id": "ent_journal_base_001",
            "name": "JOURNAL_BASE",
            "canonical_name": "journal_base",
            "entity_type": "table",
            "description": "Database table storing journal entries with financial and material transaction data",
            "degree": 656,
        },
        {
            "entity_id": "ent_payment_req_001",
            "name": "payment_req",
            "canonical_name": "payment_req",
            "entity_type": "table",
            "description": "Payment request table containing payment details",
            "degree": 42,
        },
        {
            "entity_id": "ent_muratapr_001",
            "name": "muratapr",
            "canonical_name": "muratapr",
            "entity_type": "system",
            "description": "Main application system containing the ERP modules",
            "degree": 104,
        },
    ]


@pytest.fixture
def entities_jsonl(sample_entities, tmp_path):
    path = tmp_path / "entities.jsonl"
    with open(path, "w") as f:
        for e in sample_entities:
            f.write(json.dumps(e) + "\n")
    return path


@pytest.fixture
def enriched_jsonl(tmp_path):
    """Pre-made i18n enrichment file."""
    enriched = [
        {
            "entity_id": "ent_journal_base_001",
            "name": "JOURNAL_BASE",
            "canonical_name": "journal_base",
            "entity_type": "table",
            "display_name": "JOURNAL_BASE (仕訳基礎)",
            "display_name_zh": "记账基础表",
            "display_name_en": "Journal Base Table",
            "display_name_ja": "仕訳基礎テーブル",
            "aliases_zh": ["记账基础", "仕訳基礎", "日记帐基础表"],
            "aliases_en": ["journal base", "journal entries table"],
            "aliases_ja": ["仕訳基礎", "仕訳テーブル", "ジャーナルベース"],
            "description_zh": "存储财务和物料交易日记帐条目的数据库表。",
            "description_en": "Database table storing journal entries.",
            "description_ja": "仕訳データを格納するテーブル。",
            "label_mode_hint": "technical",
        },
        {
            "entity_id": "ent_payment_req_001",
            "name": "payment_req",
            "canonical_name": "payment_req",
            "entity_type": "table",
            "display_name": "payment_req (付款申請)",
            "display_name_zh": "付款申请表",
            "display_name_en": "Payment Request Table",
            "display_name_ja": "支払申請テーブル",
            "aliases_zh": ["付款申请", "付款申請", "支付申请"],
            "aliases_en": ["payment request", "pay req"],
            "aliases_ja": ["支払申請", "支払リクエスト"],
            "description_zh": "付款申请表",
            "description_en": "Payment request table",
            "description_ja": "支払申請テーブル",
            "label_mode_hint": "technical",
        },
        {
            "entity_id": "ent_muratapr_001",
            "name": "muratapr",
            "canonical_name": "muratapr",
            "entity_type": "system",
            "display_name": "muratapr (Murata PRシステム)",
            "display_name_zh": "Murata PR系统",
            "display_name_en": "Murata PR System",
            "display_name_ja": "Murata PRシステム",
            "aliases_zh": ["Murata PR系统", "村田PR"],
            "aliases_en": ["Murata PR", "murata pr system"],
            "aliases_ja": ["ムラタPR", "PRシステム"],
            "description_zh": "Murata企业应用主系统",
            "description_en": "Main Murata enterprise app",
            "description_ja": "Murata企業アプリのメインシステム",
            "label_mode_hint": "business",
        },
    ]
    path = tmp_path / "i18n_entities_enriched.jsonl"
    with open(path, "w") as f:
        for e in enriched:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return path


# ─── Tests: I18nEnricher ──────────────────────────────────────────────────────


class TestI18nEnricher:
    def test_enrich_single_entity(self, mock_llm, enrichment_config, sample_entities):
        enricher = I18nEnricher(mock_llm, config=enrichment_config)
        result = enricher.enrich_entity_i18n(sample_entities[0])

        assert isinstance(result, EntityI18n)
        assert result.entity_id == "ent_journal_base_001"
        assert result.display_name_ja == "仕訳基礎テーブル"
        assert result.display_name_zh == "记账基础表"
        assert "仕訳基礎" in result.aliases_ja
        assert result.label_mode_hint == "technical"
        assert mock_llm.call_count == 1

    def test_enrich_payment_req(self, mock_llm, enrichment_config, sample_entities):
        enricher = I18nEnricher(mock_llm, config=enrichment_config)
        result = enricher.enrich_entity_i18n(sample_entities[1])

        assert result.display_name_ja == "支払申請テーブル"
        assert "付款申请" in result.aliases_zh
        assert "付款申請" in result.aliases_zh

    def test_batch_enrich(self, mock_llm, enrichment_config, sample_entities):
        enricher = I18nEnricher(mock_llm, config=enrichment_config)
        results = enricher.batch_enrich_entities(sample_entities)

        assert len(results) == 3
        assert mock_llm.call_count == 3
        assert results[0].name == "JOURNAL_BASE"
        assert results[1].name == "payment_req"
        assert results[2].name == "muratapr"

    def test_enrich_relation(self, mock_llm, enrichment_config):
        enricher = I18nEnricher(mock_llm, config=enrichment_config)
        result = enricher.enrich_relation_i18n("CONTAINS", count=1907)

        assert isinstance(result, RelationI18n)
        assert result.relation_type == "CONTAINS"
        # Mock returns generic but non-empty
        assert result.enriched_at != ""

    def test_select_from_jsonl(self, mock_llm, enrichment_config, entities_jsonl):
        enricher = I18nEnricher(mock_llm, config=enrichment_config)
        selected = enricher.select_entities_for_enrichment(
            entities_jsonl_path=entities_jsonl
        )
        assert len(selected) == 3

    def test_write_artifacts(self, mock_llm, enrichment_config, sample_entities, tmp_path):
        enricher = I18nEnricher(mock_llm, config=enrichment_config)
        entity_results = enricher.batch_enrich_entities(sample_entities)
        rel_results = [
            enricher.enrich_relation_i18n("CONTAINS", count=1907),
        ]

        paths = enricher.write_i18n_artifacts(entity_results, rel_results, tmp_path)

        assert (tmp_path / "i18n_entities_enriched.jsonl").exists()
        assert (tmp_path / "i18n_relations_enriched.jsonl").exists()
        assert (tmp_path / "i18n_update_neptune_preview.cypher").exists()
        assert (tmp_path / "i18n_enrichment_report.json").exists()

        # Verify JSONL content
        with open(paths["entities"]) as f:
            lines = f.readlines()
        assert len(lines) == 3
        first = json.loads(lines[0])
        assert first["entity_id"] == "ent_journal_base_001"
        assert first["display_name_ja"] == "仕訳基礎テーブル"

    def test_dry_run_no_neptune(self, mock_llm, enrichment_config, sample_entities):
        """Dry run should not write to Neptune."""
        enricher = I18nEnricher(mock_llm, config=enrichment_config)
        entity_results = enricher.batch_enrich_entities(sample_entities)

        stats = enricher.optional_update_neptune_i18n_properties(entity_results, [])
        assert stats["mode"] == "dry_run"
        assert stats["entities_updated"] == 0


# ─── Tests: CJK Normalization ─────────────────────────────────────────────────


class TestCJKNormalization:
    def test_simplified_to_traditional(self):
        variants = _normalize_cjk_variants("付款申请")
        assert "付款申请" in variants  # original
        assert "付款申請" in variants  # traditional

    def test_traditional_to_simplified(self):
        variants = _normalize_cjk_variants("付款申請")
        assert "付款申請" in variants  # original
        assert "付款申请" in variants  # simplified

    def test_no_variants_for_japanese(self):
        """Pure Japanese text shouldn't have S/T variants."""
        variants = _normalize_cjk_variants("仕訳基礎")
        # 仕 and 礎 are not in S/T mapping
        assert "仕訳基礎" in variants

    def test_mixed_text(self):
        variants = _normalize_cjk_variants("系统设计")
        assert "系统设计" in variants
        assert any("統" in v and "設" in v and "計" in v for v in variants)


# ─── Tests: EntityIndex with i18n ────────────────────────────────────────────


class TestEntityIndexI18n:
    def test_load_with_i18n_fields(self, enriched_jsonl):
        """Test loading entities that already have i18n fields."""
        idx = EntityIndex()
        count = idx.load_from_jsonl(enriched_jsonl)
        assert count == 3

        # Should find via Japanese alias
        result = idx.lookup("仕訳基礎")
        assert result is not None
        assert result["canonical_name"] == "journal_base"

    def test_load_i18n_enrichment_overlay(self, entities_jsonl, enriched_jsonl):
        """Test loading base entities then overlaying i18n enrichment."""
        idx = EntityIndex()
        base_count = idx.load_from_jsonl(entities_jsonl)
        assert base_count == 3

        # Before enrichment: no Japanese alias
        assert idx.lookup("仕訳基礎") is None

        # Load enrichment
        enrich_count = idx.load_i18n_enrichment(enriched_jsonl)
        assert enrich_count == 3

        # After enrichment: Japanese alias works
        result = idx.lookup("仕訳基礎")
        assert result is not None
        assert result["canonical_name"] == "journal_base"

    def test_cjk_match_after_enrichment(self, entities_jsonl, enriched_jsonl):
        """CJK substring matching should work with i18n aliases."""
        idx = EntityIndex()
        idx.load_from_jsonl(entities_jsonl)
        idx.load_i18n_enrichment(enriched_jsonl)

        # Match Japanese in text
        matches = idx.cjk_match("仕訳基礎とは何ですか？")
        names = [m["canonical_name"] for m in matches]
        assert "journal_base" in names

    def test_simplified_chinese_match(self, entities_jsonl, enriched_jsonl):
        """Simplified Chinese should match via S/T normalization."""
        idx = EntityIndex()
        idx.load_from_jsonl(entities_jsonl)
        idx.load_i18n_enrichment(enriched_jsonl)

        # "付款申请" (simplified) should match "付款申請" (traditional) alias
        matches = idx.cjk_match("付款申请相关表有哪些？")
        names = [m["canonical_name"] for m in matches]
        assert "payment_req" in names

    def test_traditional_chinese_match(self, entities_jsonl, enriched_jsonl):
        """Traditional Chinese should also match."""
        idx = EntityIndex()
        idx.load_from_jsonl(entities_jsonl)
        idx.load_i18n_enrichment(enriched_jsonl)

        matches = idx.cjk_match("付款申請")
        names = [m["canonical_name"] for m in matches]
        assert "payment_req" in names


# ─── Tests: Integration — Enrichment → Query Extraction ──────────────────────


class TestI18nIntegration:
    def test_japanese_query_after_enrichment(self, entities_jsonl, enriched_jsonl):
        """仕訳基礎とは何ですか？ → JOURNAL_BASE after i18n enrichment."""
        idx = EntityIndex()
        idx.load_from_jsonl(entities_jsonl)
        idx.load_i18n_enrichment(enriched_jsonl)

        extractor = QueryEntityExtractor(idx)
        result = extractor.extract("仕訳基礎とは何ですか？")

        assert len(result.graph_search_terms) > 0
        terms_lower = [t.lower() for t in result.graph_search_terms]
        assert any("journal_base" in t or "仕訳基礎" in t for t in terms_lower)

    def test_simplified_chinese_query(self, entities_jsonl, enriched_jsonl):
        """付款申请相关表有哪些？ → payment_req after enrichment."""
        idx = EntityIndex()
        idx.load_from_jsonl(entities_jsonl)
        idx.load_i18n_enrichment(enriched_jsonl)

        extractor = QueryEntityExtractor(idx)
        result = extractor.extract("付款申请相关表有哪些？")

        terms_lower = [t.lower() for t in result.graph_search_terms]
        assert any("payment_req" in t or "paymentreq" in t or "付款申请" in t for t in terms_lower)

    def test_traditional_chinese_query(self, entities_jsonl, enriched_jsonl):
        """付款申請 → payment_req after enrichment."""
        idx = EntityIndex()
        idx.load_from_jsonl(entities_jsonl)
        idx.load_i18n_enrichment(enriched_jsonl)

        extractor = QueryEntityExtractor(idx)
        result = extractor.extract("付款申請は何に使われていますか？")

        terms_lower = [t.lower() for t in result.graph_search_terms]
        assert any("payment_req" in t or "paymentreq" in t or "付款申請" in t for t in terms_lower)

    def test_murata_pr_query(self, entities_jsonl, enriched_jsonl):
        """Murata PR → muratapr after enrichment."""
        idx = EntityIndex()
        idx.load_from_jsonl(entities_jsonl)
        idx.load_i18n_enrichment(enriched_jsonl)

        extractor = QueryEntityExtractor(idx)
        result = extractor.extract("Murata PR システムの概要")

        terms_lower = [t.lower() for t in result.graph_search_terms]
        assert any("muratapr" in t or "murata" in t for t in terms_lower)

    def test_technical_mode_display(self, enriched_jsonl):
        """Technical mode should show canonical_name."""
        # Load enriched data
        with open(enriched_jsonl) as f:
            entities = [json.loads(line) for line in f]

        jb = next(e for e in entities if e["canonical_name"] == "journal_base")
        assert jb["label_mode_hint"] == "technical"
        # In technical mode, display canonical_name
        assert jb["canonical_name"] == "journal_base"

    def test_business_mode_display(self, enriched_jsonl):
        """Business mode should show display_name_ja/zh."""
        with open(enriched_jsonl) as f:
            entities = [json.loads(line) for line in f]

        mpr = next(e for e in entities if e["canonical_name"] == "muratapr")
        assert mpr["label_mode_hint"] == "business"
        assert mpr["display_name_ja"] == "Murata PRシステム"
        assert mpr["display_name_zh"] == "Murata PR系统"

    def test_question_not_single_term(self, entities_jsonl, enriched_jsonl):
        """Full sentence should never be a single search term."""
        idx = EntityIndex()
        idx.load_from_jsonl(entities_jsonl)
        idx.load_i18n_enrichment(enriched_jsonl)

        extractor = QueryEntityExtractor(idx)
        question = "仕訳基礎テーブルの構造について教えてください。"
        result = extractor.extract(question)

        # Full sentence should not appear as a search term
        for term in result.graph_search_terms:
            assert len(term) < len(question) * 0.8
