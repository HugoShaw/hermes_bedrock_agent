# Dual RAG リファクタリング計画

> Generated: 2026-06-05
> Test Case: 洋马发动机 (yangma_v2) — 196 files, 141 parsed, 35 Excel-handled, 1 failed

---

## 1. 現在のアーキテクチャ

```
S3 / Local Directory
    │
    ├─ project/scanner.py        → ProjectManifest (discovery)
    │
    ├─ [Excel Path] cli.py parse
    │   └─ parsing/ (excel_parser → LibreOffice PDF → tiled images → VLM → markdown)
    │       Output: outputs/<project>/wb*/vlm_parsed/sheet_NN.md
    │
    ├─ [Multi-Type Path] cli_project.py → project parse-all
    │   └─ parsing/ (orchestrator → role_inference → strategy → registry → per-type parsers)
    │       Output: outputs/<project>/parsed/*.md (YAML frontmatter)
    │
    ├─ knowledge_base/
    │   ├─ chunker.py             → semantic/fixed splitting → Chunk objects
    │   ├─ vector_store.py        → Bedrock Titan Embed V2 → LanceDB
    │   ├─ graph_extractor.py     → [LEGACY] 2-pass LLM extraction
    │   └─ graph_loader.py        → [LEGACY] Neptune Cypher MERGE
    │
    ├─ graph_pipeline/            → v4.3 Universal Semantic Map
    │   ├─ extractor.py           → 2-pass LLM (nodes → edges)
    │   ├─ normalizer.py          → ID registry + dedup
    │   ├─ structure.py           → Project→Workbook→Sheet hierarchy
    │   ├─ validator.py           → preflight + post-load checks
    │   └─ loader.py              → Neptune Cypher execution
    │
    └─ retrieval/
        ├─ query_router.py        → orchestrates dual retrieval
        ├─ graph_guided_retrieval → Neptune subgraph → filter LanceDB
        ├─ vector_retriever.py    → LanceDB similarity search
        ├─ graph_retriever.py     → Neptune Cypher queries
        └─ answer_generator.py    → multimodal VLM answer with evidence
```

**CLI commands (5):**
- `dualrag parse` — Excel/PDF VLM pipeline
- `dualrag build-kb` — Markdown → LanceDB vector store
- `dualrag graph` — Markdown → Neptune graph DB
- `dualrag qa` — Interactive QA terminal
- `dualrag project` — scan / status / parse / parse-all

---

## 2. 完了済み作業 (Phase 1-2)

- [x] `parsing/` パッケージ統合 (27 modules, 4342 LOC) — 旧分離パッケージを統合
- [x] `cli_project.py` (388 LOC) — project subcommands (scan, status, parse, parse-all)
- [x] 共有ヘルパー `parsing/utils.py` (compute_content_hash, download_s3_file, sanitize_filename)
- [x] ParserRegistry (11 parsers) + `.parsers` introspection property
- [x] Orchestrator: role inference → strategy selection → YAML frontmatter generation
- [x] Excel adaptive rendering: small sheets → single A4, large sheets → 3000px tiles (300px overlap)
- [x] VLM-first approach: PDF/images via Claude Sonnet, text extraction as fallback
- [x] CSV parser with role-aware markdown generation
- [x] `scripts/validate_yangma_project.py` with `--import-only` and `--dry-run` flags
- [x] Archive of legacy code in `archive/`

---

## 3. 残課題 (Downstream Gap)

| # | 問題 | 影響 | 優先度 |
|---|------|------|--------|
| 1 | `chunker.py` は `vlm_parsed/` のみ読む — `outputs/*/parsed/` 未対応 | 新パーサー出力をチャンク化できない | P0 |
| 2 | `graph_pipeline/` scanner は `vlm_parsed/` のみ — `parsed/` 未対応 | 非 Excel 文書のグラフ抽出不可 | P0 |
| 3 | Chunk schema が Excel 前提 (`sheet_index`, `workbook_name` 必須) | 非 Excel チャンクに不正メタデータ | P1 |
| 4 | LanceDB schema に `source_excel_s3_path` がハードコード | 非 Excel ドキュメントの出自追跡不可 | P1 |
| 5 | `dualrag project chunk` / `project embed` コマンドなし | マニフェスト → 下流パイプライン未接続 | P1 |
| 6 | `_SYSTEM_KEYWORDS` / `_CHUNK_TYPE_RULES` がハードコード | プロジェクト別語彙に非対応 | P2 |
| 7 | Evidence path 形式が Excel path convention と不整合 | QA 時にエビデンス画像が解決できない | P2 |

---

## 4. ドキュメントタイプ × パーサー × チャンキング戦略

| Source Type | Parser | Chunking Strategy | Metadata |
|-------------|--------|-------------------|----------|
| Excel (.xlsx/.xls/.xlsm) | `excel_vlm_adapter` | Semantic (sheet-aware) | sheet_index, sheet_name, workbook_name |
| PDF (.pdf) | `pdf_vlm_parser` / `pdf_text_parser` | Page-boundary semantic split | page_number, total_pages |
| Word (.docx) | `docx_parser` | Heading-based (H1/H2 boundaries) | section_path |
| Legacy Word (.doc) | `pdf_vlm_parser` (via LibreOffice) | Same as PDF | page_number |
| CSV/TSV | `csv_parser` | Row-group (header + N rows) | row_range, column_count |
| Image (.png/.jpg) | `image_vlm_parser` | Single chunk per image | image_category, dimensions |
| HTML (.html/.htm) | `html_parser` | Section-based (tag stripping) | — |
| Code (.py/.java/.sql) | `code_parser` | Whole-file or function-split | language |
| Markdown (.md) | `markdown_parser` | Semantic pass-through | — |
| Mermaid (.mmd) | `mermaid_parser` | Direct to graph (no chunking) | — |

---

## 5. メタデータ設計

### YAML Frontmatter (パーサー出力)

```yaml
---
source_file: "洋馬金蝶云星空WEBAPI接口设计说明书V3.0.pdf"
source_type: pdf
document_role: specification
parser_type: pdf_vlm
project_id: yangma_v2
content_hash: "sha256:abc123..."
page_count: 16
parse_date: "2026-06-05"
---
```

### Chunk Metadata (将来の ChunkV2)

```python
project_id: str          # プロジェクト識別子
source_file: str         # 元ファイル相対パス
source_type: str         # pdf, docx, csv, image, ...
document_role: str       # specification, contract, data_mapping, ...
parser_type: str         # pdf_vlm, docx, csv, ...
content_hash: str        # インクリメンタル処理用
chunk_type: str          # api_spec, mapping_table, overview, ...
metadata: dict           # タイプ固有 (sheet_index, page_number, etc.)
evidence_paths: list     # エビデンス画像パス
```

---

## 6. 提案アーキテクチャ (下流適応)

```
outputs/<project>/parsed/*.md   (YAML frontmatter 付き)
        │
        ▼
┌───────────────────────────────────────┐
│  Unified Markdown Reader              │
│  - Reads both vlm_parsed/ and parsed/ │
│  - Extracts metadata from frontmatter │
└───────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────┐
│  Type-Aware Chunker                   │
│  - Generic ChunkV2 schema             │
│  - Strategy per source_type           │
│  - content_hash-based skip            │
└───────────────────────────────────────┘
        │
        ├──▶ LanceDB (generic schema, no Excel assumptions)
        └──▶ Graph Pipeline (document_role filter → extraction)
```

Key principles:
1. **Frontmatter = metadata source** — no need for directory-name conventions
2. **Generic schemas** — Excel-specific fields move to `metadata: dict`
3. **Incremental by default** — content_hash skip at every stage
4. **Backward-compatible** — `vlm_parsed/` continues to work for Excel path

---

## 7. リファクタリングロードマップ

| Step | Task | Effort | Depends | Priority |
|------|------|--------|---------|----------|
| 1 | `chunker.py` に `parsed/` directory reader を追加 (YAML frontmatter → metadata) | 4h | — | P0 |
| 2 | `graph_pipeline/` scanner に `parsed/` 入力対応 + document_role filter | 3h | — | P0 |
| 3 | Generic ChunkV2 schema 定義 (`knowledge_base/schemas.py`) | 2h | — | P1 |
| 4 | LanceDB schema 拡張 (source_file, document_role, metadata_json) | 3h | Step 3 | P1 |
| 5 | CLI `dualrag project chunk` + `dualrag project embed` コマンド追加 | 4h | Steps 1, 4 | P1 |
| 6 | Evidence path 解決の統一 (parsed/ 用の evidence_manifest.json) | 2h | Step 1 | P2 |
| 7 | `_SYSTEM_KEYWORDS` / `_CHUNK_TYPE_RULES` を project_config 化 | 3h | — | P2 |
| 8 | `RetrievedChunk` schema に source_file, document_role 追加 | 2h | Step 4 | P2 |
| 9 | Legacy `knowledge_base/graph_extractor.py` 削除 | 1h | Step 2 | P2 |

**合計見積: ~24h (3 営業日)**

Critical path: Steps 1-2 (P0, 7h) → Steps 3-5 (P1, 9h) → Steps 6-9 (P2, 8h)

---

## 8. テストケース (yangma_v2)

### パーシング検証

| Scenario | Input | Expected |
|----------|-------|----------|
| PDF VLM | `洋馬金蝶云星空WEBAPI接口设计说明书V3.0.pdf` | 16 pages parsed, API spec tables extracted |
| DOCX | `HULFT开发合同(洋马).docx` | Contract text, party names, clauses |
| Image | `YSH_IF_001_mapping_json_*.png` | JSON field mapping table |
| CSV | `テスト表/テスト_SCMCONN_*.csv` | Row data with headers preserved |

### End-to-End QA (after downstream fix)

| Query | Expected Source Type | Expected Systems |
|-------|---------------------|------------------|
| "金蝶云星空WEBAPI的接口设计是什么？" | pdf_vlm | 金蝶云星空, WEBAPI |
| "HULFTの開発合同内容を教えて" | docx | HULFT |
| "YSH_IF_001のマッピング定義は？" | image_vlm | 金蝶云星空 |
| "テストデータのCSV構成は？" | csv | — |

---

## 9. 変更対象ファイル一覧

| File | Change | Priority |
|------|--------|----------|
| `knowledge_base/chunker.py` | `parsed/` dir reader + frontmatter metadata | P0 |
| `graph_pipeline/config.py` or scanner logic | Accept `parsed/` input dirs | P0 |
| `knowledge_base/schemas.py` | ChunkV2 schema definition | P1 |
| `knowledge_base/vector_store.py` | Generic LanceDB schema | P1 |
| `cli_project.py` | Add `chunk` and `embed` subcommands | P1 |
| `retrieval/answer_generator.py` | Evidence resolution for parsed/ path | P2 |
| `retrieval/graph_guided_retrieval.py` | document_role-aware filtering | P2 |
| `config.py` | project_config.yaml loader | P2 |
