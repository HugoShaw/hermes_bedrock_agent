"""Link Mermaid flowcharts to Excel workbooks/sheets by heuristic matching."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from .mermaid_parser import MermaidParseResult

logger = logging.getLogger(__name__)


class FlowchartLink(BaseModel):
    mermaid_source: str
    excel_workbook: Optional[str] = None
    excel_sheet: Optional[str] = None
    match_confidence: float = 0.0
    match_reason: str = ""
    mermaid_preferred: bool = True


_FLOWCHART_KEYWORDS = (
    "フローチャート", "flowchart", "フロー", "flow",
)


_FLOWCHART_SYNONYM_GROUPS = [
    {"flowchart", "フローチャート", "フロー", "flow"},
]


def _name_similarity(mermaid_stem: str, workbook_name: str) -> float:
    """Compute simple keyword overlap score between filenames."""
    m_lower = mermaid_stem.lower()
    w_lower = workbook_name.lower()

    for kw in _FLOWCHART_KEYWORDS:
        if kw in m_lower and kw in w_lower:
            return 0.7

    # Cross-language synonym match (e.g. "flowchart" in mermaid, "フローチャート" in workbook)
    for group in _FLOWCHART_SYNONYM_GROUPS:
        m_hit = any(kw in m_lower for kw in group)
        w_hit = any(kw in w_lower for kw in group)
        if m_hit and w_hit:
            return 0.6

    # Check if stems share substantial overlap
    m_parts = set(re.split(r'[_\-\s　]+', m_lower))
    w_parts = set(re.split(r'[_\-\s　]+', w_lower))
    overlap = (m_parts & w_parts) - {""}
    if overlap:
        return min(0.5, 0.2 * len(overlap))

    return 0.0


def _sheet_name_match(workbook_name: str) -> tuple[Optional[str], float]:
    """Check if workbook name suggests it contains a flowchart sheet."""
    w_lower = workbook_name.lower()
    for kw in _FLOWCHART_KEYWORDS:
        if kw in w_lower:
            return kw, 0.3
    return None, 0.0


def link_mermaid_to_excel(
    mermaid_results: list[MermaidParseResult],
    excel_workbooks: list[dict],
    run_dir: str,
) -> list[FlowchartLink]:
    """Link Mermaid parse results to Excel workbook entries.

    Args:
        mermaid_results: Parsed Mermaid structures.
        excel_workbooks: List of dicts with keys: workbook, sheets_parsed, output_dir.
        run_dir: Base run directory (for saving linkage report).

    Returns:
        List of FlowchartLink objects.
    """
    links: list[FlowchartLink] = []

    for result in mermaid_results:
        mermaid_stem = Path(result.source_path).stem.lower()
        best_link = FlowchartLink(mermaid_source=result.source_path)
        best_score = 0.0

        for wb in excel_workbooks:
            wb_name = wb.get("workbook", "")
            reasons: list[str] = []
            score = 0.0

            # Heuristic 1: filename similarity
            name_score = _name_similarity(mermaid_stem, wb_name)
            if name_score > 0:
                score += name_score
                reasons.append(f"filename_match({name_score:.1f})")

            # Heuristic 2: sheet name contains flowchart keyword
            kw, sheet_score = _sheet_name_match(wb_name)
            if sheet_score > 0:
                score += sheet_score
                reasons.append(f"sheet_keyword({kw})")

            # Heuristic 3: content overlap — check if VLM parsed output mentions node labels
            wb_output_dir = wb.get("output_dir", "")
            if wb_output_dir:
                vlm_dir = Path(wb_output_dir) / "vlm_parsed"
                if vlm_dir.exists():
                    vlm_text = ""
                    for md_file in sorted(vlm_dir.glob("*.md")):
                        vlm_text += md_file.read_text(encoding="utf-8", errors="ignore")
                    if vlm_text:
                        # Check if node labels from Mermaid appear in VLM output
                        node_labels = [n.label for n in result.nodes if len(n.label) > 3]
                        matches = sum(1 for lbl in node_labels[:20] if lbl in vlm_text)
                        if matches > 3:
                            content_score = min(0.4, matches * 0.05)
                            score += content_score
                            reasons.append(f"content_overlap({matches} nodes)")

            if score > best_score:
                best_score = score
                best_link = FlowchartLink(
                    mermaid_source=result.source_path,
                    excel_workbook=wb_name,
                    excel_sheet=None,
                    match_confidence=min(1.0, score),
                    match_reason="; ".join(reasons),
                    mermaid_preferred=True,
                )

        links.append(best_link)

    # Save linkage report to intermediates/mermaid/ (canonical location)
    if links:
        report_dir = Path(run_dir) / "intermediates" / "mermaid"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / "linkage_report.json"
        report_path.write_text(
            json.dumps([l.model_dump() for l in links], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Linkage report: %s", report_path)

    return links
