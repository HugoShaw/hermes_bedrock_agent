"""Tests for LiveI18nEnricher and BedrockLLMAdapter (Phase 10C).

All tests use mocks — no real Bedrock/AWS calls are made.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_bedrock_agent.graph.i18n_enricher import (
    BedrockLLMAdapter,
    LiveEnrichmentConfig,
    LiveI18nEnricher,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_bedrock_response(text: str) -> dict:
    return {
        "output": {
            "message": {
                "content": [{"text": text}]
            }
        }
    }


def _valid_llm_json(name: str = "TEST_ENTITY", confidence: float = 0.9) -> str:
    return json.dumps({
        "display_name": name,
        "display_name_zh": f"{name}中文",
        "display_name_en": f"{name} English",
        "display_name_ja": f"{name}日本語",
        "aliases_zh": [f"{name}_zh"],
        "aliases_en": [name.lower()],
        "aliases_ja": [f"{name}_ja"],
        "description_zh": "テスト説明",
        "description_en": f"Description for {name}",
        "description_ja": f"{name}の説明",
        "label_mode_hint": "technical",
        "enrichment_confidence": confidence,
        "technical_aliases": [name, name.lower()],
        "business_aliases_zh": [f"{name}业务"],
        "business_aliases_en": [f"{name} business"],
        "business_aliases_ja": [f"{name}業務"],
    }, ensure_ascii=False)


def _make_live_config(**kwargs) -> LiveEnrichmentConfig:
    defaults = {
        "rate_limit_per_minute": 600,  # effectively unlimited for tests
        "max_retries": 2,
        "checkpoint_every": 5,
        "save_raw_outputs": False,
        "save_failures": False,
    }
    defaults.update(kwargs)
    return LiveEnrichmentConfig(**defaults)


def _make_mock_llm(response_text: str) -> MagicMock:
    mock = MagicMock()
    mock.invoke.return_value = response_text
    return mock


def _sample_entity(name: str = "TEST_ENTITY", eid: str = "test_entity") -> dict:
    return {
        "entity_id": eid,
        "name": name,
        "canonical_name": eid,
        "entity_type": "table",
        "description": f"Test entity {name}",
        "degree": 5,
    }


# ─── Tests ────────────────────────────────────────────────────────────────────


class TestBedrockLLMAdapterProtocol:
    def test_bedrock_llm_adapter_protocol(self):
        """BedrockLLMAdapter.invoke() extracts text from converse response."""
        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = _make_bedrock_response("hello world")

        adapter = BedrockLLMAdapter(mock_bedrock, model_id="test-model")
        result = adapter.invoke("test prompt", max_tokens=100)

        assert result == "hello world"
        mock_bedrock.converse.assert_called_once()
        call_kwargs = mock_bedrock.converse.call_args
        assert call_kwargs.kwargs["model_id"] == "test-model"
        assert call_kwargs.kwargs["messages"][0]["role"] == "user"

    def test_bedrock_llm_adapter_empty_content(self):
        """Returns empty string when response has no text block."""
        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = {"output": {"message": {"content": []}}}

        adapter = BedrockLLMAdapter(mock_bedrock)
        result = adapter.invoke("prompt")

        assert result == ""

    def test_bedrock_llm_adapter_default_model_id(self):
        """Uses APAC Claude Sonnet as default model."""
        mock_bedrock = MagicMock()
        mock_bedrock.converse.return_value = _make_bedrock_response("ok")

        adapter = BedrockLLMAdapter(mock_bedrock)
        adapter.invoke("hi")

        assert mock_bedrock.converse.call_args.kwargs["model_id"] == \
            "apac.anthropic.claude-sonnet-4-20250514-v1:0"


class TestLiveEnricherResumeFromCheckpoint:
    def test_live_enricher_resume_from_checkpoint(self, tmp_path):
        """Entities in checkpoint are skipped on resume."""
        checkpoint = tmp_path / "checkpoint.json"
        checkpoint.write_text(
            json.dumps({"processed_ids": ["entity_a", "entity_b"]}),
            encoding="utf-8",
        )

        mock_llm = _make_mock_llm(_valid_llm_json("ENTITY_C"))
        config = _make_live_config()
        enricher = LiveI18nEnricher(
            mock_llm, config=config, checkpoint_path=checkpoint
        )

        entities = [
            _sample_entity("ENTITY_A", "entity_a"),
            _sample_entity("ENTITY_B", "entity_b"),
            _sample_entity("ENTITY_C", "entity_c"),
        ]
        results = enricher.batch_enrich_live(entities)

        # Only entity_c should be processed
        assert len(results) == 1
        assert results[0].entity_id == "entity_c"
        assert mock_llm.invoke.call_count == 1


class TestLiveEnricherSkipExisting:
    def test_live_enricher_skip_existing(self):
        """Entities in existing_ids set are not re-enriched."""
        mock_llm = _make_mock_llm(_valid_llm_json("NEW"))
        config = _make_live_config()
        enricher = LiveI18nEnricher(mock_llm, config=config)

        entities = [
            _sample_entity("OLD", "old_entity"),
            _sample_entity("NEW", "new_entity"),
        ]
        results = enricher.batch_enrich_live(
            entities, existing_ids={"old_entity"}
        )

        assert len(results) == 1
        assert results[0].entity_id == "new_entity"
        assert mock_llm.invoke.call_count == 1


class TestLiveEnricherRetryOnFailure:
    def test_live_enricher_retry_on_failure(self):
        """LLM failures trigger exponential-backoff retries, then fallback."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("API error")

        config = _make_live_config(max_retries=2, rate_limit_per_minute=600)

        with patch("time.sleep"):  # don't actually sleep
            enricher = LiveI18nEnricher(mock_llm, config=config)
            entity = _sample_entity("FAIL_ENTITY", "fail_entity")
            result = enricher.enrich_entity_live(entity)

        # Should fall back gracefully — not raise
        assert result.entity_id == "fail_entity"
        assert result.enrichment_source == "fallback"
        assert result.enrichment_confidence == 0.0
        assert "API error" in result.enrichment_error
        # invoke called max_retries+1 times
        assert mock_llm.invoke.call_count == 3  # attempts 0,1,2


class TestLiveEnricherJsonParseFallback:
    def test_live_enricher_json_parse_fallback(self):
        """Invalid JSON from LLM triggers fallback to canonical_name."""
        mock_llm = _make_mock_llm("NOT VALID JSON AT ALL !!!!")
        config = _make_live_config()
        enricher = LiveI18nEnricher(mock_llm, config=config)

        entity = _sample_entity("MY_TABLE", "my_table")
        result = enricher.enrich_entity_live(entity)

        assert result.entity_id == "my_table"
        assert result.enrichment_source == "fallback"
        assert result.display_name == "MY_TABLE"  # falls back to name
        assert result.canonical_name == "my_table"  # canonical_name unchanged


class TestLiveEnricherRateLimiting:
    def test_live_enricher_rate_limiting(self):
        """Rate limiter sleeps when requests per minute is exceeded."""
        mock_llm = _make_mock_llm(_valid_llm_json())
        config = _make_live_config(rate_limit_per_minute=2)
        enricher = LiveI18nEnricher(mock_llm, config=config)

        sleep_calls = []
        original_sleep = time.sleep

        def mock_sleep(secs):
            sleep_calls.append(secs)

        entities = [_sample_entity(f"E{i}", f"e{i}") for i in range(4)]
        with patch("time.sleep", side_effect=mock_sleep):
            enricher.batch_enrich_live(entities)

        # With rate=2/min and 4 entities, sleeping must have occurred
        assert len(sleep_calls) > 0


class TestLiveEnricherRawOutputSaved:
    def test_live_enricher_raw_output_saved(self, tmp_path):
        """Raw LLM output is appended to raw_output_path when enabled."""
        raw_path = tmp_path / "raw.jsonl"
        mock_llm = _make_mock_llm(_valid_llm_json("RAW_ENTITY"))
        config = _make_live_config(save_raw_outputs=True)
        enricher = LiveI18nEnricher(
            mock_llm, config=config, raw_output_path=raw_path
        )

        entity = _sample_entity("RAW_ENTITY", "raw_entity")
        enricher.enrich_entity_live(entity)

        assert raw_path.exists()
        lines = [l for l in raw_path.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["entity_id"] == "raw_entity"
        assert "prompt" in rec
        assert "response" in rec


class TestLiveEnricherFailureLogged:
    def test_live_enricher_failure_logged(self, tmp_path):
        """Failed enrichments are written to failure_path."""
        failure_path = tmp_path / "failures.jsonl"
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("boom")
        config = _make_live_config(max_retries=0, save_failures=True)

        with patch("time.sleep"):
            enricher = LiveI18nEnricher(
                mock_llm, config=config, failure_path=failure_path
            )
            enricher.enrich_entity_live(_sample_entity("FAIL", "fail_ent"))

        assert failure_path.exists()
        rec = json.loads(failure_path.read_text().splitlines()[0])
        assert rec["entity_id"] == "fail_ent"
        assert "boom" in rec["error"]


class TestLiveEnricherTechnicalAliasPreserved:
    def test_live_enricher_technical_alias_preserved(self):
        """technical_aliases contains the original technical name from LLM."""
        raw_json = _valid_llm_json("JOURNAL_ENTRY")
        mock_llm = _make_mock_llm(raw_json)
        config = _make_live_config()
        enricher = LiveI18nEnricher(mock_llm, config=config)

        entity = _sample_entity("JOURNAL_ENTRY", "journal_entry")
        result = enricher.enrich_entity_live(entity)

        assert "JOURNAL_ENTRY" in result.technical_aliases or \
               "journal_entry" in result.technical_aliases


class TestLiveEnricherNoDryRunNeptune:
    def test_live_enricher_no_neptune_in_dry_run(self):
        """Neptune is NOT updated when dry_run=True."""
        mock_neptune = MagicMock()
        mock_llm = _make_mock_llm(_valid_llm_json())
        config = _make_live_config(dry_run=True)
        enricher = LiveI18nEnricher(mock_llm, mock_neptune, config=config)

        from hermes_bedrock_agent.graph.i18n_enricher import EntityI18n, RelationI18n
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        entity_result = EntityI18n(
            entity_id="e1", name="E1", canonical_name="e1", entity_type="table",
            model_name="test", enriched_at=now,
        )
        stats = enricher.optional_update_neptune_i18n_properties(
            [entity_result], []
        )
        assert stats["mode"] == "dry_run"
        mock_neptune.execute_query.assert_not_called()


class TestLiveEnricherNeptuneRequiresConfirm:
    def test_live_enricher_neptune_requires_confirm(self):
        """Neptune IS updated when dry_run=False and neptune client provided."""
        mock_neptune = MagicMock()
        mock_neptune.execute_query.return_value = {"results": []}
        mock_llm = _make_mock_llm(_valid_llm_json())
        config = _make_live_config(dry_run=False)
        enricher = LiveI18nEnricher(mock_llm, mock_neptune, config=config)

        from hermes_bedrock_agent.graph.i18n_enricher import EntityI18n
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        entity_result = EntityI18n(
            entity_id="e1", name="E1", canonical_name="e1", entity_type="table",
            model_name="test", enriched_at=now,
        )
        stats = enricher.optional_update_neptune_i18n_properties(
            [entity_result], []
        )
        assert stats["mode"] == "live"
        assert mock_neptune.execute_query.call_count >= 1


class TestEnrichmentConfidenceField:
    def test_enrichment_confidence_field(self):
        """enrichment_confidence is parsed from LLM output."""
        raw_json = _valid_llm_json("CONF_ENTITY", confidence=0.85)
        mock_llm = _make_mock_llm(raw_json)
        config = _make_live_config()
        enricher = LiveI18nEnricher(mock_llm, config=config)

        result = enricher.enrich_entity_live(_sample_entity("CONF_ENTITY", "conf_entity"))

        assert abs(result.enrichment_confidence - 0.85) < 0.001

    def test_enrichment_confidence_default_fallback(self):
        """Fallback enrichment has confidence 0.0."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("fail")
        config = _make_live_config(max_retries=0)

        with patch("time.sleep"):
            enricher = LiveI18nEnricher(mock_llm, config=config)
            result = enricher.enrich_entity_live(_sample_entity())

        assert result.enrichment_confidence == 0.0


class TestEnrichmentSourceField:
    def test_enrichment_source_live_llm(self):
        """Successful LLM call yields enrichment_source='live_llm'."""
        mock_llm = _make_mock_llm(_valid_llm_json())
        config = _make_live_config()
        enricher = LiveI18nEnricher(mock_llm, config=config)

        result = enricher.enrich_entity_live(_sample_entity("NORMAL", "normal"))
        assert result.enrichment_source == "live_llm"

    def test_enrichment_source_builtin(self):
        """Priority entities have enrichment_source='builtin' (no LLM call)."""
        mock_llm = MagicMock()
        config = _make_live_config()
        enricher = LiveI18nEnricher(mock_llm, config=config)

        entity = {
            "entity_id": "journal_base",
            "name": "JOURNAL_BASE",
            "canonical_name": "journal_base",
            "entity_type": "table",
            "description": "",
            "degree": 100,
        }
        result = enricher.enrich_entity_live(entity)

        assert result.enrichment_source == "builtin"
        mock_llm.invoke.assert_not_called()

    def test_enrichment_source_fallback_on_retry_exhaustion(self):
        """Exhausting retries yields enrichment_source='fallback'."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("network error")
        config = _make_live_config(max_retries=1)

        with patch("time.sleep"):
            enricher = LiveI18nEnricher(mock_llm, config=config)
            result = enricher.enrich_entity_live(_sample_entity())

        assert result.enrichment_source == "fallback"


class TestEntityIdUnchanged:
    def test_entity_id_unchanged(self):
        """entity_id is never modified by enrichment."""
        original_id = "immutable_entity_id_abc123"
        mock_llm = _make_mock_llm(_valid_llm_json("SOME_ENTITY"))
        config = _make_live_config()
        enricher = LiveI18nEnricher(mock_llm, config=config)

        entity = _sample_entity("SOME_ENTITY", original_id)
        result = enricher.enrich_entity_live(entity)

        assert result.entity_id == original_id


class TestCanonicalNameUnchanged:
    def test_canonical_name_unchanged(self):
        """canonical_name is preserved from input entity, not overwritten by LLM."""
        original_canonical = "original_canonical_name"

        # LLM returns a response — but canonical_name must stay as input
        mock_llm = _make_mock_llm(_valid_llm_json("SOMETHING_ELSE"))
        config = _make_live_config()
        enricher = LiveI18nEnricher(mock_llm, config=config)

        entity = {
            "entity_id": "ent_x",
            "name": "SOMETHING_ELSE",
            "canonical_name": original_canonical,
            "entity_type": "table",
            "description": "",
            "degree": 1,
        }
        result = enricher.enrich_entity_live(entity)

        assert result.canonical_name == original_canonical


class TestCheckpointSave:
    def test_checkpoint_saved_every_n_entities(self, tmp_path):
        """Checkpoint file is written after processing checkpoint_every entities."""
        checkpoint = tmp_path / "ckpt.json"
        mock_llm = _make_mock_llm(_valid_llm_json())
        config = _make_live_config(checkpoint_every=3)
        enricher = LiveI18nEnricher(
            mock_llm, config=config, checkpoint_path=checkpoint
        )

        entities = [_sample_entity(f"E{i}", f"e{i}") for i in range(5)]
        enricher.batch_enrich_live(entities)

        assert checkpoint.exists()
        data = json.loads(checkpoint.read_text())
        assert len(data["processed_ids"]) == 5


class TestEntityI18nToDictNewFields:
    def test_to_dict_includes_all_new_fields(self):
        """EntityI18n.to_dict() includes all Phase 10C fields."""
        from hermes_bedrock_agent.graph.i18n_enricher import EntityI18n
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        e = EntityI18n(
            entity_id="x",
            name="X",
            canonical_name="x",
            entity_type="table",
            model_name="m",
            enriched_at=now,
            enrichment_source="live_llm",
            enrichment_confidence=0.8,
            enrichment_model="apac.model",
            enrichment_error="",
            updated_at=now,
            technical_aliases=["X", "x"],
            business_aliases_zh=["中文X"],
            business_aliases_en=["English X"],
            business_aliases_ja=["日本語X"],
        )
        d = e.to_dict()
        assert d["enrichment_source"] == "live_llm"
        assert d["enrichment_confidence"] == 0.8
        assert d["enrichment_model"] == "apac.model"
        assert d["enrichment_error"] == ""
        assert d["updated_at"] == now
        assert d["technical_aliases"] == ["X", "x"]
        assert d["business_aliases_zh"] == ["中文X"]
        assert d["business_aliases_en"] == ["English X"]
        assert d["business_aliases_ja"] == ["日本語X"]
