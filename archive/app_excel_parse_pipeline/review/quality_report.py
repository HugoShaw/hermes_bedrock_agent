"""Quality report generator.

Produces quality_report.json and quality_report.md with pipeline metrics.
"""
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def generate_quality_report(
    source_manifest: dict,
    workbook_atlases: list,
    parse_plans: list,
    execution_results_list: list,
    mermaid_results: list,
    graph_stats: dict,
    output_dir: Path,
) -> dict:
    """Generate comprehensive quality report."""
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_version": "1.0.0",
        "input_prefix": source_manifest.get("s3_prefix", ""),
        "statistics": _compute_statistics(
            source_manifest, workbook_atlases, parse_plans,
            execution_results_list, mermaid_results, graph_stats
        ),
        "issues": _collect_issues(parse_plans, execution_results_list, mermaid_results),
        "confidence_distribution": _compute_confidence_dist(execution_results_list),
        "human_review_required": _collect_review_items(parse_plans, execution_results_list),
        "parser_limitations": _list_limitations(),
    }

    # Save JSON
    json_path = output_dir / "quality_report.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    # Save Markdown
    md_path = output_dir / "quality_report.md"
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    return report


def _compute_statistics(
    manifest: dict, atlases: list, plans: list,
    exec_results: list, mermaid: list, graph: dict
) -> dict:
    """Compute pipeline statistics."""
    total_sheets = sum(a.get("sheet_count", 0) for a in atlases)
    total_regions = 0
    total_tables = 0
    total_fields = 0
    total_mappings = 0
    total_uncertain = 0
    total_unresolved = 0

    for plan in plans:
        for sheet in plan.get("sheets", []):
            total_regions += len(sheet.get("regions", []))

    for er in exec_results:
        total_tables += len(er.get("tables", []))
        total_fields += len(er.get("fields", []))
        total_mappings += len(er.get("mappings", []))
        total_uncertain += len(er.get("uncertain_records", []))
        total_unresolved += len(er.get("unresolved_references", []))

    mermaid_nodes = sum(len(m.get("nodes", [])) for m in mermaid)
    mermaid_edges = sum(len(m.get("edges", [])) for m in mermaid)

    scan_summary = manifest.get("scan_summary", {})

    return {
        "workbooks_processed": len(atlases),
        "sheet_count": total_sheets,
        "region_count": total_regions,
        "parse_plans_generated": len(plans),
        "table_count": total_tables,
        "field_count": total_fields,
        "mapping_count": total_mappings,
        "uncertain_count": total_uncertain,
        "unresolved_count": total_unresolved,
        "mermaid_files": len(mermaid),
        "mermaid_nodes": mermaid_nodes,
        "mermaid_edges": mermaid_edges,
        "graph_nodes": graph.get("nodes", {}).get("count", 0),
        "graph_edges": graph.get("edges", {}).get("count", 0),
        "excel_files": scan_summary.get("excel_files", 0),
        "mermaid_file_count": scan_summary.get("mermaid_files", 0),
        "other_files": scan_summary.get("other_files", 0),
    }


def _collect_issues(plans: list, exec_results: list, mermaid: list) -> list:
    """Collect all quality issues."""
    issues = []

    for plan in plans:
        for unc in plan.get("global_uncertainties", []):
            issues.append({
                "type": "parse_plan_uncertainty",
                "description": str(unc),
                "location": plan.get("workbook_name", ""),
                "severity": "medium",
            })

        for sheet in plan.get("sheets", []):
            for region in sheet.get("regions", []):
                for unc in region.get("uncertainties", []):
                    issues.append({
                        "type": "region_uncertainty",
                        "description": str(unc),
                        "location": f"{sheet.get('sheet_name', '')}/{region.get('region_id', '')}",
                        "severity": "medium",
                    })

    for er in exec_results:
        for ur in er.get("uncertain_records", []):
            issues.append({
                "type": "uncertain_record",
                "description": ur.get("reason", "unknown"),
                "location": f"{ur.get('sheet_name', '')}/{ur.get('region_id', '')}",
                "severity": "low",
            })

        for ref in er.get("unresolved_references", []):
            issues.append({
                "type": "unresolved_reference",
                "description": f"Cannot resolve: {ref.get('reference', '')}",
                "location": ref.get("context", ""),
                "severity": "medium",
            })

    return issues


def _compute_confidence_dist(exec_results: list) -> dict:
    """Compute confidence level distribution."""
    dist = {"high_0.8_1.0": 0, "medium_0.5_0.8": 0, "low_0.0_0.5": 0}

    for er in exec_results:
        for field in er.get("fields", []):
            c = field.get("confidence", 0.5)
            if c >= 0.8:
                dist["high_0.8_1.0"] += 1
            elif c >= 0.5:
                dist["medium_0.5_0.8"] += 1
            else:
                dist["low_0.0_0.5"] += 1

        for m in er.get("mappings", []):
            c = m.get("confidence", 0.5)
            if c >= 0.8:
                dist["high_0.8_1.0"] += 1
            elif c >= 0.5:
                dist["medium_0.5_0.8"] += 1
            else:
                dist["low_0.0_0.5"] += 1

    return dist


def _collect_review_items(plans: list, exec_results: list) -> list:
    """Collect items that require human review."""
    items = []

    for plan in plans:
        for hr in plan.get("human_review_required", []):
            items.append({
                "reason": str(hr),
                "workbook": plan.get("workbook_name", ""),
            })

        for sheet in plan.get("sheets", []):
            for region in sheet.get("regions", []):
                if region.get("semantic_role") == "unknown":
                    items.append({
                        "reason": f"Unknown region role: {region.get('region_id')}",
                        "workbook": plan.get("workbook_name", ""),
                        "sheet": sheet.get("sheet_name", ""),
                        "region": region.get("region_id", ""),
                    })

    for er in exec_results:
        for rec in er.get("uncertain_records", []):
            if rec.get("confidence", 1) < 0.5:
                items.append({
                    "reason": rec.get("reason", "low confidence"),
                    "sheet": rec.get("sheet_name", ""),
                    "region": rec.get("region_id", ""),
                })

    return items


def _list_limitations() -> list:
    """Document known parser limitations."""
    return [
        "Excel shapes/connectors extraction is limited (openpyxl does not fully support shapes)",
        "VLM may misinterpret dense Japanese text in small regions",
        "Ultra-wide tables with 50+ columns may have partial region detection",
        "Conditional formatting rules are not extracted",
        "Named ranges are noted but not used for cross-sheet resolution",
        "Password-protected sheets cannot be parsed",
        "Macro-enabled content (.xlsm) macros are not executed or analyzed",
        "Charts and embedded objects are not parsed",
        "Multi-level merged headers may produce incorrect column alignment",
    ]


def _render_markdown(report: dict) -> str:
    """Render quality report as Markdown."""
    lines = []
    lines.append("# Quality Report")
    lines.append(f"\nGenerated: {report['generated_at']}")
    lines.append(f"Pipeline version: {report['pipeline_version']}")
    lines.append(f"Input: {report.get('input_prefix', '')}")
    lines.append("")

    # Statistics
    stats = report["statistics"]
    lines.append("## Statistics")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    for key, value in stats.items():
        lines.append(f"| {key.replace('_', ' ').title()} | {value} |")
    lines.append("")

    # Confidence distribution
    conf = report["confidence_distribution"]
    lines.append("## Confidence Distribution")
    lines.append("")
    lines.append(f"- High (0.8-1.0): {conf.get('high_0.8_1.0', 0)}")
    lines.append(f"- Medium (0.5-0.8): {conf.get('medium_0.5_0.8', 0)}")
    lines.append(f"- Low (0.0-0.5): {conf.get('low_0.0_0.5', 0)}")
    lines.append("")

    # Issues
    issues = report["issues"]
    lines.append(f"## Issues ({len(issues)})")
    lines.append("")
    if issues:
        lines.append(f"| Type | Description | Location | Severity |")
        lines.append(f"|------|-------------|----------|----------|")
        for issue in issues[:50]:
            lines.append(f"| {issue.get('type', '')} | "
                         f"{issue.get('description', '')[:60]} | "
                         f"{issue.get('location', '')} | "
                         f"{issue.get('severity', '')} |")
        if len(issues) > 50:
            lines.append(f"\n... and {len(issues) - 50} more issues")
    else:
        lines.append("No issues detected.")
    lines.append("")

    # Human review
    review = report["human_review_required"]
    lines.append(f"## Human Review Required ({len(review)})")
    lines.append("")
    for item in review[:20]:
        lines.append(f"- {item.get('reason', '')} "
                     f"(sheet: {item.get('sheet', 'N/A')}, region: {item.get('region', 'N/A')})")
    lines.append("")

    # Limitations
    lines.append("## Parser Limitations")
    lines.append("")
    for lim in report["parser_limitations"]:
        lines.append(f"- {lim}")

    return "\n".join(lines)
