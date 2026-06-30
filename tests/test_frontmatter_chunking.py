"""Tests for YAML frontmatter handling in chunker.

Validates:
- Frontmatter is stripped from chunk text
- Frontmatter fields are preserved in chunk metadata
- Multi-line YAML list fields (evidence_paths) are parsed correctly
- Markdown without frontmatter still chunks normally
- Malformed frontmatter is handled safely
- Chunk text does not contain metadata-only lines
- Existing chunk metadata is still preserved
"""

import tempfile
from pathlib import Path

import pytest


# Sample frontmatter matching the unified parser output
SAMPLE_FRONTMATTER = """\
---
project_id: "sample_20260519"
source_file: "s3://s3-hulftchina-rd/サンプル20260519/MW_IF一覧_20250515.xlsx"
source_type: "excel"
document_type: "excel"
document_role: "data_source"
parser_type: "excel_vlm"
document_id: "e0e652646acf9a53"
document_name: "MW_IF一覧_20250515"
original_relative_path: "サンプル20260519/MW_IF一覧_20250515.xlsx"
workbook_name: "MW_IF一覧_20250515"
sheet_index: 4
sheet_name: "sheet_04"
display_name: "MW_IF一覧_20250515 - sheet_04"
unit_type: "sheet"
parser_version: "2.1"
evidence_path: "evidence/excel/MW_IF一覧_20250515/sheet_04"
evidence_paths:
  - "evidence/excel/MW_IF一覧_20250515/sheet_04/sheet_04.pdf"
  - "evidence/excel/MW_IF一覧_20250515/sheet_04/full.png"
---

# IF一覧 シート04 - マッピング定義

## 項目一覧

| No | 項目名称 | 変数 | Type | 必須 | 長さ | 備考 |
|----|---------|------|------|------|------|------|
| 1 | 会社コード | BUKRS | STRING | ○ | 4 | SAP会社コード |
| 2 | 事業所コード | WERKS | STRING | ○ | 4 | プラントコード |
| 3 | 伝票番号 | BELNR | STRING | ○ | 10 | 会計伝票番号 |
"""

SAMPLE_NO_FRONTMATTER = """\
# シンプルなマークダウン

これはフロントマターのないファイルです。テスト用のドキュメントとして使用されます。

## セクション1

テーブルデータの詳細説明：このセクションではシステム連携に必要なパラメータ一覧を定義します。

| 列A | 列B | 説明 |
|-----|-----|------|
| 値1 | 値2 | パラメータ定義 |
| 値3 | 値4 | 条件定義 |
| 値5 | 値6 | マッピング定義 |

## セクション2

追加のコンテンツがここに含まれます。この部分はチャンキングの最小文字数要件を満たすために十分な長さが必要です。
データ連携仕様書の詳細はセクション3を参照してください。
"""

SAMPLE_MALFORMED_FRONTMATTER = """\
---
project_id: "test
  invalid yaml: [unclosed
---

# Content after malformed frontmatter

Some text here.
"""

SAMPLE_FRONTMATTER_NOT_DICT = """\
---
- item1
- item2
- item3
---

# Content after non-dict frontmatter

Real content below the list.
"""


class TestParseFrontmatter:
    """Unit tests for _parse_frontmatter function."""

    def test_valid_frontmatter_stripped(self):
        from hermes_bedrock_agent.knowledge_base.chunker import _parse_frontmatter

        fm, body = _parse_frontmatter(SAMPLE_FRONTMATTER)

        # Frontmatter should be a dict with all fields
        assert isinstance(fm, dict)
        assert fm["project_id"] == "sample_20260519"
        assert fm["source_file"] == "s3://s3-hulftchina-rd/サンプル20260519/MW_IF一覧_20250515.xlsx"
        assert fm["document_id"] == "e0e652646acf9a53"
        assert fm["sheet_index"] == 4
        assert fm["sheet_name"] == "sheet_04"
        assert fm["parser_version"] == "2.1"
        assert fm["workbook_name"] == "MW_IF一覧_20250515"

        # Body should NOT contain frontmatter
        assert not body.startswith("---")
        assert "project_id:" not in body
        assert "source_file:" not in body
        assert "evidence_paths:" not in body
        assert "parser_version:" not in body

        # Body should start with actual content
        assert body.startswith("# IF一覧 シート04")

    def test_evidence_paths_list(self):
        from hermes_bedrock_agent.knowledge_base.chunker import _parse_frontmatter

        fm, _ = _parse_frontmatter(SAMPLE_FRONTMATTER)

        # evidence_paths should be a proper list
        assert isinstance(fm["evidence_paths"], list)
        assert len(fm["evidence_paths"]) == 2
        assert "sheet_04.pdf" in fm["evidence_paths"][0]
        assert "full.png" in fm["evidence_paths"][1]

    def test_no_frontmatter(self):
        from hermes_bedrock_agent.knowledge_base.chunker import _parse_frontmatter

        fm, body = _parse_frontmatter(SAMPLE_NO_FRONTMATTER)

        assert fm == {}
        assert body == SAMPLE_NO_FRONTMATTER
        assert body.startswith("# シンプルなマークダウン")

    def test_malformed_frontmatter_warning(self):
        from hermes_bedrock_agent.knowledge_base.chunker import _parse_frontmatter

        fm, body = _parse_frontmatter(SAMPLE_MALFORMED_FRONTMATTER)

        # Should return empty dict and full text
        assert fm == {}
        assert body == SAMPLE_MALFORMED_FRONTMATTER

    def test_frontmatter_not_dict(self):
        from hermes_bedrock_agent.knowledge_base.chunker import _parse_frontmatter

        fm, body = _parse_frontmatter(SAMPLE_FRONTMATTER_NOT_DICT)

        # YAML parsed as list, not dict — treated as no frontmatter
        assert fm == {}
        assert body == SAMPLE_FRONTMATTER_NOT_DICT


class TestBuildChunksFromParsedDir:
    """Integration tests for build_chunks_from_parsed_dir with frontmatter."""

    @pytest.fixture
    def parsed_dir(self, tmp_path):
        """Create a test parsed directory with frontmatter files."""
        excel_dir = tmp_path / "parsed" / "excel" / "TestWorkbook"
        excel_dir.mkdir(parents=True)

        # Write file with full frontmatter
        (excel_dir / "sheet_01.md").write_text(SAMPLE_FRONTMATTER, encoding="utf-8")

        # Write file without frontmatter
        plain_dir = tmp_path / "parsed" / "docs"
        plain_dir.mkdir(parents=True)
        (plain_dir / "readme.md").write_text(SAMPLE_NO_FRONTMATTER, encoding="utf-8")

        return tmp_path / "parsed"

    def test_frontmatter_not_in_chunk_content(self, parsed_dir):
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="sample_20260519")

        # Find chunks from the frontmatter file
        excel_chunks = [c for c in chunks if c.source_type == "excel"]
        assert len(excel_chunks) > 0

        for chunk in excel_chunks:
            # Chunk content must NOT start with ---
            assert not chunk.content.startswith("---")
            # Chunk content must NOT contain frontmatter lines
            assert "project_id:" not in chunk.content
            assert "source_file:" not in chunk.content
            assert "evidence_paths:" not in chunk.content
            assert "parser_version:" not in chunk.content
            assert "document_id:" not in chunk.content
            assert "source_type:" not in chunk.content

    def test_frontmatter_fields_in_metadata(self, parsed_dir):
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="sample_20260519")

        excel_chunks = [c for c in chunks if c.source_type == "excel"]
        assert len(excel_chunks) > 0

        chunk = excel_chunks[0]
        # All frontmatter fields should be in chunk metadata
        assert chunk.project_id == "sample_20260519"
        assert chunk.source_file == "s3://s3-hulftchina-rd/サンプル20260519/MW_IF一覧_20250515.xlsx"
        assert chunk.document_id == "e0e652646acf9a53"
        assert chunk.document_name == "MW_IF一覧_20250515"
        assert chunk.document_type == "excel"
        assert chunk.document_role == "data_source"
        assert chunk.parser_type == "excel_vlm"
        assert chunk.workbook_name == "MW_IF一覧_20250515"
        assert chunk.sheet_index == 4
        assert chunk.sheet_name == "sheet_04"
        assert chunk.display_name == "MW_IF一覧_20250515 - sheet_04"
        assert chunk.unit_type == "sheet"
        assert chunk.parser_version == "2.1"
        assert chunk.evidence_path == "evidence/excel/MW_IF一覧_20250515/sheet_04"
        assert len(chunk.evidence_paths) == 2
        assert "sheet_04.pdf" in chunk.evidence_paths[0]

    def test_no_frontmatter_still_chunks(self, parsed_dir):
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="sample_20260519")

        # Docs file (no frontmatter) should still produce chunks
        doc_chunks = [c for c in chunks if c.workbook_name == "docs"]
        assert len(doc_chunks) > 0
        # Content from the no-frontmatter file should appear in chunks
        all_doc_content = " ".join(c.content for c in doc_chunks)
        assert "セクション1" in all_doc_content or "パラメータ定義" in all_doc_content

    def test_embedding_text_uses_cleaned_content(self, parsed_dir):
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="sample_20260519")

        excel_chunks = [c for c in chunks if c.source_type == "excel"]
        for chunk in excel_chunks:
            # Embedding text should NOT contain frontmatter
            assert "project_id:" not in chunk.embedding_text
            assert "evidence_paths:" not in chunk.embedding_text
            assert "---\n" not in chunk.embedding_text.split("\n\n")[0]  # No YAML delimiter in header
            # But it SHOULD contain the actual content
            assert "IF一覧" in chunk.embedding_text or "マッピング" in chunk.embedding_text

    def test_existing_metadata_preserved(self, parsed_dir):
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks_from_parsed_dir

        chunks = build_chunks_from_parsed_dir(parsed_dir, project_id="sample_20260519")

        excel_chunks = [c for c in chunks if c.source_type == "excel"]
        chunk = excel_chunks[0]

        # Existing computed metadata should still be present
        assert chunk.content_hash != ""
        assert chunk.chunk_mode != ""
        assert chunk.chunk_id != ""
        assert chunk.source_markdown_file != ""
        assert chunk.chunk_type != ""


class TestBuildChunksOldPath:
    """Tests for the older build_chunks() function with frontmatter stripping."""

    @pytest.fixture
    def vlm_parsed_dir(self, tmp_path):
        """Create a vlm_parsed directory with a frontmatter file."""
        vlm_dir = tmp_path / "vlm_parsed"
        vlm_dir.mkdir()
        (vlm_dir / "sheet_01.md").write_text(SAMPLE_FRONTMATTER, encoding="utf-8")
        return vlm_dir

    def test_old_path_strips_frontmatter(self, vlm_parsed_dir, tmp_path):
        from hermes_bedrock_agent.knowledge_base.chunker import build_chunks

        output = tmp_path / "chunks.jsonl"
        chunks = build_chunks(
            vlm_parsed_dir=vlm_parsed_dir,
            sheet_name_mapping_csv=None,
            workbook_name="TestWorkbook",
            s3_bucket="test-bucket",
            s3_pdf_prefix="outputs/test/pdf",
            s3_vlm_prefix="outputs/test/vlm_parsed",
            s3_excel_key="test.xlsx",
            output_path=output,
            project_id="test_project",
        )

        assert len(chunks) > 0
        for chunk in chunks:
            # Chunk content must NOT contain frontmatter
            assert not chunk.content.startswith("---")
            assert "project_id:" not in chunk.content
            assert "source_file:" not in chunk.content
            assert "evidence_paths:" not in chunk.content
            assert "parser_version:" not in chunk.content
            # Content should be the actual markdown body (after frontmatter stripped)
            # The heading may be split across chunks, so check table content exists somewhere
        # At least one chunk should have table content
        all_content = " ".join(c.content for c in chunks)
        assert "項目一覧" in all_content or "会社コード" in all_content


class TestChunkSerialization:
    """Test that new Chunk fields serialize/deserialize correctly."""

    def test_chunk_with_new_fields_roundtrip(self):
        from hermes_bedrock_agent.knowledge_base.schemas import Chunk

        chunk = Chunk(
            chunk_id="test_001",
            content="# Test content",
            chunk_type="mapping_table",
            document_id="e0e652646acf9a53",
            document_name="TestWorkbook",
            document_type="excel",
            display_name="TestWorkbook - sheet_04",
            unit_type="sheet",
            original_relative_path="サンプル/test.xlsx",
            parser_version="2.1",
            evidence_path="evidence/excel/test/sheet_04",
            evidence_paths=["evidence/excel/test/sheet_04/sheet_04.pdf", "evidence/excel/test/sheet_04/full.png"],
            project_id="test_project",
        )

        # Serialize
        json_str = chunk.model_dump_json()

        # Deserialize
        restored = Chunk.model_validate_json(json_str)

        assert restored.document_id == "e0e652646acf9a53"
        assert restored.document_name == "TestWorkbook"
        assert restored.evidence_paths == ["evidence/excel/test/sheet_04/sheet_04.pdf", "evidence/excel/test/sheet_04/full.png"]
        assert restored.parser_version == "2.1"
        assert restored.unit_type == "sheet"

    def test_backward_compat_no_new_fields(self):
        """Old chunks without new fields still deserialize fine."""
        from hermes_bedrock_agent.knowledge_base.schemas import Chunk

        old_json = '{"chunk_id":"old_001","content":"old content","chunk_type":"overview","project_id":"p1"}'
        chunk = Chunk.model_validate_json(old_json)

        assert chunk.chunk_id == "old_001"
        assert chunk.document_id == ""
        assert chunk.evidence_paths == []
        assert chunk.parser_version == ""
