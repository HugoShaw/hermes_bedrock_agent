# Unified Parsing Output Validation Report

**Date:** 2026-06-12
**Scope:** Code review + static analysis (no live S3 parsing performed)
**Test results:** 31/31 PASS (6 safety guards + 25 unified output writer)

---

## 1. Parser Entrypoint Map

| # | Entrypoint | Command/Function | Status | Output Structure | Uses UnifiedOutputWriter | Can generate old-style? | Recommended |
|---|-----------|-----------------|--------|-----------------|--------------------------|------------------------|-------------|
| 1 | `dualrag parse` | `cli.py:parse()` | **Production** | unified_v1 (`parsed/evidence/legacy_compat/`) | ✅ YES | No (staging only, cleaned) | **keep** |
| 2 | `project parse-all` | `cli_project.py:parse_all()` → `orchestrator.run_project_parsing()` | **Production** (multi-type) | orchestrator-style (`parsed/<type>/`, `parsing_manifest.json`) | ❌ own impl, compatible | No (uses own reorganizer) | **keep** |
| 3 | `project parse` | `cli_project.py:parse_files()` | **Production** (single-file) | flat (`out_dir/<name>.md`, no frontmatter) | ❌ | Yes (flat, no structure) | **keep** (different use case) |
| 4 | `scripts/parse_unified.py` | standalone script | **Compatibility** | unified_v1 (same as `dualrag parse`) | ✅ YES | No | **keep** (S3+UNO subprocess workaround) |
| 5 | `scripts/run_parse_system_python.py` | subprocess wrapper | **Compatibility** (thin wrapper) | Delegates to `dualrag parse` | ✅ (via delegation) | No | **keep** (system-python UNO bridge) |
| 6 | `scripts/run_parse.py` | subprocess wrapper | **Deprecated** | Delegates to `uv run dualrag parse` | ✅ (via delegation) | No | **archive** (redundant — just `uv run dualrag parse`) |
| 7 | `scripts/parse_with_adapter.py` | standalone script | **Deprecated** | OLD style (`<wb_name>/pdf/images/vlm_parsed/`) | ❌ | **YES — writes old-style directly** | **archive** |
| 8 | `scripts/run_parse_sys.py` | standalone script (system python) | **Deprecated** | OLD style (`<wb_name>/pdf/images/vlm_parsed/`) | ❌ | **YES — writes old-style directly** | **archive** |
| 9 | `scripts/rerun_pipeline_sample_20260529.py` | standalone script | **Deprecated** | OLD style (sample-specific, hardcoded paths) | ❌ | **YES** | **archive** |
| 10 | `ExcelVlmAdapter` | `parsing/excel_vlm_adapter.py` | **Library** (adapter class) | tempdir only (no permanent writes) | N/A (temp output) | No (returns ParsedDocument) | **keep** |
| 11 | Orchestrator | `parsing/orchestrator.py` | **Library** (parsing pipeline) | own frontmatter-based structure (`parsed/<type>/`) | ❌ own impl | No (own canonical) | **keep** |

---

## 2. Production Entrypoint Uses UnifiedOutputWriter — VERIFIED ✅

**Code path for `dualrag parse` (the S3 Excel pipeline):**

```
cli.py:parse()
  ├── UnifiedOutputWriter(run_dir, effective_project_id)
  ├── For each workbook:
  │     ├── writer.setup_workbook(wb_name) → WorkbookPaths
  │     ├── convert_excel_to_pdfs(..., wb_paths.pdf_staging)
  │     ├── render_all_sheets(..., wb_paths.image_staging)
  │     ├── parse_all_sheets(..., wb_paths.vlm_staging)
  │     ├── post_process_all(parse_results)
  │     └── writer.reorganize_workbook(wb_paths, s3_source, results) → canonical structure
  ├── writer.write_manifest() → manifest.json
  ├── writer.cleanup_staging() → removes _staging/
  └── write parsing_manifest.json (NEW: added in this session)
```

**Canonical output verified:**
```
outputs/<project_id>/run_<timestamp>/
├── manifest.json              (structural manifest v2.0)
├── parsing_manifest.json      (canonical parse result manifest v2.1) ← NEW
├── parse_summary.json         (backward compat only)
├── parsed/excel/<workbook>/   (sheet_XX.md with frontmatter)
├── evidence/excel/<workbook>/ (sheet_XX/{pdf,full.png,tiles/,metadata.json})
└── legacy_compat/<workbook>/  (symlinks → parsed/ and evidence/)
```

---

## 3. Old-Style Output Code Paths — Classification

| Code Path | Classification | Status | Notes |
|-----------|---------------|--------|-------|
| `scripts/parse_with_adapter.py` L83-88 | **Deprecated old-style canonical** | ⚠️ Could confuse users | Creates `<wb>/pdf/`, `<wb>/images/`, `<wb>/vlm_parsed/` directly under run_dir |
| `scripts/run_parse_sys.py` L56-67 | **Deprecated old-style canonical** | ⚠️ Could confuse users | Same old-style layout |
| `scripts/rerun_pipeline_sample_20260529.py` | **Deprecated sample-specific** | ⚠️ Hardcoded paths | Only valid for one historical sample |
| `UnifiedOutputWriter._staging_base/` | **Temporary staging** | ✅ Acceptable | Cleaned up by `cleanup_staging()` after reorganization |
| `legacy_compat/<wb>/vlm_parsed/` | **Legacy compatibility output** | ✅ Acceptable | Symlinks only — not canonical |

**Verdict:** No production entrypoint writes old-style output as canonical. The old-style writers exist only in deprecated scripts.

---

## 4. UnifiedOutputWriter Genericity — Code Review

| Criterion | Status | Evidence |
|-----------|--------|----------|
| Japanese project names | ✅ Pass | Uses names directly (Linux ext4 supports UTF-8); tested with `"14_債務奉行クラウド"` |
| Spaces and special chars | ✅ Pass | No sanitization needed (ext4 allows all except `/` and NUL); tested with `"Sales Report 2025"` |
| Multiple Excel workbooks | ✅ Pass | Each `setup_workbook()` creates independent subdirs under `parsed/excel/`; tested with 3 workbooks |
| Future non-Excel documents | ⚠️ Partial | Currently hardcodes `parsed/excel/` and `evidence/excel/`. For non-Excel, the orchestrator path (`parsed/<type>/`) is more general |
| Safe filename generation | ✅ Pass | Uses raw workbook name as-is (no sanitization = no data loss); relies on ext4 UTF-8 support |
| Relative evidence paths | ✅ Pass | `evidence_path` in frontmatter is relative: `"evidence/excel/<wb>/sheet_XX/"` |
| No sample hardcoding | ✅ Pass | Zero references to "sample_20260519", "サンプル", or any hardcoded project names in `output_writer.py` |

**Risk:** `UnifiedOutputWriter` currently only supports the `excel/` subdirectory under `parsed/` and `evidence/`. For future non-Excel types (PDF, CSV, text), either: (a) the orchestrator path handles them (it already does), or (b) `UnifiedOutputWriter` would need a `document_type` parameter for the subdirectory. This is a Phase 3+ concern.

---

## 5. Frontmatter Contract — COMPLETE ✅

After patching `_build_frontmatter()`, the fields generated are:

| Field | Present | Required By | Notes |
|-------|---------|-------------|-------|
| `project_id` | ✅ | build-kb, isolation | From constructor arg |
| `source_file` | ✅ | chunker, graph scanner | S3 path of Excel file |
| `source_type` | ✅ (NEW) | chunker, graph scanner | Fixed `"excel"` |
| `document_role` | ✅ (NEW) | chunker, graph scanner | Fixed `"data_source"` |
| `parser_type` | ✅ (NEW) | chunker, graph scanner | Fixed `"excel_vlm"` |
| `workbook_name` | ✅ | additional context | Workbook filename stem |
| `sheet_index` | ✅ | additional context | 0-based index |
| `sheet_name` | ✅ | additional context | e.g., "sheet_01" |
| `unit_type` | ✅ | additional context | Fixed `"sheet"` |
| `parsed_at` | ✅ | audit | ISO timestamp |
| `parser_version` | ✅ | audit | `"2.0"` |
| `evidence_path` | ✅ | evidence linking | Relative path to evidence dir |
| `content_hash` | ❌ | chunker (optional) | Chunker defaults to `""` if absent; computes its own per-chunk hash |

**Verdict:** All required fields for downstream consumers are now present. `content_hash` is deliberately omitted since the chunker handles its absence gracefully (empty string default) and computes per-chunk hashes independently.

---

## 6. parsing_manifest.json — PATCHED ✅

**Before this session:**
- `dualrag parse` only generated `parse_summary.json` + `manifest.json` (structural)
- `project parse-all` generated `parsing_manifest.json` (via orchestrator)

**After patch:**
- `dualrag parse` now generates ALL THREE:
  - `parse_summary.json` — backward compat (legacy scripts may read it)
  - `manifest.json` — structural manifest (v2.0 format from UnifiedOutputWriter)
  - `parsing_manifest.json` — **NEW** canonical parse result manifest (v2.1)

The `parsing_manifest.json` format:
```json
{
  "manifest_version": "2.1",
  "project_id": "<id>",
  "structure": "unified_v1",
  "created_at": "<iso>",
  "parsing_run": {
    "timestamp": "<iso>",
    "result": {
      "files_parsed": N,
      "files_failed": M,
      "workbooks": [...],
      "mermaid_files": [...]
    }
  },
  "paths": {
    "parsed": "parsed/excel/",
    "evidence": "evidence/excel/",
    "legacy_compat": "legacy_compat/"
  }
}
```

---

## 7. Cleanup Recommendations

| File | Action | Reason |
|------|--------|--------|
| `scripts/parse_with_adapter.py` | **archive** | Writes old-style output, not imported by production, superseded by `dualrag parse` |
| `scripts/run_parse_sys.py` | **archive** | Writes old-style output, not imported by production, superseded by `run_parse_system_python.py` |
| `scripts/run_parse.py` | **archive** | Redundant — just calls `uv run dualrag parse` |
| `scripts/rerun_pipeline_sample_20260529.py` | **archive** | Sample-specific, hardcoded paths, one-time use |
| `scripts/parse_unified.py` | **keep** | Uses UnifiedOutputWriter, serves as UNO subprocess adapter |
| `scripts/run_parse_system_python.py` | **keep** | Thin wrapper that delegates to production CLI (system-python bridge) |
| `src/.../parsing/output_writer.py` | **keep** | Production canonical output writer |
| `src/.../parsing/orchestrator.py` | **keep** | Production multi-type parser |

**Note:** "archive" = move to `scripts/_archive/` or add `# DEPRECATED` header, NOT delete. These contain working logic that documents the old approach.

---

## 8. Remaining Risks

1. **`project parse` (single-file) has no frontmatter** — It writes flat `<name>.md` without YAML frontmatter. If these files are later fed into `build-kb`, the chunker will get empty strings for `source_type`, `parser_type`, `document_role`. This is tolerable (graceful defaults) but loses metadata fidelity. *Severity: Low (this path is for quick single-file tests).*

2. **`UnifiedOutputWriter` hardcodes `excel/` subdirectory** — Future non-Excel types (PDF, CSV) would need the orchestrator path or a `document_type` parameter. *Severity: Low (orchestrator handles non-Excel; Phase 3+ concern).*

3. **`document_role` is hardcoded to `"data_source"`** — All Excel sheets get the same role. The orchestrator path does role inference. For the Excel VLM pipeline, this is correct (Excel → data source), but if the project has "config" or "spec" Excel files, they'd be mis-classified. *Severity: Low (role refinement is Phase 3+).*

4. **Deprecated scripts still exist and can be run** — A user could run `python scripts/parse_with_adapter.py` and get old-style output. No guard prevents this. *Mitigation: Add deprecation warning or archive to `_archive/` subdirectory.*

5. **`parse_summary.json` vs `parsing_manifest.json` naming** — Two manifests could confuse users. `parse_summary.json` should eventually be documented as "legacy, kept for backward compat only." *Severity: Cosmetic.*

---

## Patches Made

1. **`src/hermes_bedrock_agent/parsing/output_writer.py`** — Added `source_type`, `document_role`, `parser_type`, `unit_type`, `parser_version` fields to `_build_frontmatter()`.

2. **`src/hermes_bedrock_agent/cli.py`** — Added `parsing_manifest.json` generation after `parse_summary.json` (canonical manifest with v2.1 schema).

3. **`tests/test_unified_output_writer.py`** — NEW file: 25 static tests covering paths, frontmatter contract, manifest generation, legacy separation, and import checks.

---

## Static/Unit Test Results

```
31 passed in 9.83s

tests/test_safety_guards.py: 6/6 PASS
  - build_kb requires project_id
  - build_kb allow_global permits no project_id
  - build_kb append and replace mutually exclusive
  - build_kb append emits deprecation warning
  - load_vector_store rejects empty replace
  - graph requires project_id

tests/test_unified_output_writer.py: 25/25 PASS
  - canonical directory structure ✓
  - Japanese workbook names ✓
  - spaces in workbook names ✓
  - multiple workbooks ✓
  - project_id stored ✓
  - no sample_20260519 hardcoding ✓
  - no hardcoded project names ✓
  - chunker fields present ✓
  - graph scanner fields present ✓
  - project_id field present ✓
  - all required fields present ✓
  - frontmatter values not empty ✓
  - additional useful fields ✓
  - manifest.json has version ✓
  - cli parse generates parsing_manifest ✓
  - orchestrator generates parsing_manifest ✓
  - legacy dir not under parsed ✓
  - canonical parsed not symlink ✓
  - cli parse imports UnifiedOutputWriter ✓
  - parse_unified script uses writer ✓
  - orchestrator does not use old style ✓
  - production files no old style canonical output ✓
  - deprecated scripts marked ✓
  - output_writer importable ✓
  - orchestrator importable ✓
```

---

## Conclusion

**Any future S3 project parsed through the official production entrypoints (`dualrag parse` or `project parse-all`) will use the unified output structure.** This is confirmed by:

1. Code-level proof: `cli.py:parse()` imports and uses `UnifiedOutputWriter`
2. Static tests verify the structure for arbitrary Japanese/special-char project names
3. Old-style writing only exists in deprecated scripts that are NOT called by production code
4. Frontmatter contract is now complete for all downstream consumers

**No parsing of `14_債務奉行クラウド` or any other S3 project was performed.**
