"""Tests for Phase 1 type-aware chunking strategy infrastructure.

Verifies:
1. Strategy protocol and dataclasses are importable and work
2. DefaultSemanticStrategy produces identical output to old code path
3. SingleChunkStrategy produces identical output to _SINGLE_CHUNK_TYPES
4. ChunkingStrategyRegistry selects correct strategy by metadata
5. Feature flag: build_chunks_from_parsed_dir unchanged when flag OFF
6. Feature flag: strategy dispatch active when flag ON
7. Backward compat: parsed/docs/ still discovered by chunker
8. New type dirs: parsed/pdf/, parsed/docx/, parsed/html/, parsed/txt/ discovered
9. Orchestrator _TYPE_SUBDIR_MAP normalization
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from hermes_bedrock_agent.config import Config
from hermes_bedrock_agent.knowledge_base.chunker import (
    _SINGLE_CHUNK_TYPES,
    _infer_chunk_type,
    _split_into_chunks,
    build_chunks_from_parsed_dir,
)
from hermes_bedrock_agent.knowledge_base.chunker_strategies import (
    ChunkConfig,
    ChunkMetadata,
    ChunkResult,
    ChunkingStrategy,
    ChunkingStrategyRegistry,
    select_strategy,
)
from hermes_bedrock_agent.knowledge_base.chunker_strategies.default import (
    DefaultSemanticStrategy,
    SingleChunkStrategy,
)
from hermes_bedrock_agent.knowledge_base.chunker_strategies.registry import (
    _SINGLE_CHUNK_SUBDIRS,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

EXCEL_FRONTMATTER = """\
---
project_id: "test_project"
source_file: "s3://bucket/workbook.xlsx"
source_type: "excel"
document_type: "mapping"
document_role: "data_mapping"
parser_type: "excel_vlm"
document_id: "abc123"
document_name: "sheet_01"
workbook_name: "TestWorkbook"
sheet_index: 1
sheet_name: "マッピング定義"
display_name: "Sheet 01 - Mapping"
unit_type: "sheet"
parser_version: "1.0"
evidence_path: "evidence/excel/TestWorkbook/sheet_01"
---
"""

EXCEL_BODY = """\
## マッピング定義

| No | 送信元項目名 | 送信先項目名 | 変換条件 | デフォルト値 |
|---|---|---|---|---|
| 1 | 発注番号 | ORDER_ID | そのまま | - |
| 2 | 発注日 | ORDER_DATE | YYYY-MM-DD変換 | 当日 |
| 3 | 発注先名 | SUPPLIER_NAME | マスタ参照 | - |
| 4 | 数量 | QUANTITY | 数値チェック | 0 |
| 5 | 単価 | UNIT_PRICE | 数値チェック | 0 |

## データ取得条件

発注ステータスが「確定」のレコードのみ抽出する。
取得条件: STATUS = 'CONFIRMED' AND DELETE_FLAG = 0

## 補足事項

- DataSpiderで中間ファイルを生成後、SAP連携する
- エラー時はリトライ3回まで実施
"""

MERMAID_FRONTMATTER = """\
---
project_id: "test_project"
source_file: "s3://bucket/flowchart.mmd"
source_type: "mermaid"
document_type: "flowchart"
document_role: "flowchart_source"
parser_type: "mermaid_parser"
document_id: "mermaid_001"
document_name: "mermaid_parsed"
parser_version: "2.1"
evidence_paths:
  - "intermediates/mermaid/mermaid_structure.json"
  - "intermediates/mermaid/mermaid_raw.mmd"
---
"""

MERMAID_BODY = """\
# Mermaid Flowchart Analysis

## Statistics
- Nodes: 10
- Edges: 12
- Subgraphs: 3

## Nodes

| ID | Label | Type |
|---|---|---|
| A | Start | terminal |
| B | Process 1 | process |
| C | Decision | diamond |
| D | End | terminal |

## Edges

| From | To | Label |
|---|---|---|
| A | B | begin |
| B | C | check |
| C | D | done |

## Original Mermaid

```mermaid
graph TD
    A[Start] --> B[Process 1]
    B --> C{Decision}
    C --> D[End]
```
"""

PDF_FRONTMATTER = """\
---
project_id: "test_project"
source_file: "s3://bucket/design.pdf"
source_type: "pdf"
document_role: "design_document"
parser_type: "pdf_vlm"
---
"""

PDF_BODY = """\
## 基本設計書

### 1. システム概要

本システムはEDI連携基盤として、発注情報の自動連携を実現する。
SAP S4/HANAからDataSpiderを経由してANDPADへデータを送信する。

### 2. 処理フロー

1. SAP側で発注データを抽出
2. 中間ファイル(CSV)に変換
3. DataSpiderで取込
4. ANDPAD APIへ送信
"""


def _make_parsed_dir(tmp_path: Path, subdirs: dict[str, dict[str, str]]) -> Path:
    """Create a parsed/ directory structure for testing.

    Args:
        subdirs: {type_name: {filename: content, ...}, ...}
    """
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir()
    for type_name, files in subdirs.items():
        type_dir = parsed_dir / type_name
        type_dir.mkdir(parents=True, exist_ok=True)
        for fname, content in files.items():
            (type_dir / fname).write_text(content, encoding="utf-8")
    return parsed_dir


def _cfg_flag_off() -> Config:
    """Config with strategy flag OFF (default behavior)."""
    cfg = Config()
    cfg.chunk_strategy_enabled = False
    return cfg


def _cfg_flag_on() -> Config:
    """Config with strategy flag ON (strategy dispatch active)."""
    cfg = Config()
    cfg.chunk_strategy_enabled = True
    return cfg


# ─── Protocol & Dataclass Tests ──────────────────────────────────────────────

class TestProtocol:
    def test_chunk_metadata_dataclass(self):
        meta = ChunkMetadata(
            source_type="excel",
            document_role="data_mapping",
            parsed_subdir="excel",
        )
        assert meta.source_type == "excel"
        assert meta.document_role == "data_mapping"
        assert meta.parsed_subdir == "excel"
        assert meta.project_id == ""  # default

    def test_chunk_config_defaults(self):
        cfg = ChunkConfig()
        assert cfg.max_chars == 4000
        assert cfg.min_chars == 100
        assert cfg.target_chars == 2000
        assert cfg.mode == "semantic"

    def test_chunk_result_dataclass(self):
        cr = ChunkResult(text="hello", chunk_type="overview")
        assert cr.text == "hello"
        assert cr.chunk_type == "overview"
        assert cr.embedding_text == ""
        assert cr.systems == []

    def test_default_semantic_strategy_implements_protocol(self):
        s = DefaultSemanticStrategy()
        assert isinstance(s, ChunkingStrategy)
        assert s.name == "default_semantic"

    def test_single_chunk_strategy_implements_protocol(self):
        s = SingleChunkStrategy()
        assert isinstance(s, ChunkingStrategy)
        assert s.name == "single_chunk"


# ─── DefaultSemanticStrategy Tests ───────────────────────────────────────────

class TestDefaultSemanticStrategy:
    def test_produces_chunks_for_excel_body(self):
        strategy = DefaultSemanticStrategy()
        meta = ChunkMetadata(source_type="excel", parsed_subdir="excel")
        config = ChunkConfig(max_chars=4000, min_chars=100, target_chars=2000, mode="semantic")
        results = strategy.chunk(EXCEL_BODY, meta, config)
        assert len(results) > 0
        for r in results:
            assert r.text.strip()
            assert r.chunk_type in ("mapping_table", "data_condition", "business_rule", "overview", "flowchart", "api_spec")

    def test_identical_to_inline_split(self):
        """DefaultSemanticStrategy must produce same text chunks as _split_into_chunks."""
        strategy = DefaultSemanticStrategy()
        meta = ChunkMetadata(source_type="excel", parsed_subdir="excel")
        config = ChunkConfig(max_chars=4000, min_chars=100, target_chars=2000, mode="semantic")
        results = strategy.chunk(EXCEL_BODY, meta, config)

        # Compare to direct call
        inline_chunks = _split_into_chunks(EXCEL_BODY, 4000, 100, mode="semantic", target=2000)
        strategy_texts = [r.text for r in results]
        assert strategy_texts == inline_chunks

    def test_chunk_type_matches_inline_inference(self):
        """chunk_type from strategy must match _infer_chunk_type for each chunk."""
        strategy = DefaultSemanticStrategy()
        meta = ChunkMetadata(source_type="excel", parsed_subdir="excel")
        config = ChunkConfig(max_chars=4000, min_chars=100, target_chars=2000, mode="semantic")
        results = strategy.chunk(EXCEL_BODY, meta, config)

        for r in results:
            expected_type = _infer_chunk_type(r.text)
            assert r.chunk_type == expected_type

    def test_empty_body_returns_empty(self):
        strategy = DefaultSemanticStrategy()
        meta = ChunkMetadata()
        config = ChunkConfig()
        assert strategy.chunk("", meta, config) == []
        assert strategy.chunk("   \n\n  ", meta, config) == []

    def test_body_below_min_returns_empty(self):
        """Body shorter than min_chars should not produce chunks."""
        strategy = DefaultSemanticStrategy()
        meta = ChunkMetadata()
        config = ChunkConfig(min_chars=500)
        results = strategy.chunk("short text", meta, config)
        assert results == []


# ─── SingleChunkStrategy Tests ───────────────────────────────────────────────

class TestSingleChunkStrategy:
    def test_returns_single_chunk(self):
        strategy = SingleChunkStrategy()
        meta = ChunkMetadata(source_type="mermaid", parsed_subdir="mermaid")
        config = ChunkConfig()
        results = strategy.chunk(MERMAID_BODY, meta, config)
        assert len(results) == 1
        assert results[0].text == MERMAID_BODY.strip()

    def test_infers_chunk_type(self):
        strategy = SingleChunkStrategy()
        meta = ChunkMetadata(source_type="mermaid", parsed_subdir="mermaid")
        config = ChunkConfig()
        results = strategy.chunk(MERMAID_BODY, meta, config)
        assert results[0].chunk_type == "flowchart"  # keyword: "flowchart" in body

    def test_empty_body_returns_empty(self):
        strategy = SingleChunkStrategy()
        meta = ChunkMetadata()
        config = ChunkConfig()
        assert strategy.chunk("", meta, config) == []


# ─── Registry Tests ──────────────────────────────────────────────────────────

class TestChunkingStrategyRegistry:
    def test_mermaid_selects_mermaid_flowchart(self):
        meta = ChunkMetadata(source_type="mermaid", parsed_subdir="mermaid")
        strategy = select_strategy(meta)
        assert strategy.name == "mermaid_flowchart"

    def test_images_selects_single_chunk(self):
        meta = ChunkMetadata(source_type="images", parsed_subdir="images")
        strategy = select_strategy(meta)
        assert strategy.name == "single_chunk"

    def test_excel_selects_default_semantic(self):
        meta = ChunkMetadata(source_type="excel", parsed_subdir="excel")
        strategy = select_strategy(meta)
        assert strategy.name == "default_semantic"

    def test_csv_selects_default_semantic(self):
        meta = ChunkMetadata(source_type="csv", parsed_subdir="csv")
        strategy = select_strategy(meta)
        assert strategy.name == "default_semantic"

    def test_code_selects_default_semantic(self):
        meta = ChunkMetadata(source_type="code", parsed_subdir="code")
        strategy = select_strategy(meta)
        assert strategy.name == "default_semantic"

    def test_pdf_selects_default_semantic(self):
        meta = ChunkMetadata(source_type="pdf", parsed_subdir="pdf")
        strategy = select_strategy(meta)
        assert strategy.name == "default_semantic"

    def test_unknown_type_selects_default(self):
        meta = ChunkMetadata(source_type="unknown", parsed_subdir="unknown")
        strategy = select_strategy(meta)
        assert strategy.name == "default_semantic"

    def test_parsed_subdir_mermaid_overrides_source_type(self):
        """Even if source_type is wrong, parsed_subdir 'mermaid' selects mermaid_flowchart."""
        meta = ChunkMetadata(source_type="excel", parsed_subdir="mermaid")
        strategy = select_strategy(meta)
        assert strategy.name == "mermaid_flowchart"

    def test_single_chunk_subdirs_subset_of_legacy(self):
        """_SINGLE_CHUNK_SUBDIRS is a subset of legacy _SINGLE_CHUNK_TYPES.

        Phase 2: Mermaid moved from single-chunk to MermaidFlowchartStrategy.
        The legacy set (flag OFF) still has mermaid, but the registry doesn't.
        """
        assert _SINGLE_CHUNK_SUBDIRS.issubset(_SINGLE_CHUNK_TYPES)
        assert "mermaid" in _SINGLE_CHUNK_TYPES  # flag OFF still single-chunks
        assert "mermaid" not in _SINGLE_CHUNK_SUBDIRS  # flag ON uses strategy


# ─── Feature Flag Integration Tests ─────────────────────────────────────────

class TestFeatureFlag:
    def test_flag_off_default(self):
        """Default config has strategy disabled."""
        cfg = Config()
        assert cfg.chunk_strategy_enabled is False

    def test_flag_on_via_env(self):
        """CHUNK_STRATEGY_ENABLED=true enables the flag."""
        with patch.dict(os.environ, {"CHUNK_STRATEGY_ENABLED": "true"}):
            cfg = Config()
            assert cfg.chunk_strategy_enabled is True

    def test_flag_off_via_env(self):
        """CHUNK_STRATEGY_ENABLED=false keeps default off."""
        with patch.dict(os.environ, {"CHUNK_STRATEGY_ENABLED": "false"}):
            cfg = Config()
            assert cfg.chunk_strategy_enabled is False


# ─── End-to-End: Flag OFF produces unchanged output ─────────────────────────

class TestFlagOffUnchangedOutput:
    def test_excel_chunks_identical_flag_off(self, tmp_path):
        """With flag OFF, excel chunking output is unchanged from original."""
        parsed_dir = _make_parsed_dir(tmp_path, {
            "excel": {"sheet_01.md": EXCEL_FRONTMATTER + EXCEL_BODY},
        })
        cfg = _cfg_flag_off()
        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg)
        assert len(chunks) > 0
        for c in chunks:
            assert c.project_id == "test_project"
            assert c.source_type == "excel"
            assert c.chunk_type in ("mapping_table", "data_condition", "business_rule", "overview")

    def test_mermaid_single_chunk_flag_off(self, tmp_path):
        """With flag OFF, mermaid is single-chunked (original behavior)."""
        parsed_dir = _make_parsed_dir(tmp_path, {
            "mermaid": {"mermaid_parsed.md": MERMAID_FRONTMATTER + MERMAID_BODY},
        })
        cfg = _cfg_flag_off()
        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg)
        assert len(chunks) == 1
        assert chunks[0].source_type == "mermaid"
        assert chunks[0].content == MERMAID_BODY.strip()

    def test_multi_type_flag_off(self, tmp_path):
        """With flag OFF, multiple types produce same results as before."""
        parsed_dir = _make_parsed_dir(tmp_path, {
            "excel": {"sheet_01.md": EXCEL_FRONTMATTER + EXCEL_BODY},
            "mermaid": {"mermaid_parsed.md": MERMAID_FRONTMATTER + MERMAID_BODY},
            "pdf": {"design.md": PDF_FRONTMATTER + PDF_BODY},
        })
        cfg = _cfg_flag_off()
        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg)
        source_types = {c.source_type for c in chunks}
        assert "excel" in source_types
        assert "mermaid" in source_types
        assert "pdf" in source_types


# ─── End-to-End: Flag ON uses strategy dispatch ──────────────────────────────

class TestFlagOnStrategyDispatch:
    def test_excel_chunks_identical_flag_on(self, tmp_path):
        """With flag ON + DefaultSemanticStrategy, excel output is identical."""
        parsed_dir = _make_parsed_dir(tmp_path, {
            "excel": {"sheet_01.md": EXCEL_FRONTMATTER + EXCEL_BODY},
        })
        cfg_off = _cfg_flag_off()
        cfg_on = _cfg_flag_on()
        chunks_off = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg_off)
        chunks_on = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg_on)

        assert len(chunks_off) == len(chunks_on)
        for c_off, c_on in zip(chunks_off, chunks_on):
            assert c_off.content == c_on.content
            assert c_off.chunk_type == c_on.chunk_type
            assert c_off.chunk_id == c_on.chunk_id
            assert c_off.embedding_text == c_on.embedding_text

    def test_mermaid_multi_chunk_flag_on(self, tmp_path):
        """With flag ON, mermaid uses MermaidFlowchartStrategy (different from flag OFF).

        Phase 2: Flag ON produces structured chunks, flag OFF still single-chunks.
        The test fixture is small so strategy produces 1 overview chunk,
        but with different chunk_type than the legacy single_chunk path.
        """
        parsed_dir = _make_parsed_dir(tmp_path, {
            "mermaid": {"mermaid_parsed.md": MERMAID_FRONTMATTER + MERMAID_BODY},
        })
        cfg_off = _cfg_flag_off()
        cfg_on = _cfg_flag_on()
        chunks_off = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg_off)
        chunks_on = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg_on)

        # Flag OFF: single chunk with legacy behavior
        assert len(chunks_off) == 1
        assert chunks_off[0].chunk_type == "flowchart"  # _infer_chunk_type default

        # Flag ON: MermaidFlowchartStrategy produces overview chunk
        assert len(chunks_on) >= 1
        # Content should be equivalent (small fixture → single chunk)
        assert chunks_on[0].content == chunks_off[0].content
        # But chunk_type reflects strategy
        assert chunks_on[0].chunk_type == "mermaid_overview"

    def test_pdf_chunks_identical_flag_on(self, tmp_path):
        """With flag ON, PDF chunking produces identical output."""
        parsed_dir = _make_parsed_dir(tmp_path, {
            "pdf": {"design.md": PDF_FRONTMATTER + PDF_BODY},
        })
        cfg_off = _cfg_flag_off()
        cfg_on = _cfg_flag_on()
        chunks_off = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg_off)
        chunks_on = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg_on)

        assert len(chunks_off) == len(chunks_on)
        for c_off, c_on in zip(chunks_off, chunks_on):
            assert c_off.content == c_on.content
            assert c_off.chunk_id == c_on.chunk_id


# ─── Directory Normalization Tests ───────────────────────────────────────────

class TestDirectoryNormalization:
    def test_parsed_docs_still_discovered(self, tmp_path):
        """Legacy parsed/docs/ directory is still discovered by chunker."""
        parsed_dir = _make_parsed_dir(tmp_path, {
            "docs": {"design.md": PDF_FRONTMATTER + PDF_BODY},
        })
        cfg = _cfg_flag_off()
        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg)
        assert len(chunks) > 0
        # source_type comes from frontmatter, not directory name
        assert chunks[0].source_type == "pdf"

    def test_parsed_pdf_discovered(self, tmp_path):
        """New canonical parsed/pdf/ directory is discovered."""
        parsed_dir = _make_parsed_dir(tmp_path, {
            "pdf": {"design.md": PDF_FRONTMATTER + PDF_BODY},
        })
        cfg = _cfg_flag_off()
        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg)
        assert len(chunks) > 0
        assert chunks[0].source_type == "pdf"

    def test_parsed_docx_discovered(self, tmp_path):
        """New canonical parsed/docx/ directory is discovered."""
        docx_fm = "---\nsource_type: docx\nparser_type: docx\nproject_id: test\n---\n"
        body = "## Document\n\nThis is a Word document with enough content for a chunk to be generated from it. " * 3
        parsed_dir = _make_parsed_dir(tmp_path, {
            "docx": {"report.md": docx_fm + body},
        })
        cfg = _cfg_flag_off()
        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test", cfg=cfg)
        assert len(chunks) > 0
        assert chunks[0].source_type == "docx"

    def test_parsed_html_discovered(self, tmp_path):
        """New canonical parsed/html/ directory is discovered."""
        html_fm = "---\nsource_type: html\nparser_type: html\nproject_id: test\n---\n"
        body = "## Web Page\n\nThis is HTML content converted to markdown with sufficient length. " * 3
        parsed_dir = _make_parsed_dir(tmp_path, {
            "html": {"page.md": html_fm + body},
        })
        cfg = _cfg_flag_off()
        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test", cfg=cfg)
        assert len(chunks) > 0
        assert chunks[0].source_type == "html"

    def test_parsed_txt_discovered(self, tmp_path):
        """New canonical parsed/txt/ directory is discovered."""
        txt_fm = "---\nsource_type: txt\nparser_type: text\nproject_id: test\n---\n"
        body = "## Plain Text\n\nThis is a plain text file that was ingested and converted to markdown. " * 3
        parsed_dir = _make_parsed_dir(tmp_path, {
            "txt": {"readme.md": txt_fm + body},
        })
        cfg = _cfg_flag_off()
        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test", cfg=cfg)
        assert len(chunks) > 0
        assert chunks[0].source_type == "txt"

    def test_all_canonical_dirs_together(self, tmp_path):
        """All canonical type dirs can coexist and be discovered."""
        excel_content = EXCEL_FRONTMATTER + EXCEL_BODY
        mermaid_content = MERMAID_FRONTMATTER + MERMAID_BODY
        pdf_content = PDF_FRONTMATTER + PDF_BODY
        csv_fm = "---\nsource_type: csv\nparser_type: csv\nproject_id: test_project\n---\n"
        csv_body = "## CSV Fields\n\n| Field | Type | Description |\n|---|---|---|\n| id | int | Primary key |\n| name | str | Customer name |\n" * 5
        code_fm = "---\nsource_type: code\nparser_type: code\nproject_id: test_project\n---\n"
        code_body = "## Code Summary\n\n```python\ndef process_order(order_id):\n    # Process order logic here\n    pass\n```\n" * 5

        parsed_dir = _make_parsed_dir(tmp_path, {
            "excel": {"sheet_01.md": excel_content},
            "mermaid": {"mermaid_parsed.md": mermaid_content},
            "pdf": {"design.md": pdf_content},
            "csv": {"fields.md": csv_fm + csv_body},
            "code": {"main.md": code_fm + code_body},
        })
        cfg = _cfg_flag_off()
        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg)
        source_types = {c.source_type for c in chunks}
        assert "excel" in source_types
        assert "mermaid" in source_types
        assert "pdf" in source_types
        assert "csv" in source_types
        assert "code" in source_types


# ─── Orchestrator _TYPE_SUBDIR_MAP Tests ─────────────────────────────────────

class TestOrchestratorTypeMap:
    def test_pdf_vlm_maps_to_pdf(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("pdf_vlm") == "pdf"

    def test_doc_vlm_maps_to_pdf(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("doc_vlm") == "pdf"

    def test_docx_maps_to_docx(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("docx") == "docx"

    def test_html_maps_to_html(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("html") == "html"

    def test_text_maps_to_txt(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("text") == "txt"

    def test_markdown_maps_to_txt(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("markdown") == "txt"

    def test_csv_maps_to_csv(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("csv") == "csv"

    def test_code_maps_to_code(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("code") == "code"

    def test_excel_vlm_maps_to_excel(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("excel_vlm") == "excel"

    def test_mermaid_maps_to_mermaid(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("mermaid") == "mermaid"

    def test_unknown_type_maps_to_txt(self):
        from hermes_bedrock_agent.parsing.orchestrator import _get_type_subdir
        assert _get_type_subdir("unknown_parser") == "txt"

    def test_no_docs_in_map(self):
        """'docs' should not appear as a value in the new type map."""
        from hermes_bedrock_agent.parsing.orchestrator import _TYPE_SUBDIR_MAP
        assert "docs" not in _TYPE_SUBDIR_MAP.values()


# ─── Strategy Metadata Propagation Tests ─────────────────────────────────────

class TestStrategyMetadataPropagation:
    def test_strategy_receives_correct_metadata(self, tmp_path):
        """When flag ON, strategy receives all frontmatter fields."""
        parsed_dir = _make_parsed_dir(tmp_path, {
            "excel": {"sheet_01.md": EXCEL_FRONTMATTER + EXCEL_BODY},
        })
        cfg = _cfg_flag_on()

        # Monkey-patch to capture metadata
        captured_meta = []
        orig_select = select_strategy.__wrapped__ if hasattr(select_strategy, "__wrapped__") else None

        from hermes_bedrock_agent.knowledge_base import chunker_strategies
        original_select = chunker_strategies.registry.select_strategy

        def capturing_select(meta):
            captured_meta.append(meta)
            return original_select(meta)

        with patch("hermes_bedrock_agent.knowledge_base.chunker_strategies.select_strategy", capturing_select):
            chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_project", cfg=cfg)

        assert len(captured_meta) == 1
        m = captured_meta[0]
        assert m.source_type == "excel"
        assert m.document_role == "data_mapping"
        assert m.parser_type == "excel_vlm"
        assert m.document_id == "abc123"
        assert m.parsed_subdir == "excel"
        assert m.workbook_name == "TestWorkbook"
        assert m.sheet_name == "マッピング定義"
        assert m.sheet_index == 1
