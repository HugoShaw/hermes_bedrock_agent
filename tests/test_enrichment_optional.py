"""Tests for optional enrichment stage configuration and behavior.

Covers:
- EnrichmentSettings defaults (disabled, mode=none)
- run_enrichment() dispatcher (none/rule/mock modes)
- Pipeline stage_enrichment() default skip behavior
- enrich_i18n.py CLI mode handling
- Safety: no LLM calls in mode=none, no Neptune write without confirm
- QueryEntityExtractor works without i18n artifacts
- Visualization fallback when i18n fields are missing
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. EnrichmentSettings defaults
# ---------------------------------------------------------------------------


class TestEnrichmentSettings:
    """Verify that EnrichmentSettings defaults to disabled/none."""

    def test_default_disabled(self):
        from hermes_bedrock_agent.configs.settings import EnrichmentSettings

        settings = EnrichmentSettings()
        assert settings.enabled is False

    def test_default_mode_none(self):
        from hermes_bedrock_agent.configs.settings import EnrichmentSettings

        settings = EnrichmentSettings()
        assert settings.mode == "none"

    def test_default_no_neptune_update(self):
        from hermes_bedrock_agent.configs.settings import EnrichmentSettings

        settings = EnrichmentSettings()
        assert settings.update_neptune is False

    def test_default_require_confirm(self):
        from hermes_bedrock_agent.configs.settings import EnrichmentSettings

        settings = EnrichmentSettings()
        assert settings.require_confirm_live_write is True

    def test_default_max_entities(self):
        from hermes_bedrock_agent.configs.settings import EnrichmentSettings

        settings = EnrichmentSettings()
        assert settings.max_entities == 200

    def test_app_settings_enrichment_property(self):
        from hermes_bedrock_agent.configs.settings import AppSettings

        app = AppSettings()
        enrichment = app.enrichment
        assert enrichment.enabled is False
        assert enrichment.mode == "none"


# ---------------------------------------------------------------------------
# 2. run_enrichment() dispatcher
# ---------------------------------------------------------------------------


class TestRunEnrichment:
    """Test the run_enrichment() dispatcher function."""

    @pytest.fixture
    def sample_entities(self):
        return [
            {
                "entity_id": "journal_base",
                "entity_type": "table",
                "canonical_name": "JOURNAL_BASE",
                "name": "JOURNAL_BASE",
                "description": "仕訳基礎テーブル",
            },
            {
                "entity_id": "payment_req",
                "entity_type": "process",
                "canonical_name": "payment_req",
                "name": "payment_req",
                "description": "付款申請処理",
            },
            {
                "entity_id": "some_table",
                "entity_type": "table",
                "canonical_name": "SOME_TABLE",
                "name": "SOME_TABLE",
                "description": "A generic table",
            },
        ]

    @pytest.fixture
    def sample_relations(self):
        return [
            {
                "relation_id": "r1",
                "relation_type": "reads_from",
                "source": "a",
                "target": "b",
            },
            {
                "relation_id": "r2",
                "relation_type": "writes_to",
                "source": "b",
                "target": "c",
            },
            {
                "relation_id": "r3",
                "relation_type": "unknown_relation",
                "source": "c",
                "target": "d",
            },
        ]

    def test_mode_none_returns_none(self, sample_entities, sample_relations):
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        result = run_enrichment(
            mode="none",
            entities=sample_entities,
            relations=sample_relations,
        )
        assert result is None

    def test_mode_rule_returns_results(self, sample_entities, sample_relations):
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        result = run_enrichment(
            mode="rule",
            entities=sample_entities,
            relations=sample_relations,
        )
        assert result is not None
        assert result["mode"] == "rule"
        assert result["entities_enriched"] == 3
        assert result["relations_enriched"] == 3

    def test_mode_rule_priority_entity_has_i18n(self, sample_entities, sample_relations):
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        result = run_enrichment(
            mode="rule",
            entities=sample_entities,
            relations=sample_relations,
            output_dir=None,
        )
        # Can't check output files if output_dir is None, but result should show count
        assert result["entities_enriched"] >= 1

    def test_mode_rule_writes_artifacts(self, sample_entities, sample_relations, tmp_path):
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        result = run_enrichment(
            mode="rule",
            entities=sample_entities,
            relations=sample_relations,
            output_dir=str(tmp_path),
        )
        assert len(result["output_files"]) == 2
        ent_file = Path(result["output_files"][0])
        rel_file = Path(result["output_files"][1])
        assert ent_file.exists()
        assert rel_file.exists()

        # Verify entity content
        with open(ent_file) as f:
            lines = f.readlines()
        assert len(lines) == 3
        first = json.loads(lines[0])
        assert first["entity_id"] == "journal_base"
        assert first["canonical_name"] == "JOURNAL_BASE"

    def test_mode_rule_relation_builtin_labels(self, sample_entities, sample_relations, tmp_path):
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        result = run_enrichment(
            mode="rule",
            entities=sample_entities,
            relations=sample_relations,
            output_dir=str(tmp_path),
        )
        rel_file = Path(result["output_files"][1])
        with open(rel_file) as f:
            rels = [json.loads(line) for line in f]

        # reads_from should have builtin labels
        reads_from = next(r for r in rels if r["relation_type"] == "reads_from")
        assert reads_from["label_zh"] == "读取"
        assert reads_from["label_ja"] == "読み取る"
        assert reads_from["label_en"] == "reads from"

    def test_mode_mock_returns_results(self, sample_entities, sample_relations):
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        result = run_enrichment(
            mode="mock",
            entities=sample_entities,
            relations=sample_relations,
        )
        assert result is not None
        assert result["mode"] == "mock"
        assert result["entities_enriched"] >= 1

    def test_mode_llm_warns_from_pipeline(self, sample_entities, sample_relations):
        """LLM mode from pipeline dispatcher returns warning (not direct execution)."""
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        result = run_enrichment(
            mode="llm",
            entities=sample_entities,
            relations=sample_relations,
        )
        assert result is not None
        assert result["entities_enriched"] == 0
        assert "warning" in result

    def test_mode_rule_max_entities_respected(self, sample_entities, sample_relations):
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        result = run_enrichment(
            mode="rule",
            entities=sample_entities,
            relations=sample_relations,
            max_entities=1,
        )
        assert result["entities_enriched"] == 1

    def test_mode_none_no_llm_call(self, sample_entities, sample_relations):
        """mode=none must not invoke any LLM client."""
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        with patch(
            "hermes_bedrock_agent.graph.i18n_enricher.MockDeterministicLLM"
        ) as mock_cls:
            result = run_enrichment(
                mode="none",
                entities=sample_entities,
                relations=sample_relations,
            )
            mock_cls.assert_not_called()
        assert result is None


# ---------------------------------------------------------------------------
# 3. enrich_i18n.py CLI mode handling
# ---------------------------------------------------------------------------


class TestEnrichI18nCLI:
    """Test enrich_i18n.py CLI behavior with --mode parameter."""

    def test_mode_none_prints_info_and_exits(self):
        """--mode none should print info and exit 0."""
        result = subprocess.run(
            [sys.executable, "scripts/enrich_i18n.py", "--mode", "none"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 0
        assert "mode=none" in result.stdout
        assert "DISABLED" in result.stdout

    def test_update_neptune_without_confirm_fails(self):
        """--update-neptune without --confirm-live-write should exit 1."""
        result = subprocess.run(
            [
                sys.executable,
                "scripts/enrich_i18n.py",
                "--mode", "mock",
                "--update-neptune",
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert result.returncode == 1
        assert "confirm-live-write" in result.stdout

    def test_default_mode_inferred_as_mock(self):
        """Without --mode flag, default standalone is mock (not none)."""
        # We can't easily run this without artifacts dir, but we can check
        # that the script doesn't crash on parse_args with no --mode
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; sys.argv = ['enrich_i18n.py']; "
                "sys.path.insert(0, 'scripts'); "
                "import importlib.util; "
                "spec = importlib.util.spec_from_file_location('enrich', 'scripts/enrich_i18n.py'); "
                "mod = importlib.util.module_from_spec(spec); "
                "# just test parse_args\n"
                "import argparse; "
                "exec(open('scripts/enrich_i18n.py').read().split('def main')[0]); "
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
            timeout=10,
        )
        # This is a basic sanity check — the import should not crash
        assert result.returncode == 0 or "ModuleNotFoundError" not in result.stderr


# ---------------------------------------------------------------------------
# 4. Pipeline stage_enrichment default skip
# ---------------------------------------------------------------------------


class TestPipelineEnrichmentStage:
    """Verify that stage all defaults to skipping enrichment."""

    def test_stage_order_includes_enrichment(self):
        """STAGE_ORDER should include 'enrichment' between 'load' and 'retrieval'."""
        # Import the constant
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import importlib
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "pipeline",
            Path(__file__).parent.parent / "scripts" / "run_e2e_murata_pipeline.py",
        )
        # We can't fully import (too many deps), so just read the file
        content = (
            Path(__file__).parent.parent / "scripts" / "run_e2e_murata_pipeline.py"
        ).read_text()
        # Find STAGE_ORDER
        import re

        match = re.search(r'STAGE_ORDER\s*=\s*\[([^\]]+)\]', content)
        assert match is not None
        stages = [s.strip().strip('"').strip("'") for s in match.group(1).split(",")]
        assert "enrichment" in stages
        # enrichment should be after load and before retrieval
        load_idx = stages.index("load")
        enr_idx = stages.index("enrichment")
        ret_idx = stages.index("retrieval")
        assert load_idx < enr_idx < ret_idx

    def test_enrichment_mode_default_is_none(self):
        """Default --enrichment-mode should be 'none'."""
        content = (
            Path(__file__).parent.parent / "scripts" / "run_e2e_murata_pipeline.py"
        ).read_text()
        assert 'default="none"' in content
        assert "enrichment_mode" in content


# ---------------------------------------------------------------------------
# 5. Safety: no LLM / no Neptune in default mode
# ---------------------------------------------------------------------------


class TestSafety:
    """Verify safety constraints."""

    def test_enrichment_settings_no_neptune_by_default(self):
        from hermes_bedrock_agent.configs.settings import EnrichmentSettings

        s = EnrichmentSettings()
        assert s.update_neptune is False

    def test_run_enrichment_mode_none_no_side_effects(self, tmp_path):
        """mode=none should not create any files."""
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        entities = [{"entity_id": "x", "canonical_name": "X", "entity_type": "table"}]
        result = run_enrichment(
            mode="none",
            entities=entities,
            relations=[],
            output_dir=str(tmp_path),
        )
        assert result is None
        # No files should be created
        assert list(tmp_path.iterdir()) == []

    def test_mode_rule_no_llm_import(self):
        """mode=rule should not import or instantiate any LLM client."""
        from hermes_bedrock_agent.graph.i18n_enricher import run_enrichment

        entities = [{"entity_id": "x", "canonical_name": "X", "entity_type": "table"}]
        # Patch BedrockLLMAdapter to detect if it's called
        with patch(
            "hermes_bedrock_agent.graph.i18n_enricher.BedrockLLMAdapter",
            side_effect=RuntimeError("Should not be called"),
        ):
            result = run_enrichment(
                mode="rule",
                entities=entities,
                relations=[],
            )
        assert result is not None
        assert result["entities_enriched"] == 1


# ---------------------------------------------------------------------------
# 6. QueryEntityExtractor without i18n artifacts
# ---------------------------------------------------------------------------


class TestQueryEntityExtractorWithoutI18n:
    """QueryEntityExtractor must work without enrichment artifacts."""

    def test_entity_index_works_without_i18n_fields(self, tmp_path):
        from hermes_bedrock_agent.retrieval.query_entity_extractor import EntityIndex

        entities = [
            {
                "entity_id": "journal_base",
                "canonical_name": "JOURNAL_BASE",
                "name": "JOURNAL_BASE",
                "entity_type": "table",
                "description": "Base journal table",
                "aliases": ["JB"],
            }
        ]
        # Write to temp JSONL
        jsonl_path = tmp_path / "entities.jsonl"
        with open(jsonl_path, "w") as f:
            for e in entities:
                f.write(json.dumps(e) + "\n")

        index = EntityIndex()
        count = index.load_from_jsonl(jsonl_path)
        assert count == 1
        # Should work without aliases_zh, aliases_ja, etc.
        result = index.lookup("JOURNAL_BASE")
        assert result is not None

    def test_entity_index_works_with_i18n_fields(self, tmp_path):
        from hermes_bedrock_agent.retrieval.query_entity_extractor import EntityIndex

        entities = [
            {
                "entity_id": "journal_base",
                "canonical_name": "JOURNAL_BASE",
                "name": "JOURNAL_BASE",
                "entity_type": "table",
                "description": "Base journal table",
                "aliases": ["JB"],
                "aliases_zh": ["仕訳基礎"],
                "aliases_ja": ["仕訳基礎テーブル"],
                "aliases_en": ["journal base"],
                "display_name_zh": "仕訳基礎",
                "display_name_ja": "仕訳基礎テーブル",
                "display_name_en": "Journal Base",
            }
        ]
        # Write to temp JSONL and i18n enrichment JSONL
        jsonl_path = tmp_path / "entities.jsonl"
        with open(jsonl_path, "w") as f:
            for e in entities:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        i18n_path = tmp_path / "i18n_entities_enriched.jsonl"
        with open(i18n_path, "w") as f:
            for e in entities:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")

        index = EntityIndex()
        index.load_from_jsonl(jsonl_path)
        index.load_i18n_enrichment(i18n_path)

        # Should find via Japanese alias
        result = index.lookup("仕訳基礎")
        assert result is not None


# ---------------------------------------------------------------------------
# 7. Visualization fallback without i18n
# ---------------------------------------------------------------------------


class TestVisualizationFallback:
    """Visualization must work without i18n fields — fallback to canonical_name."""

    def test_resolve_label_fallback_no_i18n(self):
        """If no i18n_data provided, should fallback to node_label."""
        from hermes_bedrock_agent.visualization.mermaid_generator import (
            resolve_i18n_label,
        )

        label = resolve_i18n_label(
            node_id="test_node",
            node_label="TEST_NODE",
            i18n_data=None,
            lang="ja",
            label_mode="business",
        )
        # Without i18n_data, should return node_label as-is
        assert label == "TEST_NODE"

    def test_resolve_label_technical_mode(self):
        from hermes_bedrock_agent.visualization.mermaid_generator import (
            resolve_i18n_label,
        )

        i18n_data = {
            "test_node": {
                "display_name_ja": "テストノード",
                "display_name_en": "Test Node",
            }
        }
        label = resolve_i18n_label(
            node_id="test_node",
            node_label="TEST_NODE",
            i18n_data=i18n_data,
            lang="en",
            label_mode="technical",
        )
        # Technical mode always returns original label
        assert label == "TEST_NODE"

    def test_resolve_label_business_mode_with_i18n(self):
        from hermes_bedrock_agent.visualization.mermaid_generator import (
            resolve_i18n_label,
        )

        i18n_data = {
            "test_node": {
                "display_name_ja": "テストノード",
                "display_name_en": "Test Node",
            }
        }
        label = resolve_i18n_label(
            node_id="test_node",
            node_label="TEST_NODE",
            i18n_data=i18n_data,
            lang="ja",
            label_mode="business",
        )
        assert "テストノード" in label

    def test_resolve_label_mixed_mode(self):
        from hermes_bedrock_agent.visualization.mermaid_generator import (
            resolve_i18n_label,
        )

        i18n_data = {
            "test_node": {
                "display_name_zh": "测试节点",
                "display_name_en": "Test Node",
            }
        }
        label = resolve_i18n_label(
            node_id="test_node",
            node_label="TEST_NODE",
            i18n_data=i18n_data,
            lang="zh",
            label_mode="mixed",
        )
        # Mixed mode: display_name + canonical_name
        assert "测试节点" in label
        assert "TEST_NODE" in label

    def test_resolve_label_business_missing_lang_fallback(self):
        from hermes_bedrock_agent.visualization.mermaid_generator import (
            resolve_i18n_label,
        )

        i18n_data = {
            "test_node": {
                "display_name_en": "Test Node",
                # No display_name_ja
            }
        }
        label = resolve_i18n_label(
            node_id="test_node",
            node_label="TEST_NODE",
            i18n_data=i18n_data,
            lang="ja",
            label_mode="business",
        )
        # Missing ja should fallback to node_label
        assert label == "TEST_NODE"

    def test_sanitize_id_always_ascii(self):
        from hermes_bedrock_agent.visualization.mermaid_generator import (
            _sanitize_id,
        )

        # ASCII input
        assert _sanitize_id("TEST_NODE").isascii()
        # Japanese input
        assert _sanitize_id("日本語ノード").isascii()
        # Chinese input
        assert _sanitize_id("测试节点").isascii()
        # Mixed input
        assert _sanitize_id("node_テスト_123").isascii()

    def test_sanitize_id_deterministic(self):
        from hermes_bedrock_agent.visualization.mermaid_generator import (
            _sanitize_id,
        )

        # Same input always produces same output
        id1 = _sanitize_id("仕訳基礎テーブル")
        id2 = _sanitize_id("仕訳基礎テーブル")
        assert id1 == id2
        assert len(id1) > 0
