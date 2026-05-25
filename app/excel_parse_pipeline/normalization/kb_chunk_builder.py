"""KB chunk builder: generate Markdown chunks for vector KB ingestion.

Produces semantic chunks grouped by:
- workbook summary
- sheet summaries
- table records (per-table)
- mapping records
- flowchart records
- transformation records
"""
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def build_kb_chunks(
    workbook_atlas: dict,
    parse_plan: dict,
    execution_results: dict,
    mermaid_results: list,
    output_dir: Path,
) -> dict:
    """Generate KB Markdown chunks from all pipeline outputs."""
    kb_dir = output_dir / "kb_chunks"
    kb_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # 1. Workbook summary
    wb_summary = _build_workbook_summary(workbook_atlas, parse_plan)
    wb_path = kb_dir / "workbook_summary.md"
    wb_path.write_text(wb_summary, encoding="utf-8")
    results["workbook_summary"] = str(wb_path)

    # 2. Sheet summaries
    sheet_summary = _build_sheet_summaries(workbook_atlas, parse_plan)
    sheet_path = kb_dir / "sheet_summaries.md"
    sheet_path.write_text(sheet_summary, encoding="utf-8")
    results["sheet_summaries"] = str(sheet_path)

    # 3. Table records
    table_md = _build_table_records(execution_results)
    table_path = kb_dir / "table_records.md"
    table_path.write_text(table_md, encoding="utf-8")
    results["table_records"] = str(table_path)

    # 4. Mapping records
    mapping_md = _build_mapping_records(execution_results)
    mapping_path = kb_dir / "mapping_records.md"
    mapping_path.write_text(mapping_md, encoding="utf-8")
    results["mapping_records"] = str(mapping_path)

    # 5. Flowchart records
    flow_md = _build_flowchart_records(mermaid_results, execution_results)
    flow_path = kb_dir / "flowchart_records.md"
    flow_path.write_text(flow_md, encoding="utf-8")
    results["flowchart_records"] = str(flow_path)

    # 6. Transformation records
    transform_md = _build_transformation_records(execution_results)
    transform_path = kb_dir / "transformation_records.md"
    transform_path.write_text(transform_md, encoding="utf-8")
    results["transformation_records"] = str(transform_path)

    return results


def _build_workbook_summary(atlas: dict, plan: dict) -> str:
    """Build workbook-level KB chunk."""
    lines = []
    lines.append(f"# Workbook: {atlas.get('workbook_name', 'Unknown')}")
    lines.append("")
    lines.append(f"**Source:** {atlas.get('source_file', 'N/A')}")
    lines.append(f"**Type:** {plan.get('workbook_type', 'unknown')}")
    lines.append(f"**Sheet count:** {atlas.get('sheet_count', 0)}")
    lines.append("")

    lines.append("## Sheets")
    lines.append("")
    for sheet in atlas.get("sheets", []):
        dims = sheet.get("dimensions", {})
        lines.append(f"- **{sheet['sheet_name']}**: {dims.get('total_rows', 0)} rows × "
                     f"{dims.get('total_cols', 0)} cols, "
                     f"used range: {sheet.get('used_range', 'N/A')}")

    lines.append("")
    lines.append("## Structure Overview")
    lines.append("")

    for sheet_plan in plan.get("sheets", []):
        lines.append(f"### {sheet_plan.get('sheet_name', 'N/A')}")
        lines.append(f"- Type: {sheet_plan.get('sheet_type', 'unknown')}")
        regions = sheet_plan.get("regions", [])
        if regions:
            lines.append(f"- Regions detected: {len(regions)}")
            for r in regions:
                lines.append(f"  - {r.get('region_id', '?')}: {r.get('semantic_role', 'unknown')} "
                             f"({r.get('range', '?')})")
        lines.append("")

    return "\n".join(lines)


def _build_sheet_summaries(atlas: dict, plan: dict) -> str:
    """Build per-sheet KB chunks."""
    lines = []
    workbook_name = atlas.get("workbook_name", "Unknown")

    for sheet in atlas.get("sheets", []):
        sheet_name = sheet["sheet_name"]
        lines.append(f"# Sheet: {sheet_name}")
        lines.append(f"**Workbook:** {workbook_name}")
        lines.append("")

        dims = sheet.get("dimensions", {})
        lines.append(f"- Rows: {dims.get('total_rows', 0)}")
        lines.append(f"- Columns: {dims.get('total_cols', 0)}")
        lines.append(f"- Used range: {sheet.get('used_range', 'N/A')}")
        lines.append(f"- Merged cells: {len(sheet.get('merged_cells', []))}")
        lines.append("")

        # Find matching plan
        sheet_plan = None
        for sp in plan.get("sheets", []):
            if sp.get("sheet_name") == sheet_name:
                sheet_plan = sp
                break

        if sheet_plan:
            lines.append(f"## Classification")
            lines.append(f"- Sheet type: {sheet_plan.get('sheet_type', 'unknown')}")
            lines.append("")

            regions = sheet_plan.get("regions", [])
            if regions:
                lines.append(f"## Regions ({len(regions)})")
                for r in regions:
                    lines.append(f"### Region: {r.get('region_id', '?')}")
                    lines.append(f"- Range: {r.get('range', '?')}")
                    lines.append(f"- Role: {r.get('semantic_role', 'unknown')}")
                    lines.append(f"- Reason: {r.get('layout_role_reason', 'N/A')}")
                    
                    columns = r.get("columns", [])
                    if columns:
                        lines.append(f"- Columns:")
                        for col in columns[:10]:  # Limit
                            lines.append(f"  - {col.get('column', '?')}: {col.get('role', 'unknown')}")
                    lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _build_table_records(execution_results: dict) -> str:
    """Build table extraction KB chunks."""
    lines = []
    lines.append("# Extracted Tables")
    lines.append("")

    tables = execution_results.get("tables", [])
    if not tables:
        lines.append("No tables extracted.")
        return "\n".join(lines)

    for table in tables:
        lines.append(f"## Table: {table.get('sheet_name', '?')} / {table.get('region_id', '?')}")
        lines.append(f"- Role: {table.get('semantic_role', 'unknown')}")
        lines.append(f"- Range: {table.get('range', '?')}")
        lines.append(f"- Rows: {table.get('row_count', 0)}")
        lines.append("")

        # Show headers
        headers = table.get("headers", {})
        if headers:
            header_line = " | ".join(f"{k}: {v}" for k, v in list(headers.items())[:10])
            lines.append(f"**Headers:** {header_line}")
            lines.append("")

        # Show sample data (first few rows)
        data = table.get("data_sample", [])
        if data:
            lines.append("**Sample data:**")
            for i, row in enumerate(data[:5]):
                row_str = " | ".join(str(v)[:30] for v in row.values()) if isinstance(row, dict) else str(row)[:200]
                lines.append(f"  Row {i+1}: {row_str}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def _build_mapping_records(execution_results: dict) -> str:
    """Build mapping KB chunks."""
    lines = []
    lines.append("# Mapping Records")
    lines.append("")

    mappings = execution_results.get("mappings", [])
    if not mappings:
        lines.append("No mapping records extracted.")
        return "\n".join(lines)

    lines.append(f"Total mappings: {len(mappings)}")
    lines.append("")

    for i, m in enumerate(mappings[:50]):  # Limit for KB size
        source = m.get("source_field", "?")
        target = m.get("target_field", "?")
        confidence = m.get("confidence", 0)
        lines.append(f"## Mapping {i+1}: {source} → {target}")
        lines.append(f"- Confidence: {confidence:.2f}")
        
        if m.get("transformation"):
            lines.append(f"- Transformation: {m['transformation']}")
        if m.get("condition"):
            lines.append(f"- Condition: {m['condition']}")
        
        evidence = m.get("evidence", {})
        if evidence:
            lines.append(f"- Evidence: sheet={evidence.get('sheet', '?')}, "
                         f"range={evidence.get('cell_range', '?')}")
        lines.append("")

    if len(mappings) > 50:
        lines.append(f"... and {len(mappings) - 50} more mappings (see structured/mappings.jsonl)")

    return "\n".join(lines)


def _build_flowchart_records(mermaid_results: list, execution_results: dict) -> str:
    """Build flowchart KB chunks."""
    lines = []
    lines.append("# Flowchart Records")
    lines.append("")

    # Mermaid-derived (authoritative)
    if mermaid_results:
        lines.append("## Mermaid-Derived Flowcharts (Authoritative)")
        lines.append("")
        for mermaid in mermaid_results:
            lines.append(f"### Source: {mermaid.get('source_file', '?')}")
            lines.append(f"- Type: {mermaid.get('graph_type', 'flowchart')}")
            lines.append(f"- Nodes: {len(mermaid.get('nodes', []))}")
            lines.append(f"- Edges: {len(mermaid.get('edges', []))}")
            lines.append(f"- Confidence: 1.0 (manual Mermaid)")
            lines.append("")

            # List nodes
            for node in mermaid.get("nodes", [])[:20]:
                lines.append(f"  - [{node.get('node_type', 'process')}] "
                             f"{node['node_id']}: {node.get('label', '')}")

            lines.append("")
            lines.append("  Edges:")
            for edge in mermaid.get("edges", [])[:20]:
                label = f" ({edge['label']})" if edge.get("label") else ""
                lines.append(f"  - {edge['source_node']} → {edge['target_node']}{label}")
            lines.append("")
    else:
        lines.append("No Mermaid files found.")
        lines.append("")

    # Excel-derived (lower confidence)
    flow_nodes = execution_results.get("flow_nodes", [])
    if flow_nodes:
        lines.append("## Excel-Derived Flowchart Elements")
        lines.append(f"- Nodes from shapes: {len(flow_nodes)}")
        lines.append("")

    return "\n".join(lines)


def _build_transformation_records(execution_results: dict) -> str:
    """Build transformation rule KB chunks."""
    lines = []
    lines.append("# Transformation Records")
    lines.append("")

    transforms = execution_results.get("transformations", [])
    if not transforms:
        lines.append("No transformation records extracted.")
        return "\n".join(lines)

    lines.append(f"Total transformation rules: {len(transforms)}")
    lines.append("")

    for i, t in enumerate(transforms[:30]):
        lines.append(f"## Rule {i+1}")
        lines.append(f"- Type: {t.get('rule_type', 'unknown')}")
        lines.append(f"- Description: {t.get('description', 'N/A')[:200]}")
        if t.get("source_field"):
            lines.append(f"- Source: {t['source_field']}")
        if t.get("target_field"):
            lines.append(f"- Target: {t['target_field']}")
        lines.append(f"- Confidence: {t.get('confidence', 0.5):.2f}")
        lines.append("")

    return "\n".join(lines)
