"""Markdown writer - assembles all parsed data into a single Markdown document."""
import logging
from datetime import datetime
from pathlib import Path

from .models import WorkbookData, SheetData, CellBlock

logger = logging.getLogger(__name__)


def write_markdown(workbook: WorkbookData, output_path: str,
                   mermaid_files: dict[str, str],
                   s3_uri: str = "") -> str:
    """Write complete Markdown document combining all sheet data.
    
    Args:
        workbook: Parsed workbook data
        output_path: Path to write the .md file
        mermaid_files: Dict of {description: mermaid_content}
        s3_uri: Original S3 URI for metadata
    
    Returns:
        The generated markdown content
    """
    lines = []
    
    # Title
    filename = Path(workbook.source_path).stem
    lines.append(f"# {filename} - Excel解析結果")
    lines.append("")
    
    # Source metadata
    lines.append("## Source")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| S3 URI | {s3_uri} |")
    lines.append(f"| Local File | {workbook.source_path} |")
    lines.append(f"| Generated At | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |")
    lines.append("")
    
    # Workbook summary table
    lines.append("## Workbook Summary")
    lines.append("")
    lines.append("| Sheet | Cell Content | Images | Shapes | Connectors | Has Mermaid |")
    lines.append("|---|---:|---:|---:|---:|---|")
    
    for sheet in workbook.sheets:
        cell_count = sum(
            sum(1 for c in row if c)
            for block in sheet.cell_blocks
            for row in block.data
        )
        has_mermaid = "Yes" if sheet.shapes else "No"
        lines.append(
            f"| {sheet.name} | {cell_count} | {len(sheet.pictures)} | "
            f"{len(sheet.shapes)} | {len(sheet.connectors)} | {has_mermaid} |"
        )
    lines.append("")
    
    # Per-sheet content
    for sheet in workbook.sheets:
        lines.append(f"## Sheet: {sheet.name}")
        lines.append("")
        
        # Sheet metadata
        lines.append("### Sheet Metadata")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        lines.append(f"| Sheet Name | {sheet.name} |")
        lines.append(f"| Max Row | {sheet.max_row} |")
        lines.append(f"| Max Column | {sheet.max_col} |")
        lines.append(f"| Has Drawings | {sheet.has_drawing} |")
        lines.append(f"| Shape Count | {len(sheet.shapes)} |")
        lines.append(f"| Connector Count | {len(sheet.connectors)} |")
        lines.append(f"| Image Count | {len(sheet.pictures)} |")
        lines.append(f"| Merged Cells | {len(sheet.merged_cells)} |")
        lines.append("")
        
        # Cell content
        if sheet.cell_blocks:
            lines.append("### Cell Content")
            lines.append("")
            for block in sheet.cell_blocks:
                lines.extend(_render_cell_block(block))
                lines.append("")
        
        # Images
        if sheet.pictures:
            lines.append("### Images")
            lines.append("")
            for pic in sheet.pictures:
                rel_path = Path(pic.output_path).name if pic.output_path else pic.media_path
                lines.append(f"- **{pic.name}** ({pic.media_path})")
                lines.append(f"  - Position: row={pic.from_row}, col={pic.from_col}")
                lines.append(f"  - Output: `images/{rel_path}`")
                lines.append("")
        
        # Mermaid diagrams for this sheet
        sheet_mermaids = {k: v for k, v in mermaid_files.items() 
                        if sheet.name.lower() in k.lower() or 
                        (sheet.name == "概要" and "architecture" in k.lower())}
        
        if not sheet_mermaids and sheet.shapes:
            # Check for generic mermaid entries
            if sheet.name == "フローチャート":
                sheet_mermaids = {k: v for k, v in mermaid_files.items() 
                                if "flowchart" in k.lower()}
            elif sheet.name == "概要":
                sheet_mermaids = {k: v for k, v in mermaid_files.items()
                                if "architecture" in k.lower() or "overview" in k.lower()}
        
        for desc, content in sheet_mermaids.items():
            lines.append(f"### Mermaid: {desc}")
            lines.append("")
            lines.append("```mermaid")
            lines.append(content)
            lines.append("```")
            lines.append("")
        
        # Shape inventory
        if sheet.shapes:
            lines.append("### Shape Inventory")
            lines.append("")
            lines.append("| ID | Name | Text | Geometry | Position (row,col) |")
            lines.append("|---|---|---|---|---|")
            for shape in sheet.shapes:
                text_preview = (shape.text or "")[:40].replace("\n", " ").replace("|", "\\|")
                pos = f"({shape.from_row},{shape.from_col})-({shape.to_row},{shape.to_col})"
                lines.append(
                    f"| {shape.shape_id} | {shape.name[:30]} | "
                    f"{text_preview} | {shape.geometry or '-'} | {pos} |"
                )
            lines.append("")
        
        # Connector inventory
        if sheet.connectors:
            lines.append("### Connector Inventory")
            lines.append("")
            lines.append("| ID | Name | From Shape | To Shape | Label | Inferred |")
            lines.append("|---|---|---|---|---|---|")
            for conn in sheet.connectors:
                lines.append(
                    f"| {conn.connector_id} | {conn.name[:25]} | "
                    f"{conn.start_shape_id or '?'} | {conn.end_shape_id or '?'} | "
                    f"{conn.label or '-'} | {conn.inferred} |"
                )
            lines.append("")
    
    # Audit notes section
    lines.append("## Audit Notes")
    lines.append("")
    
    # Count unresolved connectors
    unresolved = []
    for sheet in workbook.sheets:
        for conn in sheet.connectors:
            if not conn.start_shape_id or not conn.end_shape_id:
                unresolved.append(f"- Sheet '{sheet.name}': Connector {conn.connector_id} ({conn.name})")
    
    inferred = []
    for sheet in workbook.sheets:
        for conn in sheet.connectors:
            if conn.inferred:
                inferred.append(f"- Sheet '{sheet.name}': Connector {conn.connector_id} ({conn.name}) "
                              f"from={conn.start_shape_id} to={conn.end_shape_id}")
    
    if unresolved:
        lines.append("### Unresolved Connectors")
        lines.append("")
        lines.extend(unresolved)
        lines.append("")
    
    if inferred:
        lines.append("### Position-Inferred Connections")
        lines.append("")
        lines.extend(inferred)
        lines.append("")
    
    lines.append("### Coverage Summary")
    lines.append("")
    total_shapes = sum(len(s.shapes) for s in workbook.sheets)
    total_conns = sum(len(s.connectors) for s in workbook.sheets)
    resolved_conns = sum(
        1 for s in workbook.sheets 
        for c in s.connectors 
        if c.start_shape_id and c.end_shape_id
    )
    lines.append(f"- Total shapes extracted: {total_shapes}")
    lines.append(f"- Total connectors extracted: {total_conns}")
    lines.append(f"- Resolved connectors: {resolved_conns}/{total_conns}")
    lines.append(f"- Unresolved connectors: {len(unresolved)}")
    lines.append(f"- Position-inferred connections: {len(inferred)}")
    lines.append("")
    
    content = "\n".join(lines)
    
    # Write file
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    
    logger.info(f"Markdown written: {output_path} ({len(content)} bytes)")
    return content


def _render_cell_block(block: CellBlock) -> list[str]:
    """Render a cell block as Markdown."""
    lines = []
    
    if block.is_table:
        # Render as Markdown table
        # Filter out completely empty columns
        col_has_data = [False] * len(block.data[0]) if block.data else []
        for row in block.data:
            for i, cell in enumerate(row):
                if cell:
                    col_has_data[i] = True
        
        active_cols = [i for i, has in enumerate(col_has_data) if has]
        
        if not active_cols:
            return lines
        
        # Header (first row)
        header = [block.data[0][i].replace("|", "\\|") for i in active_cols]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(active_cols)) + "|")
        
        # Data rows
        for row in block.data[1:]:
            if not any(row[i] for i in active_cols):
                continue
            row_cells = [row[i].replace("|", "\\|") if row[i] else "" for i in active_cols]
            lines.append("| " + " | ".join(row_cells) + " |")
    else:
        # Render as paragraphs/list
        for row in block.data:
            text = " ".join(c for c in row if c).strip()
            if text:
                lines.append(text)
                lines.append("")
    
    return lines
