"""HTML review report builder.

Generates interactive HTML pages for human review of:
- Workbook overview
- Parse plan details
- Mapping extraction results
- Flowchart analysis
"""
import json
import html
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 1200px; margin: 0 auto; padding: 20px; background: #f8f9fa; }}
h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
h2 {{ color: #34495e; margin-top: 30px; }}
h3 {{ color: #5d6d7e; }}
table {{ border-collapse: collapse; width: 100%; margin: 15px 0; background: white; }}
th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; font-size: 13px; }}
th {{ background: #3498db; color: white; }}
tr:nth-child(even) {{ background: #f2f7fc; }}
.confidence-high {{ color: #27ae60; font-weight: bold; }}
.confidence-med {{ color: #f39c12; font-weight: bold; }}
.confidence-low {{ color: #e74c3c; font-weight: bold; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: bold; }}
.badge-mermaid {{ background: #27ae60; color: white; }}
.badge-excel {{ background: #3498db; color: white; }}
.badge-uncertain {{ background: #e74c3c; color: white; }}
.badge-review {{ background: #f39c12; color: white; }}
.section {{ background: white; border-radius: 8px; padding: 20px; margin: 15px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
.stats {{ display: flex; gap: 15px; flex-wrap: wrap; }}
.stat-card {{ background: white; border-radius: 8px; padding: 15px 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }}
.stat-value {{ font-size: 28px; font-weight: bold; color: #2c3e50; }}
.stat-label {{ font-size: 12px; color: #7f8c8d; margin-top: 5px; }}
pre {{ background: #2c3e50; color: #ecf0f1; padding: 15px; border-radius: 5px; overflow-x: auto; font-size: 12px; }}
.evidence {{ font-size: 11px; color: #7f8c8d; }}
</style>
</head>
<body>
{content}
</body>
</html>"""


def _confidence_badge(confidence: float) -> str:
    if confidence >= 0.8:
        return f'<span class="confidence-high">{confidence:.2f}</span>'
    elif confidence >= 0.5:
        return f'<span class="confidence-med">{confidence:.2f}</span>'
    else:
        return f'<span class="confidence-low">{confidence:.2f}</span>'


def build_review_html(
    workbook_atlas: dict,
    parse_plan: dict,
    execution_results: dict,
    mermaid_results: list,
    quality_data: dict,
    output_dir: Path,
) -> dict:
    """Generate all HTML review files."""
    review_dir = output_dir / "review"
    review_dir.mkdir(parents=True, exist_ok=True)

    results = {}

    # 1. Workbook review
    wb_html = _build_workbook_review(workbook_atlas, parse_plan, quality_data)
    wb_path = review_dir / "workbook_review.html"
    wb_path.write_text(wb_html, encoding="utf-8")
    results["workbook_review"] = str(wb_path)

    # 2. Parse plan review
    plan_html = _build_parse_plan_review(parse_plan)
    plan_path = review_dir / "parse_plan_review.html"
    plan_path.write_text(plan_html, encoding="utf-8")
    results["parse_plan_review"] = str(plan_path)

    # 3. Mapping review
    map_html = _build_mapping_review(execution_results)
    map_path = review_dir / "mapping_review.html"
    map_path.write_text(map_html, encoding="utf-8")
    results["mapping_review"] = str(map_path)

    # 4. Flowchart review
    flow_html = _build_flowchart_review(mermaid_results, execution_results)
    flow_path = review_dir / "flowchart_review.html"
    flow_path.write_text(flow_html, encoding="utf-8")
    results["flowchart_review"] = str(flow_path)

    return results


def _build_workbook_review(atlas: dict, plan: dict, quality: dict) -> str:
    """Build workbook overview HTML."""
    workbook_name = html.escape(atlas.get("workbook_name", "Unknown"))
    stats = quality.get("statistics", {})

    content_parts = []
    content_parts.append(f"<h1>📊 Workbook Review: {workbook_name}</h1>")

    # Stats cards
    content_parts.append('<div class="stats">')
    stat_items = [
        ("Sheets", stats.get("sheet_count", 0)),
        ("Regions", stats.get("region_count", 0)),
        ("Tables", stats.get("table_count", 0)),
        ("Fields", stats.get("field_count", 0)),
        ("Mappings", stats.get("mapping_count", 0)),
        ("Uncertain", stats.get("uncertain_count", 0)),
    ]
    for label, value in stat_items:
        content_parts.append(f'<div class="stat-card"><div class="stat-value">{value}</div>'
                             f'<div class="stat-label">{label}</div></div>')
    content_parts.append('</div>')

    # Sheet table
    content_parts.append('<div class="section"><h2>Sheet Overview</h2>')
    content_parts.append('<table><tr><th>Sheet</th><th>Type</th><th>Rows</th>'
                         '<th>Cols</th><th>Regions</th><th>Used Range</th></tr>')

    for sheet in atlas.get("sheets", []):
        sheet_name = html.escape(sheet["sheet_name"])
        dims = sheet.get("dimensions", {})
        
        # Find plan info
        sheet_type = "unknown"
        region_count = 0
        for sp in plan.get("sheets", []):
            if sp.get("sheet_name") == sheet["sheet_name"]:
                sheet_type = sp.get("sheet_type", "unknown")
                region_count = len(sp.get("regions", []))
                break

        content_parts.append(
            f'<tr><td>{sheet_name}</td><td>{sheet_type}</td>'
            f'<td>{dims.get("total_rows", 0)}</td><td>{dims.get("total_cols", 0)}</td>'
            f'<td>{region_count}</td><td>{sheet.get("used_range", "N/A")}</td></tr>'
        )

    content_parts.append('</table></div>')

    # Quality issues
    issues = quality.get("issues", [])
    if issues:
        content_parts.append('<div class="section"><h2>⚠️ Quality Issues</h2>')
        content_parts.append('<table><tr><th>Type</th><th>Description</th><th>Location</th></tr>')
        for issue in issues[:30]:
            content_parts.append(
                f'<tr><td><span class="badge badge-review">{html.escape(issue.get("type", ""))}</span></td>'
                f'<td>{html.escape(issue.get("description", ""))}</td>'
                f'<td>{html.escape(issue.get("location", ""))}</td></tr>'
            )
        content_parts.append('</table></div>')

    return _HTML_TEMPLATE.format(title=f"Workbook Review: {workbook_name}",
                                  content="\n".join(content_parts))


def _build_parse_plan_review(plan: dict) -> str:
    """Build parse plan review HTML."""
    content_parts = []
    content_parts.append("<h1>📋 Parse Plan Review</h1>")
    content_parts.append(f'<p>Workbook type: <strong>{plan.get("workbook_type", "unknown")}</strong></p>')
    content_parts.append(f'<p>Confidence: {_confidence_badge(plan.get("confidence", 0))}</p>')

    for sheet_plan in plan.get("sheets", []):
        sheet_name = html.escape(sheet_plan.get("sheet_name", "?"))
        content_parts.append(f'<div class="section"><h2>Sheet: {sheet_name}</h2>')
        content_parts.append(f'<p>Type: <strong>{sheet_plan.get("sheet_type", "unknown")}</strong></p>')

        regions = sheet_plan.get("regions", [])
        if regions:
            content_parts.append('<table><tr><th>Region</th><th>Range</th><th>Role</th>'
                                 '<th>Strategy</th><th>Confidence</th></tr>')
            for r in regions:
                strategy = r.get("extraction_strategy", {})
                content_parts.append(
                    f'<tr><td>{html.escape(r.get("region_id", "?"))}</td>'
                    f'<td>{html.escape(r.get("range", "?"))}</td>'
                    f'<td>{html.escape(r.get("semantic_role", "unknown"))}</td>'
                    f'<td>{html.escape(strategy.get("type", "?"))}</td>'
                    f'<td>{_confidence_badge(r.get("confidence", 0))}</td></tr>'
                )
            content_parts.append('</table>')

        # Uncertainties
        uncertainties = sheet_plan.get("uncertainties", [])
        if uncertainties:
            content_parts.append('<h3>Uncertainties</h3><ul>')
            for u in uncertainties:
                content_parts.append(f'<li>{html.escape(str(u))}</li>')
            content_parts.append('</ul>')

        content_parts.append('</div>')

    # Global uncertainties
    global_unc = plan.get("global_uncertainties", [])
    if global_unc:
        content_parts.append('<div class="section"><h2>⚠️ Global Uncertainties</h2><ul>')
        for u in global_unc:
            content_parts.append(f'<li>{html.escape(str(u))}</li>')
        content_parts.append('</ul></div>')

    # Raw JSON
    content_parts.append('<div class="section"><h2>Raw Parse Plan (JSON)</h2>')
    content_parts.append(f'<pre>{html.escape(json.dumps(plan, indent=2, ensure_ascii=False)[:10000])}</pre>')
    content_parts.append('</div>')

    return _HTML_TEMPLATE.format(title="Parse Plan Review", content="\n".join(content_parts))


def _build_mapping_review(execution_results: dict) -> str:
    """Build mapping review HTML."""
    content_parts = []
    content_parts.append("<h1>🔗 Mapping Review</h1>")

    mappings = execution_results.get("mappings", [])
    content_parts.append(f'<p>Total mappings: <strong>{len(mappings)}</strong></p>')

    if mappings:
        content_parts.append('<div class="section">')
        content_parts.append('<table><tr><th>#</th><th>Source</th><th>Target</th>'
                             '<th>Transformation</th><th>Confidence</th><th>Evidence</th></tr>')
        for i, m in enumerate(mappings[:100]):
            evidence = m.get("evidence", {})
            ev_str = f"{evidence.get('sheet', '')} {evidence.get('cell_range', '')}"
            content_parts.append(
                f'<tr><td>{i+1}</td>'
                f'<td>{html.escape(str(m.get("source_field", "?")))}</td>'
                f'<td>{html.escape(str(m.get("target_field", "?")))}</td>'
                f'<td>{html.escape(str(m.get("transformation", ""))[:80])}</td>'
                f'<td>{_confidence_badge(m.get("confidence", 0))}</td>'
                f'<td class="evidence">{html.escape(ev_str)}</td></tr>'
            )
        content_parts.append('</table></div>')

    # Unresolved
    unresolved = execution_results.get("unresolved_references", [])
    if unresolved:
        content_parts.append(f'<div class="section"><h2>❌ Unresolved References ({len(unresolved)})</h2>')
        content_parts.append('<table><tr><th>Reference</th><th>Context</th><th>Reason</th></tr>')
        for ref in unresolved[:30]:
            content_parts.append(
                f'<tr><td>{html.escape(str(ref.get("reference", "")))}</td>'
                f'<td>{html.escape(str(ref.get("context", "")))}</td>'
                f'<td>{html.escape(str(ref.get("reason", "")))}</td></tr>'
            )
        content_parts.append('</table></div>')

    return _HTML_TEMPLATE.format(title="Mapping Review", content="\n".join(content_parts))


def _build_flowchart_review(mermaid_results: list, execution_results: dict) -> str:
    """Build flowchart review HTML."""
    content_parts = []
    content_parts.append("<h1>🔀 Flowchart Review</h1>")

    # Mermaid sources
    if mermaid_results:
        content_parts.append('<div class="section"><h2>Mermaid Sources '
                             '<span class="badge badge-mermaid">Authoritative</span></h2>')
        for mermaid in mermaid_results:
            content_parts.append(f'<h3>{html.escape(mermaid.get("source_file", "?"))}</h3>')
            content_parts.append(f'<p>Type: {mermaid.get("graph_type", "flowchart")} | '
                                 f'Nodes: {len(mermaid.get("nodes", []))} | '
                                 f'Edges: {len(mermaid.get("edges", []))}</p>')

            # Show raw content
            raw = mermaid.get("raw_content", "")
            if raw:
                content_parts.append(f'<pre>{html.escape(raw[:3000])}</pre>')

            # Node table
            nodes = mermaid.get("nodes", [])
            if nodes:
                content_parts.append('<table><tr><th>ID</th><th>Label</th><th>Type</th></tr>')
                for n in nodes[:30]:
                    content_parts.append(
                        f'<tr><td>{html.escape(n["node_id"])}</td>'
                        f'<td>{html.escape(n.get("label", ""))}</td>'
                        f'<td>{n.get("node_type", "process")}</td></tr>'
                    )
                content_parts.append('</table>')

        content_parts.append('</div>')
    else:
        content_parts.append('<p>No Mermaid files found.</p>')

    # Conflicts
    conflicts = execution_results.get("flowchart_conflicts", [])
    if conflicts:
        content_parts.append(f'<div class="section"><h2>⚠️ Conflicts ({len(conflicts)})</h2>')
        content_parts.append('<table><tr><th>Type</th><th>Description</th><th>Source</th></tr>')
        for c in conflicts[:20]:
            content_parts.append(
                f'<tr><td>{html.escape(c.get("type", ""))}</td>'
                f'<td>{html.escape(c.get("description", ""))}</td>'
                f'<td>{html.escape(c.get("source", ""))}</td></tr>'
            )
        content_parts.append('</table></div>')

    return _HTML_TEMPLATE.format(title="Flowchart Review", content="\n".join(content_parts))
