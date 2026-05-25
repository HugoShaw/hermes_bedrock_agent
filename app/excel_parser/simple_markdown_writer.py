"""Simple Markdown writer - generates a single consolidated .md file.

Produces a clean, RAG-friendly Markdown document combining:
- Workbook metadata
- Cell content (text/tables)
- Image references
- Diagram analysis (Claude or OOXML-only)
- Embedded Mermaid code blocks
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import WorkbookData, SheetData, CellBlock

logger = logging.getLogger(__name__)


def write_simple_markdown(
    workbook: WorkbookData,
    output_path: str,
    mermaid_content: str,
    classifications: list[dict],
    claude_results: dict[str, Optional[dict]],
    render_status: dict,
    input_uri: str = "",
    title: str = "",
    document_id: str = "",
    warnings: list[str] = None,
) -> str:
    """Write a consolidated Markdown file.

    Args:
        workbook: Parsed workbook data
        output_path: Path to write the .md file
        mermaid_content: Full Mermaid content (for embedding excerpts)
        classifications: Sheet classification results
        claude_results: Dict of {sheet_name: claude_response_or_None}
        render_status: Rendering status dict
        input_uri: Original input URI
        title: Document title
        document_id: Document ID
        warnings: List of warning messages

    Returns:
        The generated markdown content
    """
    if warnings is None:
        warnings = []

    lines = []
    cls_map = {c["sheet_name"]: c for c in classifications}

    # Title
    doc_title = title or Path(workbook.source_path).stem
    lines.append(f"# {doc_title}")
    lines.append("")

    # Source metadata
    lines.append("## Source")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Input URI | {input_uri} |")
    lines.append(f"| Document ID | {document_id} |")
    lines.append(f"| Generated At | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |")
    lines.append(f"| Parser Mode | Excel OOXML + optional Claude visual analysis |")
    lines.append(f"| Rendering | {render_status.get('method', 'none')} |")
    lines.append("")

    # Workbook summary table
    lines.append("## Workbook Summary")
    lines.append("")
    lines.append("| Sheet | Classification | Cells | Shapes | Connectors | Pictures | Strategy |")
    lines.append("|---|---|---:|---:|---:|---:|---|")

    for cls in classifications:
        lines.append(
            f"| {cls['sheet_name']} | {cls['classification']} | "
            f"{cls['cell_count']} | {cls['shape_count']} | "
            f"{cls['connector_count']} | {cls['picture_count']} | "
            f"{cls['strategy']} |"
        )
    lines.append("")

    # Per-sheet content
    for sheet in workbook.sheets:
        cls = cls_map.get(sheet.name, {})
        classification = cls.get("classification", "unknown")

        if classification == "empty":
            lines.append(f"## Sheet: {sheet.name}")
            lines.append("")
            lines.append("*(Empty sheet - no content)*")
            lines.append("")
            continue

        lines.append(f"## Sheet: {sheet.name}")
        lines.append("")

        # Cell content
        if sheet.cell_blocks:
            lines.append("### Cell Content")
            lines.append("")
            for block in sheet.cell_blocks:
                if block.markdown:
                    lines.append(block.markdown)
                elif block.data:
                    if block.is_table:
                        lines.append(_format_table(block))
                    else:
                        lines.append(_format_text(block))
                lines.append("")

        # Images
        if sheet.pictures:
            lines.append("### Images")
            lines.append("")
            for pic in sheet.pictures:
                if pic.output_path:
                    rel_path = _make_relative_path(pic.output_path, output_path)
                    lines.append(f"![{pic.name}]({rel_path})")
                else:
                    lines.append(f"- Image: {pic.name} (media: {pic.media_path})")
            lines.append("")

        # Diagram analysis
        if classification in ("visual", "mixed"):
            lines.append("### Diagram Analysis")
            lines.append("")

            claude_result = claude_results.get(sheet.name)
            if claude_result:
                # Claude analysis available
                diagram_type = claude_result.get("diagram_type", "unknown")
                summary = claude_result.get("summary_markdown", "")
                confidence = claude_result.get("confidence", 0)

                lines.append(f"**Diagram Type:** {diagram_type}")
                lines.append(f"**Analysis Confidence:** {confidence:.0%}")
                lines.append("")
                if summary:
                    lines.append(summary)
                    lines.append("")

                # Important texts
                important = claude_result.get("important_texts", [])
                if important:
                    lines.append("**Key Elements:**")
                    for text in important[:10]:
                        lines.append(f"- {text}")
                    lines.append("")

                # Warnings from Claude
                cw = claude_result.get("warnings", [])
                if cw:
                    lines.append("**Analysis Notes:**")
                    for w in cw:
                        lines.append(f"- ⚠️ {w}")
                    lines.append("")
            else:
                lines.append(
                    "*(Claude API not used; diagram analysis based on OOXML structure only)*"
                )
                lines.append("")
                if sheet.shapes:
                    lines.append(f"OOXML objects: {len(sheet.shapes)} shapes, "
                                 f"{len(sheet.connectors)} connectors")
                    lines.append("")

            # Mermaid section - extract this sheet's subgraph from full mermaid
            sheet_mermaid = _extract_sheet_mermaid(mermaid_content, sheet.name)
            if sheet_mermaid:
                lines.append("### Mermaid")
                lines.append("")
                mermaid_lines = sheet_mermaid.strip().split("\n")
                if len(mermaid_lines) > 80:
                    # Too long - embed abbreviated version
                    lines.append("```mermaid")
                    lines.extend(mermaid_lines[:60])
                    lines.append(f"    %% ... ({len(mermaid_lines) - 60} more lines)")
                    lines.append("```")
                    lines.append("")
                    lines.append(f"*Full Mermaid in: `{document_id}_raw.mmd`*")
                else:
                    lines.append("```mermaid")
                    lines.append(sheet_mermaid.strip())
                    lines.append("```")
                lines.append("")

        # Rendered image reference
        render_images = render_status.get("sheet_images", [])
        for img in render_images:
            if img.get("sheet_name") == sheet.name and img.get("path"):
                rel_path = _make_relative_path(img["path"], output_path)
                lines.append(f"### Rendered View")
                lines.append("")
                lines.append(f"![Rendered: {sheet.name}]({rel_path})")
                lines.append("")
                break

    # Warnings section
    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    content = "\n".join(lines)

    # Write file
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content, encoding="utf-8")
    logger.info(f"Markdown written to: {output_path} ({len(content)} chars)")

    return content


def _format_table(block: CellBlock) -> str:
    """Format a cell block as a Markdown table."""
    if not block.data:
        return ""

    lines = []
    # Determine column widths
    max_cols = max(len(row) for row in block.data) if block.data else 0
    if max_cols == 0:
        return ""

    # Header row (first row)
    header = block.data[0] if block.data else []
    header = [str(c) if c else "" for c in header]
    while len(header) < max_cols:
        header.append("")

    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")

    # Data rows
    for row in block.data[1:]:
        cells = [str(c) if c else "" for c in row]
        while len(cells) < max_cols:
            cells.append("")
        # Escape pipe characters
        cells = [c.replace("|", "\\|") for c in cells]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


def _format_text(block: CellBlock) -> str:
    """Format a cell block as bullet points or plain text."""
    if not block.data:
        return ""

    lines = []
    for row in block.data:
        non_empty = [str(c) for c in row if c]
        if non_empty:
            text = " | ".join(non_empty)
            lines.append(f"- {text}")

    return "\n".join(lines)


def _make_relative_path(abs_path: str, md_path: str) -> str:
    """Make a path relative to the markdown file location."""
    try:
        abs_p = Path(abs_path).resolve()
        md_dir = Path(md_path).resolve().parent
        return str(abs_p.relative_to(md_dir))
    except (ValueError, RuntimeError):
        return abs_path


def _extract_sheet_mermaid(full_mermaid: str, sheet_name: str) -> Optional[str]:
    """Extract the subgraph section for a specific sheet from the full mermaid."""
    if not full_mermaid:
        return None

    # Find the subgraph for this sheet
    safe_id = f"SHEET_" + sheet_name.replace(" ", "_").replace("/", "_")
    # Also try with re-encoded characters
    import re
    safe_pattern = re.sub(r"[^a-zA-Z0-9_]", "_", f"SHEET_{sheet_name}")

    lines = full_mermaid.split("\n")
    in_subgraph = False
    subgraph_lines = []
    depth = 0

    for line in lines:
        stripped = line.strip()
        if not in_subgraph:
            if (f'subgraph {safe_id}' in line or
                f'subgraph {safe_pattern}' in line or
                f'["{sheet_name}"]' in line):
                in_subgraph = True
                subgraph_lines.append(line)
                depth = 1
        else:
            subgraph_lines.append(line)
            if stripped.startswith("subgraph "):
                depth += 1
            elif stripped == "end":
                depth -= 1
                if depth <= 0:
                    break

    if subgraph_lines:
        # Return just the content (strip the subgraph wrapper for embedding)
        header = lines[0] if lines else "flowchart TD"
        return header + "\n\n" + "\n".join(subgraph_lines)

    return None
