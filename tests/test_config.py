"""Tests for hermes_bedrock_agent.config — multi-KB Settings."""
from __future__ import annotations

import pytest

from hermes_bedrock_agent.config import KBEntry, Settings

# ---------------------------------------------------------------------------
# KBEntry
# ---------------------------------------------------------------------------

class TestKBEntry:
    def test_display_name_uses_label_when_set(self):
        kb = KBEntry(kb_id="KB001", label="docs")
        assert kb.display_name == "docs"

    def test_display_name_falls_back_to_id(self):
        kb = KBEntry(kb_id="KB001")
        assert kb.display_name == "KB001"

    def test_empty_label_falls_back_to_id(self):
        kb = KBEntry(kb_id="KB001", label="")
        assert kb.display_name == "KB001"


# ---------------------------------------------------------------------------
# Settings.from_env
# ---------------------------------------------------------------------------

class TestSettingsFromEnv:
    # ---- single-KB (legacy) -----------------------------------------------

    def test_single_kb_from_BEDROCK_KNOWLEDGE_BASE_ID(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "LEGACY01")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASES", raising=False)
        s = Settings.from_env()
        assert len(s.knowledge_bases) == 1
        assert s.knowledge_bases[0].kb_id == "LEGACY01"
        assert s.knowledge_bases[0].label == ""

    def test_single_kb_with_label(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "LEGACY01")
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_LABEL", "legacy-docs")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASES", raising=False)
        s = Settings.from_env()
        assert s.knowledge_bases[0].label == "legacy-docs"

    def test_legacy_compat_property(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "LEGACYID")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASES", raising=False)
        s = Settings.from_env()
        assert s.bedrock_knowledge_base_id == "LEGACYID"

    # ---- multi-KB (new) ---------------------------------------------------

    def test_multi_kb_from_BEDROCK_KNOWLEDGE_BASES(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASES", "docs:KB001,sales:KB002,support:KB003")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASE_ID", raising=False)
        s = Settings.from_env()
        assert len(s.knowledge_bases) == 3
        assert s.knowledge_bases[0] == KBEntry(kb_id="KB001", label="docs")
        assert s.knowledge_bases[1] == KBEntry(kb_id="KB002", label="sales")
        assert s.knowledge_bases[2] == KBEntry(kb_id="KB003", label="support")

    def test_multi_kb_bare_ids_no_labels(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASES", "KB001,KB002")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASE_ID", raising=False)
        s = Settings.from_env()
        assert s.knowledge_bases[0].kb_id == "KB001"
        assert s.knowledge_bases[0].label == ""
        assert s.knowledge_bases[1].kb_id == "KB002"

    def test_multi_kb_mixed_labeled_and_bare(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASES", "docs:KB001,KB002")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASE_ID", raising=False)
        s = Settings.from_env()
        assert s.knowledge_bases[0].label == "docs"
        assert s.knowledge_bases[1].label == ""

    def test_multi_kb_takes_priority_over_legacy(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASES", "a:KB001")
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "SHOULD_BE_IGNORED")
        s = Settings.from_env()
        assert len(s.knowledge_bases) == 1
        assert s.knowledge_bases[0].kb_id == "KB001"

    def test_multi_kb_whitespace_tolerant(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASES", " docs : KB001 , sales : KB002 ")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASE_ID", raising=False)
        s = Settings.from_env()
        assert s.knowledge_bases[0].kb_id == "KB001"
        assert s.knowledge_bases[0].label == "docs"

    def test_multi_kb_ignores_empty_tokens(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASES", "docs:KB001,,sales:KB002")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASE_ID", raising=False)
        s = Settings.from_env()
        assert len(s.knowledge_bases) == 2

    # ---- error cases -------------------------------------------------------

    def test_raises_when_no_kb_configured(self, monkeypatch):
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASES", raising=False)
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASE_ID", raising=False)
        with pytest.raises(ValueError, match="No knowledge bases configured"):
            Settings.from_env()

    def test_bedrock_knowledge_base_id_raises_when_empty_list(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "KB1")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASES", raising=False)
        s = Settings(aws_region="us-east-1", knowledge_bases=[])
        with pytest.raises(ValueError, match="No knowledge bases configured"):
            _ = s.bedrock_knowledge_base_id

    def test_region_defaults_to_ap_northeast_1(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "KB1")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASES", raising=False)
        monkeypatch.delenv("AWS_REGION", raising=False)
        s = Settings.from_env()
        assert s.aws_region == "ap-northeast-1"

    def test_custom_region(self, monkeypatch):
        monkeypatch.setenv("BEDROCK_KNOWLEDGE_BASE_ID", "KB1")
        monkeypatch.delenv("BEDROCK_KNOWLEDGE_BASES", raising=False)
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        s = Settings.from_env()
        assert s.aws_region == "us-west-2"
