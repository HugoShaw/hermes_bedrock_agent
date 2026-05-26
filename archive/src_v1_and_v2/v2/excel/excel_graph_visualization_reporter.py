"""
Excel Graph Visualization Reporter — generates markdown report for X6 stage.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ExcelGraphVisualizationReporter:
    """Generate visualization report."""

    def __init__(
        self,
        nodes: list[dict],
        edges: list[dict],
        source: str,
        generated_files: list[str],
        validation_results: dict[str, Any],
        output_dir: str | Path,
        run_id: str = "",
        dataset: str = "",
    ):
        self.nodes = nodes
        self.edges = edges
        self.source = source
        self.generated_files = generated_files
        self.validation = validation_results
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.dataset = dataset

    def generate_report(self) -> str:
        """Generate the visualization report markdown."""
        label_counts = Counter(n.get("label", "Unknown") for n in self.nodes)
        rel_counts = Counter(e.get("type", "Unknown") for e in self.edges)

        # Determine status
        status = "GO"
        if self.validation.get("murata_contamination", 0) > 0:
            status = "FAILED"
        elif self.validation.get("missing_endpoints", 0) > 10:
            status = "CONDITIONAL GO"

        report = f"""# Excel Graph Visualization Report

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}
**Run ID:** {self.run_id}
**Dataset:** {self.dataset}
**Source:** {self.source}
**Status:** {status}

---

## 1. Executive Summary

- Source used: **{self.source}**
- Full graph HTML: GENERATED
- Core graph HTML: GENERATED
- Field mapping HTML: GENERATED
- Business→Implementation HTML: GENERATED
- Evidence graph HTML: GENERATED
- Decision: **{status}**

---

## 2. Export Statistics

| Metric | Value |
|--------|-------|
| Total nodes | {len(self.nodes)} |
| Total edges | {len(self.edges)} |
| Evidence nodes | {label_counts.get('EvidenceChunk', 0)} |
| MAPS_TO edges | {rel_counts.get('MAPS_TO', 0)} |
| HAS_EVIDENCE edges | {rel_counts.get('HAS_EVIDENCE', 0)} |
| RELATED_TO edges | {rel_counts.get('RELATED_TO', 0)} |
| HAS_FIELD edges | {rel_counts.get('HAS_FIELD', 0)} |
| HAS_RULE edges | {rel_counts.get('HAS_RULE', 0)} |
| HAS_TERM edges | {rel_counts.get('HAS_TERM', 0)} |
| CONTAINS edges | {rel_counts.get('CONTAINS', 0)} |
| HAS_FUNCTION edges | {rel_counts.get('HAS_FUNCTION', 0)} |

### Nodes by Label

| Label | Count |
|-------|-------|
"""
        for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
            report += f"| {label} | {count} |\n"

        report += f"""
### Edges by Relation Type

| Relation | Count |
|----------|-------|
"""
        for rel, count in sorted(rel_counts.items(), key=lambda x: -x[1]):
            report += f"| {rel} | {count} |\n"

        report += f"""
---

## 3. Validation Results

| Check | Result |
|-------|--------|
| Node count | {len(self.nodes)} |
| Edge count | {len(self.edges)} |
| Missing endpoints | {self.validation.get('missing_endpoints', 0)} |
| Duplicate node IDs | {self.validation.get('duplicate_nodes', 0)} |
| Duplicate edge IDs | {self.validation.get('duplicate_edges', 0)} |
| Run ID contamination | {self.validation.get('run_id_contamination', 0)} |
| Dataset contamination | {self.validation.get('dataset_contamination', 0)} |
| Murata contamination | {self.validation.get('murata_contamination', 0)} |
| System nodes (SAP/中間F/Andpad) | {self.validation.get('system_nodes_present', 'N/A')} |
| MAPS_TO presence | {'YES' if rel_counts.get('MAPS_TO', 0) > 0 else 'NO'} |
| HAS_EVIDENCE presence | {'YES' if rel_counts.get('HAS_EVIDENCE', 0) > 0 else 'NO'} |
| RELATED_TO presence | {'YES' if rel_counts.get('RELATED_TO', 0) > 0 else 'NO'} |

---

## 4. Generated Files

"""
        for f in sorted(self.generated_files):
            report += f"- `{f}`\n"

        report += f"""
---

## 5. Usage Instructions

Open the HTML files locally in a browser:

```bash
# Full graph (all 786 nodes + 2059 edges)
xdg-open data/outputs/sample_20260519_excel_v1/visualization/excel_knowledge_graph_full.html

# Core graph (without evidence chunks — cleaner view)
xdg-open data/outputs/sample_20260519_excel_v1/visualization/excel_knowledge_graph_core.html

# Field mapping focus (SAP ↔ 中間F ↔ Andpad)
xdg-open data/outputs/sample_20260519_excel_v1/visualization/excel_field_mapping_graph.html

# Business-to-implementation cross-layer
xdg-open data/outputs/sample_20260519_excel_v1/visualization/excel_business_to_implementation_graph.html

# Evidence traceability
xdg-open data/outputs/sample_20260519_excel_v1/visualization/excel_evidence_graph.html
```

Or copy the HTML file to your local PC and open in Chrome/Firefox.

### Interactive Features

- **Search**: type node name in search box
- **Filter by Label**: select from dropdown
- **Filter by Relation**: select from dropdown
- **Toggle Evidence**: hide/show EvidenceChunk nodes
- **Click node/edge**: show properties in sidebar
- **Fit**: auto-zoom to fit all visible nodes
- **Reset**: clear all filters and show full graph

---

## 6. Known Limitations

- Full graph (786 nodes) may be visually dense — use Core or focused views for demos
- EvidenceChunk nodes clutter full graph — use Toggle Evidence button
- vis-network loaded from CDN (unpkg.com) — internet access needed on first load
- Full evidence text not in Neptune, only text_preview (max 200 chars)
- Column nodes (548) dominate the graph — filter by label for focused views
- Graph physics simulation may take a few seconds to stabilize
- For very large graphs, use browser zoom and drag to navigate

---

## 7. Recommended Next Stage

**X7: Excel Graph QA / Retrieval Test** — query validation against live Neptune graph with evidence retrieval.
"""
        # Write report
        report_path = self.output_dir / "excel_graph_visualization_report.md"
        report_path.write_text(report, encoding="utf-8")
        self.generated_files.append(str(report_path))
        logger.info("Generated report: %s", report_path)
        return report
