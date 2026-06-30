"""Tests for Mermaid unified output structure.

Validates:
1. UnifiedOutputWriter.write_mermaid_parsed() creates parsed/mermaid/mermaid_parsed.md
2. Mermaid technical files go to intermediates/mermaid/
3. parsing_manifest.json includes Mermaid parsed document
4. Chunker discovers parsed/mermaid/mermaid_parsed.md
5. Frontmatter is stripped from chunk text and preserved in metadata
6. No raw technical artifacts are treated as chunk-ready parsed documents
7. manifest.json includes Mermaid section with intermediates paths
8. Behavior is automatic (no manual patching needed)
"""

import json
import tempfile
from pathlib import Path

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: UnifiedOutputWriter generates parsed/mermaid/mermaid_parsed.md
# ─────────────────────────────────────────────────────────────────────────────


class TestMermaidParsedGeneration:
    """Validate that write_mermaid_parsed creates the canonical output."""

    def _make_mock_results(self):
        """Create mock MermaidParseResult-like objects for testing."""
        from hermes_bedrock_agent.parsing.mermaid_parser import (
            MermaidParseResult, MermaidNode, MermaidEdge, MermaidSubgraph,
        )

        nodes = [
            MermaidNode(id="N1", label="開始", node_type="terminal", subgraph="R1"),
            MermaidNode(id="N2", label="データ取得", node_type="process", subgraph="R1"),
            MermaidNode(id="N3", label="検証", node_type="decision", subgraph="R2"),
            MermaidNode(id="N4", label="完了", node_type="terminal", subgraph="R2"),
        ]
        edges = [
            MermaidEdge(source="N1", target="N2", label="開始"),
            MermaidEdge(source="N2", target="N3", label=None),
            MermaidEdge(source="N3", target="N4", label="OK"),
        ]
        subgraphs = [
            MermaidSubgraph(id="R1", label="入力処理", nodes=["N1", "N2"]),
            MermaidSubgraph(id="R2", label="検証処理", nodes=["N3", "N4"]),
        ]

        result = MermaidParseResult(
            source_path="/tmp/test.mmd",
            source_type="mmd_file",
            title="Flowchart: 入力処理",
            diagram_type="flowchart",
            nodes=nodes,
            edges=edges,
            subgraphs=subgraphs,
            raw_content='flowchart TD\n  N1(["開始"]) --> N2["データ取得"]',
            markdown_summary="# Test Summary",
            output_dir="/tmp/out",
        )
        return result

    def _make_mock_link(self):
        """Create mock FlowchartLink for testing."""
        from hermes_bedrock_agent.parsing.flowchart_linker import FlowchartLink
        return FlowchartLink(
            mermaid_source="/tmp/test.mmd",
            excel_workbook="MW_IFマッピング表",
            excel_sheet="sheet_01",
            match_confidence=0.7,
            match_reason="filename_match(0.7)",
            mermaid_preferred=True,
        )

    def test_write_mermaid_parsed_creates_file(self, tmp_path):
        """write_mermaid_parsed creates parsed/mermaid/mermaid_parsed.md."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_project")

        result = self._make_mock_results()
        link = self._make_mock_link()
        mermaid_results = [("flowchart", "path/to/test.mmd", result)]
        links = [link]

        mr = writer.write_mermaid_parsed(mermaid_results, links, source_s3_prefix="s3://bucket/prefix/")

        # Check file was created
        parsed_path = run_dir / "parsed" / "mermaid" / "mermaid_parsed.md"
        assert parsed_path.exists(), "parsed/mermaid/mermaid_parsed.md must exist"
        assert mr.parsed_path == str(parsed_path)
        assert mr.node_count == 4
        assert mr.edge_count == 3
        assert mr.subgraph_count == 2

    def test_mermaid_parsed_has_frontmatter(self, tmp_path):
        """parsed/mermaid/mermaid_parsed.md has correct YAML frontmatter."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "my_project_id")

        result = self._make_mock_results()
        link = self._make_mock_link()
        mermaid_results = [("flowchart", "サンプル/test.mmd", result)]

        writer.write_mermaid_parsed(mermaid_results, [link], source_s3_prefix="s3://bucket/prefix/")

        content = (run_dir / "parsed" / "mermaid" / "mermaid_parsed.md").read_text(encoding="utf-8")

        # Verify frontmatter structure
        assert content.startswith("---\n")
        assert 'project_id: "my_project_id"' in content
        assert 'source_type: "mermaid"' in content
        assert 'document_type: "flowchart"' in content
        assert 'document_role: "flowchart_source"' in content
        assert 'parser_type: "mermaid_parser"' in content
        assert 'parser_version: "2.1"' in content
        assert 'document_id: "' in content
        assert 'document_name: "mermaid_parsed"' in content
        assert 'display_name: "Mermaid Flowchart"' in content
        assert 'linked_excel_workbook: "MW_IFマッピング表"' in content
        assert 'linked_excel_sheet: "sheet_01"' in content
        assert "linkage_confidence: 0.70" in content
        assert "mermaid_preferred: true" in content
        assert 'evidence_paths:' in content
        assert '"intermediates/mermaid/mermaid_structure.json"' in content
        assert '"intermediates/mermaid/mermaid_raw.mmd"' in content

    def test_mermaid_parsed_has_required_frontmatter_fields(self, tmp_path):
        """All required frontmatter fields are present."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter
        import yaml

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_proj")

        result = self._make_mock_results()
        mermaid_results = [("flowchart", "path/to/test.mmd", result)]

        writer.write_mermaid_parsed(mermaid_results, [], source_s3_prefix="s3://bucket/p/")

        content = (run_dir / "parsed" / "mermaid" / "mermaid_parsed.md").read_text(encoding="utf-8")
        # Parse frontmatter
        end = content.find("\n---\n", 4)
        fm_text = content[4:end]
        fm = yaml.safe_load(fm_text)

        required_fields = {
            "project_id", "source_file", "source_type", "document_type",
            "document_role", "parser_type", "parser_version", "document_id",
            "document_name", "original_relative_path", "display_name",
            "linked_excel_workbook", "linked_excel_sheet", "linkage_confidence",
            "mermaid_preferred", "parsed_at", "evidence_paths",
        }
        missing = required_fields - set(fm.keys())
        assert not missing, f"Missing frontmatter fields: {missing}"

    def test_mermaid_parsed_body_is_searchable(self, tmp_path):
        """Body contains searchable node labels, edge info, and mermaid block."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_proj")

        result = self._make_mock_results()
        mermaid_results = [("flowchart", "path/to/test.mmd", result)]

        writer.write_mermaid_parsed(mermaid_results, [])

        content = (run_dir / "parsed" / "mermaid" / "mermaid_parsed.md").read_text(encoding="utf-8")

        # Body should contain node labels for searchability
        assert "開始" in content
        assert "データ取得" in content
        assert "検証" in content
        assert "完了" in content
        # Should contain Mermaid block
        assert "```mermaid" in content
        # Should contain tables
        assert "| ID | Label | Type | Subgraph |" in content
        assert "| Source | Target | Label |" in content
        # Should contain business flow
        assert "Business Flow" in content

    def test_mermaid_parsed_no_results_returns_empty(self, tmp_path):
        """write_mermaid_parsed with no results returns empty MermaidResult."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_proj")

        mr = writer.write_mermaid_parsed([], [])
        assert mr.parsed_path == ""
        assert mr.node_count == 0
        assert not (run_dir / "parsed" / "mermaid").exists()


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: Technical artifacts go to intermediates/mermaid/
# ─────────────────────────────────────────────────────────────────────────────


class TestMermaidIntermediates:
    """Validate technical Mermaid artifacts are in intermediates/, not parsed/."""

    def _make_mock_results(self):
        from hermes_bedrock_agent.parsing.mermaid_parser import (
            MermaidParseResult, MermaidNode, MermaidEdge, MermaidSubgraph,
        )
        return MermaidParseResult(
            source_path="/tmp/test.mmd",
            source_type="mmd_file",
            title="Test",
            diagram_type="flowchart",
            nodes=[MermaidNode(id="N1", label="A", node_type="process")],
            edges=[MermaidEdge(source="N1", target="N1")],
            subgraphs=[],
            raw_content="flowchart TD\n  N1[A]",
            markdown_summary="# Test",
            output_dir="/tmp",
        )

    def test_intermediates_directory_created(self, tmp_path):
        """intermediates/mermaid/ is created with raw and structure files."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_proj")

        result = self._make_mock_results()
        mermaid_results = [("diagram1", "path/file.mmd", result)]

        writer.write_mermaid_parsed(mermaid_results, [])

        intermediates_dir = run_dir / "intermediates" / "mermaid"
        assert intermediates_dir.exists()
        assert (intermediates_dir / "mermaid_raw.mmd").exists()
        assert (intermediates_dir / "mermaid_structure.json").exists()
        assert (intermediates_dir / "diagram1_raw.mmd").exists()

    def test_structure_json_valid(self, tmp_path):
        """intermediates/mermaid/mermaid_structure.json is valid JSON with expected keys."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_proj")

        result = self._make_mock_results()
        mermaid_results = [("diagram1", "path/file.mmd", result)]

        writer.write_mermaid_parsed(mermaid_results, [])

        structure_path = run_dir / "intermediates" / "mermaid" / "mermaid_structure.json"
        data = json.loads(structure_path.read_text())
        assert "total_nodes" in data
        assert "total_edges" in data
        assert "total_subgraphs" in data
        assert "diagrams" in data
        assert data["total_nodes"] == 1
        assert data["total_edges"] == 1

    def test_linkage_report_in_intermediates(self, tmp_path):
        """Linkage report is written to intermediates/mermaid/."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter
        from hermes_bedrock_agent.parsing.flowchart_linker import FlowchartLink

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_proj")

        result = self._make_mock_results()
        link = FlowchartLink(
            mermaid_source="/tmp/test.mmd",
            excel_workbook="WB1",
            match_confidence=0.5,
        )
        mermaid_results = [("diagram1", "path/file.mmd", result)]

        writer.write_mermaid_parsed(mermaid_results, [link])

        linkage_path = run_dir / "intermediates" / "mermaid" / "linkage_report.json"
        assert linkage_path.exists()
        data = json.loads(linkage_path.read_text())
        assert isinstance(data, list)
        assert data[0]["excel_workbook"] == "WB1"

    def test_no_technical_artifacts_in_parsed(self, tmp_path):
        """No .json, .mmd, or debug files in parsed/mermaid/."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_proj")

        result = self._make_mock_results()
        mermaid_results = [("diagram1", "path/file.mmd", result)]

        writer.write_mermaid_parsed(mermaid_results, [])

        parsed_dir = run_dir / "parsed" / "mermaid"
        # Only .md files should be in parsed/
        all_files = list(parsed_dir.rglob("*"))
        non_md = [f for f in all_files if f.is_file() and f.suffix != ".md"]
        assert not non_md, f"Non-markdown files in parsed/mermaid/: {non_md}"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: manifest.json includes Mermaid section
# ─────────────────────────────────────────────────────────────────────────────


class TestManifestIncludesMermaid:
    """Validate manifest.json has Mermaid metadata after write_mermaid_parsed."""

    def _make_mock_results(self):
        from hermes_bedrock_agent.parsing.mermaid_parser import (
            MermaidParseResult, MermaidNode, MermaidEdge, MermaidSubgraph,
        )
        return MermaidParseResult(
            source_path="/tmp/test.mmd",
            source_type="mmd_file",
            title="Test",
            diagram_type="flowchart",
            nodes=[MermaidNode(id="N1", label="A", node_type="process")],
            edges=[MermaidEdge(source="N1", target="N1")],
            subgraphs=[],
            raw_content="flowchart TD\n  N1[A]",
            markdown_summary="# Test",
            output_dir="/tmp",
        )

    def test_manifest_has_mermaid_section(self, tmp_path):
        """manifest.json includes mermaid key after write_mermaid_parsed."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_proj")

        result = self._make_mock_results()
        writer.write_mermaid_parsed([("d1", "key1", result)], [])
        manifest_path = writer.write_manifest()

        data = json.loads(manifest_path.read_text())
        assert "mermaid" in data
        assert data["mermaid"]["parsed_path"] == "parsed/mermaid/mermaid_parsed.md"
        assert data["mermaid"]["intermediates_dir"] == "intermediates/mermaid/"
        assert data["mermaid"]["node_count"] == 1
        assert data["mermaid"]["edge_count"] == 1
        assert data["mermaid"]["subgraph_count"] == 0

    def test_manifest_without_mermaid(self, tmp_path):
        """manifest.json does NOT have mermaid key if no Mermaid was parsed."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter

        run_dir = tmp_path / "run_test"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_proj")
        manifest_path = writer.write_manifest()

        data = json.loads(manifest_path.read_text())
        assert "mermaid" not in data


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: Chunker discovers parsed/mermaid/mermaid_parsed.md
# ─────────────────────────────────────────────────────────────────────────────


class TestChunkerDiscoversMermaid:
    """Validate that build_chunks_from_parsed_dir finds and chunks Mermaid output."""

    def _create_mermaid_parsed(self, parsed_dir: Path) -> None:
        """Create a minimal parsed/mermaid/mermaid_parsed.md with frontmatter."""
        mermaid_dir = parsed_dir / "mermaid"
        mermaid_dir.mkdir(parents=True, exist_ok=True)
        content = '''---
project_id: "test_proj"
source_file: "s3://bucket/test.mmd"
source_type: "mermaid"
document_type: "flowchart"
document_role: "flowchart_source"
parser_type: "mermaid_parser"
parser_version: "2.1"
document_id: "abc123def456"
document_name: "mermaid_parsed"
original_relative_path: "test.mmd"
display_name: "Mermaid Flowchart"
linked_excel_workbook: null
linked_excel_sheet: null
linkage_confidence: null
mermaid_preferred: true
parsed_at: "2026-06-12T00:00:00"
evidence_paths:
  - "intermediates/mermaid/mermaid_structure.json"
  - "intermediates/mermaid/mermaid_raw.mmd"
---

# Mermaid Flowchart Analysis

**Total nodes:** 4 | **Edges:** 3 | **Subgraphs:** 2

## Diagram: flowchart

| ID | Label | Type | Subgraph |
|---|---|---|---|
| `N1` | 開始 | terminal | 入力処理 |
| `N2` | データ取得 | process | 入力処理 |

### Business Flow

1. **入力処理**: 開始 → データ取得
2. **検証処理**: 検証 → 完了
'''
        (mermaid_dir / "mermaid_parsed.md").write_text(content, encoding="utf-8")

    def test_chunker_finds_mermaid_md(self, tmp_path):
        """build_chunks_from_parsed_dir discovers parsed/mermaid/mermaid_parsed.md."""
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        parsed_dir = tmp_path / "parsed"
        self._create_mermaid_parsed(parsed_dir)

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_proj")
        assert len(chunks) > 0

        # All chunks should be from mermaid type
        mermaid_chunks = [c for c in chunks if c.source_type == "mermaid"]
        assert len(mermaid_chunks) > 0

    def test_chunker_strips_frontmatter(self, tmp_path):
        """Chunk text does not contain YAML frontmatter."""
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        parsed_dir = tmp_path / "parsed"
        self._create_mermaid_parsed(parsed_dir)

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_proj")
        for chunk in chunks:
            assert "---" not in chunk.content.split("\n")[0], \
                "Chunk text should not start with frontmatter delimiter"
            assert "project_id:" not in chunk.content[:50], \
                "Chunk text should not contain raw frontmatter"

    def test_chunker_preserves_frontmatter_metadata(self, tmp_path):
        """Chunk metadata preserves frontmatter fields."""
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        parsed_dir = tmp_path / "parsed"
        self._create_mermaid_parsed(parsed_dir)

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_proj")
        assert len(chunks) > 0

        chunk = chunks[0]
        assert chunk.source_type == "mermaid"
        assert chunk.parser_type == "mermaid_parser"
        assert chunk.document_role == "flowchart_source"
        assert chunk.document_id == "abc123def456"
        assert chunk.document_name == "mermaid_parsed"
        assert chunk.project_id == "test_proj"

    def test_chunker_mermaid_single_chunk_type(self, tmp_path):
        """Mermaid is in _SINGLE_CHUNK_TYPES so body is not split."""
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        parsed_dir = tmp_path / "parsed"
        self._create_mermaid_parsed(parsed_dir)

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_proj")
        # mermaid in _SINGLE_CHUNK_TYPES → entire body is one chunk
        mermaid_chunks = [c for c in chunks if c.source_type == "mermaid"]
        assert len(mermaid_chunks) == 1

    def test_chunker_discovers_excel_alongside_mermaid(self, tmp_path):
        """Chunker finds both parsed/excel/ and parsed/mermaid/ subdirs."""
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        parsed_dir = tmp_path / "parsed"
        self._create_mermaid_parsed(parsed_dir)

        # Also create an Excel parsed file (with enough content to pass min_chars)
        excel_dir = parsed_dir / "excel" / "TestWB"
        excel_dir.mkdir(parents=True)
        excel_content = '''---
project_id: "test_proj"
source_file: "s3://bucket/test.xlsx"
source_type: "excel"
document_role: "data_source"
parser_type: "excel_vlm"
---

# Sheet 01 — マッピング定義

## システム連携情報

| No | フィールド名 | データ型 | マッピング先 | 備考 |
|----|------------|---------|-----------|------|
| 1 | 取引先コード | VARCHAR(10) | SAP BP_CODE | 必須 |
| 2 | 取引先名 | VARCHAR(100) | SAP BP_NAME | |
| 3 | 住所 | VARCHAR(200) | SAP ADDRESS | 半角変換 |
| 4 | 電話番号 | VARCHAR(20) | SAP PHONE | ハイフンなし |
| 5 | メールアドレス | VARCHAR(100) | SAP EMAIL | |

## 変換ルール

1. 取引先コードは先頭ゼロ埋め10桁
2. 住所は全角スペースを半角に変換
3. 電話番号からハイフンを除去
4. メールアドレスは小文字に統一

## 注意事項

- NULL値の場合はデフォルト値を設定
- 重複チェックは取引先コードで実施
- エラー時はスキップして次レコードへ
'''
        (excel_dir / "sheet_01.md").write_text(excel_content, encoding="utf-8")

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="test_proj")
        types = {c.source_type for c in chunks}
        assert "mermaid" in types
        assert "excel" in types


# ─────────────────────────────────────────────────────────────────────────────
# Test 5: Code review — cli.py Mermaid integration
# ─────────────────────────────────────────────────────────────────────────────


class TestCliMermaidIntegration:
    """Code review tests: cli.py correctly integrates Mermaid with unified output."""

    def test_cli_uses_write_mermaid_parsed(self):
        """cli.py calls writer.write_mermaid_parsed for Mermaid output."""
        src_path = Path(__file__).resolve().parent.parent / "src" / "hermes_bedrock_agent" / "cli.py"
        content = src_path.read_text(encoding="utf-8")

        assert "writer.write_mermaid_parsed(" in content, \
            "cli.py must call writer.write_mermaid_parsed()"

    def test_cli_writes_to_intermediates_not_mermaid_root(self):
        """cli.py writes raw Mermaid to intermediates/, not run_dir/mermaid/."""
        src_path = Path(__file__).resolve().parent.parent / "src" / "hermes_bedrock_agent" / "cli.py"
        content = src_path.read_text(encoding="utf-8")

        # Should use intermediates path
        assert "intermediates" in content
        # Should NOT have the old mermaid_out_dir = run_dir / "mermaid" pattern
        assert 'mermaid_out_dir = run_dir / "mermaid"' not in content

    def test_parsing_manifest_includes_mermaid_paths(self):
        """parsing_manifest.json generation in cli.py includes mermaid entries."""
        src_path = Path(__file__).resolve().parent.parent / "src" / "hermes_bedrock_agent" / "cli.py"
        content = src_path.read_text(encoding="utf-8")

        assert '"parsed_mermaid": "parsed/mermaid/"' in content
        assert '"intermediates_mermaid": "intermediates/mermaid/"' in content

    def test_flowchart_linker_writes_to_intermediates(self):
        """flowchart_linker.py writes linkage_report.json to intermediates/."""
        src_path = (
            Path(__file__).resolve().parent.parent
            / "src" / "hermes_bedrock_agent" / "parsing" / "flowchart_linker.py"
        )
        content = src_path.read_text(encoding="utf-8")

        assert '"intermediates" / "mermaid"' in content
        # Should NOT write to run_dir / "mermaid" (old location)
        assert 'Path(run_dir) / "mermaid"\n' not in content


# ─────────────────────────────────────────────────────────────────────────────
# Test 6: End-to-end output structure validation
# ─────────────────────────────────────────────────────────────────────────────


class TestOutputStructure:
    """Validate the final output directory structure after Mermaid parsing."""

    def test_full_structure_with_mermaid(self, tmp_path):
        """Full output structure has parsed/, evidence/, intermediates/, manifests."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter
        from hermes_bedrock_agent.parsing.mermaid_parser import (
            MermaidParseResult, MermaidNode, MermaidEdge, MermaidSubgraph,
        )

        run_dir = tmp_path / "run_20260612_120000"
        run_dir.mkdir()
        writer = UnifiedOutputWriter(run_dir, "test_project")

        # Setup a workbook
        wb_paths = writer.setup_workbook("TestWB")

        # Setup mermaid
        result = MermaidParseResult(
            source_path="/tmp/test.mmd",
            source_type="mmd_file",
            title="Test",
            diagram_type="flowchart",
            nodes=[MermaidNode(id="N1", label="A", node_type="process")],
            edges=[],
            subgraphs=[],
            raw_content="flowchart TD\n  N1[A]",
            markdown_summary="# Test",
            output_dir="/tmp",
        )
        writer.write_mermaid_parsed([("fc", "key", result)], [])
        writer.write_manifest()

        # Verify structure
        assert (run_dir / "parsed" / "excel" / "TestWB").exists()
        assert (run_dir / "parsed" / "mermaid" / "mermaid_parsed.md").exists()
        assert (run_dir / "evidence" / "excel" / "TestWB").exists()
        assert (run_dir / "evidence" / "mermaid").exists()
        assert (run_dir / "intermediates" / "mermaid" / "mermaid_raw.mmd").exists()
        assert (run_dir / "intermediates" / "mermaid" / "mermaid_structure.json").exists()
        assert (run_dir / "manifest.json").exists()

    def test_document_id_deterministic(self, tmp_path):
        """document_id in mermaid frontmatter is deterministic."""
        from hermes_bedrock_agent.parsing.output_writer import UnifiedOutputWriter
        from hermes_bedrock_agent.parsing.mermaid_parser import (
            MermaidParseResult, MermaidNode, MermaidEdge,
        )

        result = MermaidParseResult(
            source_path="/tmp/test.mmd",
            source_type="mmd_file",
            title="Test",
            diagram_type="flowchart",
            nodes=[MermaidNode(id="N1", label="A", node_type="process")],
            edges=[],
            subgraphs=[],
            raw_content="flowchart TD\n  N1[A]",
            markdown_summary="# Test",
            output_dir="/tmp",
        )

        # Run 1
        run_dir1 = tmp_path / "run1"
        run_dir1.mkdir()
        writer1 = UnifiedOutputWriter(run_dir1, "proj_x")
        writer1.write_mermaid_parsed([("fc", "same_key", result)], [])
        content1 = (run_dir1 / "parsed" / "mermaid" / "mermaid_parsed.md").read_text()

        # Run 2
        run_dir2 = tmp_path / "run2"
        run_dir2.mkdir()
        writer2 = UnifiedOutputWriter(run_dir2, "proj_x")
        writer2.write_mermaid_parsed([("fc", "same_key", result)], [])
        content2 = (run_dir2 / "parsed" / "mermaid" / "mermaid_parsed.md").read_text()

        import re
        ids1 = re.findall(r'document_id: "([^"]+)"', content1)
        ids2 = re.findall(r'document_id: "([^"]+)"', content2)
        assert ids1[0] == ids2[0], "document_id must be deterministic"
