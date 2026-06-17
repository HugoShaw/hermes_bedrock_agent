# Archived Scripts

These scripts are **deprecated** and archived as of 2025-06-12.
They write old-style output (flat vlm_parsed/ directory) without the unified output structure.

**Do not use for production parsing.** Use these production commands instead:

- `dualrag parse` — Excel/S3 parser with unified output + full YAML frontmatter
- `dualrag project parse-all` — Multi-type parser with role inference + strategy selection

## Archived scripts

| Script | Reason |
|--------|--------|
| `parse_with_adapter.py` | Old-style canonical output; superseded by UnifiedOutputWriter |
| `run_parse_sys.py` | System-python old-style; superseded by `dualrag parse` |
| `run_parse.py` | Redundant wrapper; just calls `uv run dualrag parse` |
| `rerun_pipeline_sample_20260529.py` | Sample-specific one-off; hardcoded project paths |
