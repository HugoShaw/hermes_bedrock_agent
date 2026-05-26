#!/usr/bin/env python3
"""Convert Excel file to Markdown + Mermaid (simplified stable pipeline).

Produces two primary outputs:
  {document_id}.md       - consolidated Markdown with all sheet content
  {document_id}_raw.mmd  - consolidated Mermaid diagram

Pipeline:
  1. Download/locate Excel file
  2. Read workbook cells (openpyxl)
  3. Parse OOXML drawings (shapes, connectors, pictures)
  4. Classify sheets (text_table / visual / mixed / empty)
  5. Render visual sheets to PNG (LibreOffice, optional)
  6. Call Claude/Bedrock VLM for visual sheets (optional)
  7. Build Mermaid from flow_spec or OOXML fallback
  8. Write final Markdown + Mermaid files

Usage:
    python scripts/convert_excel_to_markdown_simple.py \\
        --input-uri "s3://s3-hulftchina-rd/..." \\
        --document-id "msha_dss_flowchart" \\
        --title "M社様 DSSスクリプト改修概要 フローチャート" \\
        --output-root data/outputs/excel_markdown

    # Local file:
    python scripts/convert_excel_to_markdown_simple.py \\
        --input-uri "data/input/sample.xlsx" \\
        --document-id "sample" \\
        --title "Sample" \\
        --output-root data/outputs/excel_markdown

    # Skip Claude API:
    python scripts/convert_excel_to_markdown_simple.py \\
        --input-uri "..." --document-id "..." --no-claude

    # Skip rendering:
    python scripts/convert_excel_to_markdown_simple.py \\
        --input-uri "..." --document-id "..." --no-render
"""
import sys
import json
import csv
import logging
import argparse
from pathlib import Path
from datetime import datetime

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.excel_parser.s3_loader import download_from_s3
from app.excel_parser.workbook_reader import read_workbook
from app.excel_parser.ooxml_drawing_parser import parse_drawings
from app.excel_parser.object_classifier import classify_shape
from app.excel_parser.visual_renderer import render_excel_to_images
from app.excel_parser.simple_sheet_classifier import classify_sheets
from app.excel_parser.simple_claude_analyzer import analyze_visual_sheet
from app.excel_parser.simple_mermaid_builder import build_combined_mermaid
from app.excel_parser.simple_markdown_writer import write_simple_markdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("excel2md")


def main():
    parser = argparse.ArgumentParser(
        description="Excel → Markdown + Mermaid (simplified stable pipeline)"
    )
    parser.add_argument("--input-uri", type=str, required=True,
                        help="S3 URI or local path to Excel file")
    parser.add_argument("--document-id", type=str, required=True,
                        help="Document identifier for output naming")
    parser.add_argument("--title", type=str, default="",
                        help="Document title for Markdown header")
    parser.add_argument("--output-root", type=str, default="data/outputs/excel_markdown",
                        help="Output root directory")
    parser.add_argument("--local-cache-dir", type=str, default="/tmp/excel_cache",
                        help="Local cache for S3 downloads")
    parser.add_argument("--no-claude", action="store_true",
                        help="Skip Claude API calls (OOXML-only)")
    parser.add_argument("--no-render", action="store_true",
                        help="Skip LibreOffice rendering")
    args = parser.parse_args()

    # Setup output directories
    doc_dir = Path(args.output_root) / args.document_id
    work_dir = doc_dir / "work"
    images_dir = doc_dir / "images"
    rendered_dir = doc_dir / "rendered" / "sheets"

    for d in [doc_dir, work_dir, images_dir, rendered_dir]:
        d.mkdir(parents=True, exist_ok=True)

    warnings = []
    logger.info(f"=" * 60)
    logger.info(f"Excel → Markdown+Mermaid Pipeline")
    logger.info(f"  Input:       {args.input_uri}")
    logger.info(f"  Document ID: {args.document_id}")
    logger.info(f"  Output:      {doc_dir}")
    logger.info(f"  Claude:      {'disabled' if args.no_claude else 'enabled'}")
    logger.info(f"  Render:      {'disabled' if args.no_render else 'enabled'}")
    logger.info(f"=" * 60)

    # ─── Step 1: Get Excel file ─────────────────────────────────────────
    logger.info("Step 1: Locating Excel file...")
    excel_path = _get_excel_file(args.input_uri, args.local_cache_dir)
    if not excel_path:
        logger.error("Cannot locate Excel file. Aborting.")
        sys.exit(1)
    logger.info(f"  Excel file: {excel_path}")

    # ─── Step 2: Read workbook cells ────────────────────────────────────
    logger.info("Step 2: Reading workbook cells...")
    try:
        workbook = read_workbook(str(excel_path))
        logger.info(f"  Found {len(workbook.sheets)} sheets")
        for sheet in workbook.sheets:
            cell_count = sum(
                sum(1 for c in row if c)
                for block in sheet.cell_blocks
                for row in block.data
            )
            logger.info(f"    '{sheet.name}': {cell_count} cells, max_row={sheet.max_row}")
    except Exception as e:
        logger.error(f"  Failed to read workbook: {e}")
        sys.exit(1)

    # ─── Step 3: Parse OOXML drawings ──────────────────────────────────
    logger.info("Step 3: Parsing OOXML drawings...")
    try:
        parse_drawings(str(excel_path), workbook.sheets, str(images_dir))
        for sheet in workbook.sheets:
            if sheet.shapes or sheet.connectors or sheet.pictures:
                logger.info(
                    f"    '{sheet.name}': {len(sheet.shapes)} shapes, "
                    f"{len(sheet.connectors)} connectors, {len(sheet.pictures)} pictures"
                )
                # Classify shapes
                for shape in sheet.shapes:
                    result = classify_shape(shape, sheet.shapes, sheet.connectors)
                    # Store role as attribute (monkey-patch since model doesn't have it)
                    shape._role_candidate = result.get("role", "unknown")
    except Exception as e:
        logger.error(f"  OOXML parsing failed: {e}")
        warnings.append(f"OOXML parsing error: {e}")

    # ─── Step 4: Classify sheets ────────────────────────────────────────
    logger.info("Step 4: Classifying sheets...")
    classifications = classify_sheets(workbook.sheets)

    # Save classification
    cls_path = work_dir / "sheet_classification.json"
    cls_path.write_text(
        json.dumps({"sheets": classifications}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"  Classification saved to: {cls_path}")

    # ─── Step 4b: Build and save object inventory ───────────────────────
    logger.info("Step 4b: Building object inventory...")
    inventory = _build_object_inventory(workbook)
    inv_path = work_dir / "object_inventory.json"
    inv_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"  Object inventory saved to: {inv_path}")

    # Save CSVs
    _save_shapes_csv(workbook, work_dir / "shapes.csv")
    _save_connectors_csv(workbook, work_dir / "connectors.csv")
    _save_pictures_csv(workbook, work_dir / "pictures.csv")

    # ─── Step 5: Render visual sheets ──────────────────────────────────
    render_status = {"method": "none", "sheet_images": [], "success": False, "error": ""}

    if args.no_render:
        logger.info("Step 5: Rendering skipped (--no-render)")
        render_status["error"] = "Rendering disabled by --no-render flag"
        warnings.append("Visual rendering disabled (--no-render)")
    else:
        logger.info("Step 5: Rendering Excel sheets to PNG...")
        try:
            sheet_names = [s.name for s in workbook.sheets]
            render_status = render_excel_to_images(str(excel_path), str(rendered_dir), sheet_names)
            if render_status["success"]:
                logger.info(f"  Rendered {len(render_status['sheet_images'])} sheets via {render_status['method']}")
                for img_info in render_status["sheet_images"]:
                    logger.info(f"    '{img_info['sheet_name']}' → {img_info['path']}")
            else:
                logger.warning(f"  Rendering failed: {render_status['error']}")
                warnings.append(f"Visual rendering failed: {render_status['error']}")
        except Exception as e:
            logger.warning(f"  Rendering error: {e}")
            warnings.append(f"Visual rendering error: {e}")

    # Save render status
    render_path = work_dir / "render_status.json"
    render_path.write_text(
        json.dumps(render_status, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8"
    )

    # ─── Step 6: Claude API analysis ───────────────────────────────────
    claude_results = {}

    if args.no_claude:
        logger.info("Step 6: Claude analysis skipped (--no-claude)")
        warnings.append("Claude API analysis disabled (--no-claude)")
    else:
        logger.info("Step 6: Analyzing visual sheets with Claude/Bedrock VLM...")
        for cls in classifications:
            if cls["classification"] not in ("visual", "mixed"):
                continue

            sheet_name = cls["sheet_name"]
            logger.info(f"  Analyzing sheet: '{sheet_name}'...")

            # Find screenshot
            screenshot = _find_screenshot(render_status, sheet_name, rendered_dir)

            # Get sheet inventory
            sheet_inv = _get_sheet_inventory(inventory, sheet_name)

            # Get cell markdown
            cell_md = _get_cell_markdown(workbook, sheet_name)

            result = analyze_visual_sheet(
                screenshot_path=screenshot,
                object_inventory=sheet_inv,
                cell_markdown=cell_md,
                sheet_name=sheet_name,
                output_dir=str(work_dir),
            )
            claude_results[sheet_name] = result

            if result:
                logger.info(f"    ✓ Got flow_spec: {len(result.get('flow_spec', {}).get('nodes', []))} nodes")
            else:
                logger.info(f"    ✗ No Claude result (will use OOXML fallback)")
                warnings.append(f"Claude analysis unavailable for sheet '{sheet_name}'; using OOXML-only")

    # ─── Step 7: Build Mermaid ─────────────────────────────────────────
    logger.info("Step 7: Building Mermaid diagram...")
    try:
        mermaid_content = build_combined_mermaid(
            workbook.sheets, classifications, claude_results
        )
        mermaid_path = doc_dir / f"{args.document_id}_raw.mmd"
        mermaid_path.write_text(mermaid_content, encoding="utf-8")
        mermaid_lines = len(mermaid_content.strip().split("\n"))
        logger.info(f"  Mermaid written to: {mermaid_path} ({mermaid_lines} lines)")
    except Exception as e:
        logger.error(f"  Mermaid generation failed: {e}")
        mermaid_content = f"%% Mermaid generation failed: {e}\nflowchart TD\n    ERROR[\"Generation failed\"]\n"
        mermaid_path = doc_dir / f"{args.document_id}_raw.mmd"
        mermaid_path.write_text(mermaid_content, encoding="utf-8")
        warnings.append(f"Mermaid generation error: {e}")

    # ─── Step 8: Write Markdown ────────────────────────────────────────
    logger.info("Step 8: Writing consolidated Markdown...")
    try:
        md_path = doc_dir / f"{args.document_id}.md"
        write_simple_markdown(
            workbook=workbook,
            output_path=str(md_path),
            mermaid_content=mermaid_content,
            classifications=classifications,
            claude_results=claude_results,
            render_status=render_status,
            input_uri=args.input_uri,
            title=args.title or args.document_id,
            document_id=args.document_id,
            warnings=warnings,
        )
        logger.info(f"  Markdown written to: {md_path}")
    except Exception as e:
        logger.error(f"  Markdown generation failed: {e}")
        warnings.append(f"Markdown generation error: {e}")

    # ─── Summary ───────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Markdown: {doc_dir / f'{args.document_id}.md'}")
    logger.info(f"  Mermaid:  {doc_dir / f'{args.document_id}_raw.mmd'}")
    logger.info(f"  Work dir: {work_dir}")
    logger.info(f"  Images:   {images_dir}")
    if render_status.get("success"):
        logger.info(f"  Rendered: {rendered_dir}")
    logger.info("")

    if warnings:
        logger.info("Warnings:")
        for w in warnings:
            logger.info(f"  ⚠️  {w}")

    # Print summary table
    logger.info("")
    logger.info("Sheet Processing Summary:")
    logger.info(f"{'Sheet':<30} {'Class':<12} {'Cells':>5} {'Shapes':>6} {'Conn':>5} {'Claude':>8} {'Rendered':>8}")
    logger.info("-" * 80)
    for cls in classifications:
        sn = cls["sheet_name"][:28]
        claude_used = "Yes" if claude_results.get(cls["sheet_name"]) else "No"
        rendered = "Yes" if any(
            img.get("sheet_name") == cls["sheet_name"]
            for img in render_status.get("sheet_images", [])
        ) else "No"
        logger.info(
            f"{sn:<30} {cls['classification']:<12} {cls['cell_count']:>5} "
            f"{cls['shape_count']:>6} {cls['connector_count']:>5} "
            f"{claude_used:>8} {rendered:>8}"
        )


# ─── Helper functions ──────────────────────────────────────────────────────


def _get_excel_file(input_uri: str, cache_dir: str) -> Path:
    """Download from S3 or resolve local path."""
    if input_uri.startswith("s3://"):
        try:
            return download_from_s3(input_uri, cache_dir)
        except Exception as e:
            logger.error(f"S3 download failed: {e}")
            # Check if cached locally
            cached = Path(cache_dir) / Path(input_uri).name
            if cached.exists():
                logger.info(f"Using cached file: {cached}")
                return cached
            return None
    else:
        local_path = Path(input_uri)
        if local_path.exists():
            return local_path
        # Try relative to project root
        project_path = project_root / input_uri
        if project_path.exists():
            return project_path
        logger.error(f"File not found: {input_uri}")
        return None


def _build_object_inventory(workbook) -> dict:
    """Build complete object inventory for all sheets."""
    inventory = {"sheets": []}

    for sheet in workbook.sheets:
        sheet_inv = {
            "sheet_name": sheet.name,
            "shapes": [],
            "connectors": [],
            "pictures": [],
        }

        for shape in sheet.shapes:
            role = getattr(shape, "_role_candidate", "unknown")
            sheet_inv["shapes"].append({
                "sheet_name": sheet.name,
                "shape_id": shape.shape_id,
                "name": shape.name,
                "text": shape.text,
                "geometry": shape.geometry,
                "from_row": shape.from_row,
                "from_col": shape.from_col,
                "to_row": shape.to_row,
                "to_col": shape.to_col,
                "x": shape.x,
                "y": shape.y,
                "width": shape.width,
                "height": shape.height,
                "xfrm_x": shape.xfrm_x,
                "xfrm_y": shape.xfrm_y,
                "xfrm_cx": shape.xfrm_cx,
                "xfrm_cy": shape.xfrm_cy,
                "role_candidate": role,
            })

        for conn in sheet.connectors:
            sheet_inv["connectors"].append({
                "sheet_name": sheet.name,
                "connector_id": conn.connector_id,
                "name": conn.name,
                "start_shape_id": conn.start_shape_id,
                "end_shape_id": conn.end_shape_id,
                "has_arrow": conn.has_arrow,
                "label": conn.label,
                "inferred": conn.inferred,
            })

        for pic in sheet.pictures:
            sheet_inv["pictures"].append({
                "sheet_name": sheet.name,
                "picture_id": pic.picture_id,
                "name": pic.name,
                "media_path": pic.media_path,
                "output_path": pic.output_path,
            })

        inventory["sheets"].append(sheet_inv)

    return inventory


def _save_shapes_csv(workbook, path: Path):
    """Save shapes data to CSV."""
    rows = []
    for sheet in workbook.sheets:
        for shape in sheet.shapes:
            role = getattr(shape, "_role_candidate", "unknown")
            rows.append({
                "sheet_name": sheet.name,
                "shape_id": shape.shape_id,
                "name": shape.name,
                "text": (shape.text or "")[:100],
                "geometry": shape.geometry or "",
                "role_candidate": role,
                "x": shape.x,
                "y": shape.y,
                "width": shape.width,
                "height": shape.height,
            })

    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"  Shapes CSV: {path} ({len(rows)} rows)")


def _save_connectors_csv(workbook, path: Path):
    """Save connectors data to CSV."""
    rows = []
    for sheet in workbook.sheets:
        for conn in sheet.connectors:
            rows.append({
                "sheet_name": sheet.name,
                "connector_id": conn.connector_id,
                "name": conn.name,
                "start_shape_id": conn.start_shape_id or "",
                "end_shape_id": conn.end_shape_id or "",
                "has_arrow": conn.has_arrow,
                "label": conn.label or "",
                "inferred": conn.inferred,
            })

    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"  Connectors CSV: {path} ({len(rows)} rows)")


def _save_pictures_csv(workbook, path: Path):
    """Save pictures data to CSV."""
    rows = []
    for sheet in workbook.sheets:
        for pic in sheet.pictures:
            rows.append({
                "sheet_name": sheet.name,
                "picture_id": pic.picture_id,
                "name": pic.name,
                "media_path": pic.media_path,
                "output_path": pic.output_path,
            })

    if rows:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        logger.info(f"  Pictures CSV: {path} ({len(rows)} rows)")


def _find_screenshot(render_status: dict, sheet_name: str, rendered_dir: Path) -> str:
    """Find the rendered screenshot for a sheet."""
    # Check render_status
    for img in render_status.get("sheet_images", []):
        if img.get("sheet_name") == sheet_name and img.get("path"):
            if Path(img["path"]).exists():
                return img["path"]

    # Fallback: search rendered dir by pattern
    for pattern in [f"*{sheet_name}*", f"sheet_*"]:
        for f in rendered_dir.glob(pattern):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                return str(f)

    return None


def _get_sheet_inventory(inventory: dict, sheet_name: str) -> dict:
    """Get inventory for a specific sheet."""
    for sheet_inv in inventory.get("sheets", []):
        if sheet_inv.get("sheet_name") == sheet_name:
            return sheet_inv
    return {"shapes": [], "connectors": [], "pictures": []}


def _get_cell_markdown(workbook, sheet_name: str) -> str:
    """Get cell content as markdown for a sheet."""
    for sheet in workbook.sheets:
        if sheet.name == sheet_name:
            lines = []
            for block in sheet.cell_blocks:
                if block.markdown:
                    lines.append(block.markdown)
                elif block.data:
                    for row in block.data:
                        non_empty = [str(c) for c in row if c]
                        if non_empty:
                            lines.append(" | ".join(non_empty))
            return "\n".join(lines)
    return ""


if __name__ == "__main__":
    main()
