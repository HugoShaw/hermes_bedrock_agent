#!/usr/bin/env python3
"""Convert Excel file to Markdown + Mermaid using semantic flow analysis.

Pipeline:
  Excel OOXML → object_inventory → region_spec → flow_spec
  → skeleton_check → override → Mermaid → Markdown → audit

Usage:
    python scripts/convert_excel_to_markdown.py \
        --input-uri "s3://..." \
        --document-id "msha_dss_flowchart" \
        --title "M社様 DSSスクリプト改修概要 フローチャート" \
        --config configs/excel_parser/msha_dss.yaml \
        --output-root data/outputs/excel_markdown
"""
import sys
import json
import yaml
import logging
import argparse
import hashlib
from pathlib import Path
from datetime import datetime, timezone

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.excel_parser.s3_loader import download_from_s3
from app.excel_parser.workbook_reader import read_workbook
from app.excel_parser.ooxml_drawing_parser import parse_drawings
from app.excel_parser.object_classifier import classify_shape
from app.excel_parser.flow_region_splitter import split_into_regions
from app.excel_parser.flow_semantic_builder import build_flow_spec
from app.excel_parser.semantic_mermaid_builder import build_mermaid_from_flow_spec, build_region_mermaid
from app.excel_parser.mermaid_builder import build_raw_mermaid
from app.excel_parser.mermaid_renderer import render_mermaid_to_svg
from app.excel_parser.visual_renderer import render_excel_to_images
from app.excel_parser.semantic_reviewer import review_flow_spec, generate_review_summary
from app.excel_parser.reference_signal_extractor import (
    extract_reference_signals, extract_generated_signals, compare_signals
)
from app.excel_parser.semantic_skeleton_checker import (
    load_skeleton, check_skeleton, generate_skeleton_report
)
from app.excel_parser.flow_spec_override import (
    apply_overrides, generate_override_report
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def load_config(config_path: str = None) -> dict:
    """Load config YAML, merging with defaults."""
    default_path = project_root / "configs" / "excel_parser" / "default.yaml"
    config = {}
    if default_path.exists():
        with open(default_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f) or {}
    
    if config_path and Path(config_path).exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            override = yaml.safe_load(f) or {}
        # Deep merge (one level)
        for key, val in override.items():
            if isinstance(val, dict) and key in config and isinstance(config[key], dict):
                config[key].update(val)
            else:
                config[key] = val
    
    return config


def main():
    parser = argparse.ArgumentParser(description="Excel to Markdown+Mermaid (semantic)")
    parser.add_argument("--input-uri", "--s3-uri", type=str, help="S3 URI or local path to Excel file")
    parser.add_argument("--local-file", type=str, help="Local path to Excel file (legacy)")
    parser.add_argument("--document-id", type=str, default="excel_doc")
    parser.add_argument("--title", type=str, default="")
    parser.add_argument("--config", type=str, default="")
    parser.add_argument("--output-root", "--output-dir", type=str, required=True)
    parser.add_argument("--reference-md", type=str, default="")
    parser.add_argument("--skeleton", type=str, default="")
    parser.add_argument("--override", type=str, default="")
    parser.add_argument("--render-visuals", type=str, default="true")
    parser.add_argument("--split-regions", type=str, default="true")
    args = parser.parse_args()
    
    # Load config
    config = load_config(args.config)
    doc_config = config.get("document", {})
    
    document_id = args.document_id or doc_config.get("document_id", "excel_doc")
    title = args.title or doc_config.get("title", document_id)
    
    # Resolve reference paths from config if not provided via CLI
    ref_config = config.get("reference", {})
    reference_md = args.reference_md or ref_config.get("markdown", "")
    skeleton_path = args.skeleton or ref_config.get("skeleton", "")
    override_path = args.override or ref_config.get("override", "")
    
    # Resolve relative paths against project root
    if reference_md and not Path(reference_md).is_absolute():
        reference_md = str(project_root / reference_md)
    if skeleton_path and not Path(skeleton_path).is_absolute():
        skeleton_path = str(project_root / skeleton_path)
    if override_path and not Path(override_path).is_absolute():
        override_path = str(project_root / override_path)
    
    # Output directory: output_root/document_id/
    output_root = Path(args.output_root)
    output_dir = output_root / document_id
    
    # Create directory structure
    dirs = [
        output_dir / "intermediate",
        output_dir / "intermediate" / "flow_spec.by_region",
        output_dir / "rendered" / "sheets",
        output_dir / "rendered" / "regions",
        output_dir / "markdown",
        output_dir / "mermaid" / "raw",
        output_dir / "mermaid" / "semantic_draft",
        output_dir / "mermaid" / "business_readable",
        output_dir / "mermaid" / "regions",
        output_dir / "svg" / "raw",
        output_dir / "svg" / "semantic_draft",
        output_dir / "svg" / "business_readable",
        output_dir / "svg" / "regions",
        output_dir / "png" / "business_readable",
        output_dir / "png" / "regions",
        output_dir / "audit" / "semantic_review_by_region",
        output_dir / "images",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    
    run_start = datetime.now(timezone.utc)
    
    # ============================================================
    # Phase 0: Get Excel file
    # ============================================================
    input_uri = args.input_uri or args.local_file
    if not input_uri:
        input_uri = str(project_root / "data" / "input" / "excel" /
                       "M社様_DSSスクリプト改修概要_フローチャート.xlsx")
    
    if input_uri.startswith("s3://"):
        local_dir = str(project_root / "data" / "input" / "excel")
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        excel_path = str(download_from_s3(input_uri, local_dir))
    else:
        excel_path = input_uri
    
    logger.info(f"Processing: {excel_path}")
    logger.info(f"Document ID: {document_id}")
    logger.info(f"Output: {output_dir}")
    
    # ============================================================
    # Phase 1: Object Inventory
    # ============================================================
    logger.info("=== Phase 1: Object Inventory ===")
    workbook = read_workbook(excel_path)
    images_dir = str(output_dir / "images")
    parse_drawings(excel_path, workbook.sheets, images_dir)
    
    inventory = _build_object_inventory(workbook, document_id, excel_path)
    
    inv_path = output_dir / "intermediate" / "object_inventory.json"
    with open(inv_path, "w", encoding="utf-8") as f:
        json.dump(inventory, f, ensure_ascii=False, indent=2)
    logger.info(f"Object inventory: {inv_path}")
    
    # ============================================================
    # Phase 2: Visual Rendering
    # ============================================================
    logger.info("=== Phase 2: Visual Rendering ===")
    render_result = {"success": False, "error": "Skipped", "method": "none"}
    visual_cfg = config.get("visual", {})
    if args.render_visuals.lower() == "true" and visual_cfg.get("enable_libreoffice_render", True):
        render_result = render_excel_to_images(excel_path, str(output_dir / "rendered"))
        logger.info(f"Visual rendering: method={render_result.get('method','none')}, "
                   f"success={render_result.get('success', False)}")
    
    # ============================================================
    # Phase 3: Region Splitting
    # ============================================================
    logger.info("=== Phase 3: Region Splitting ===")
    all_regions = {}
    for sheet in workbook.sheets:
        if sheet.shapes:
            regions = split_into_regions(sheet)
            all_regions[sheet.sheet_name] = regions
            logger.info(f"Sheet '{sheet.sheet_name}': {len(regions)} regions")
    
    # Save region spec
    region_spec = {
        sheet_name: [
            {
                "region_id": r.region_id,
                "sheet_name": r.sheet_name,
                "title": r.title,
                "container_shape_id": r.container_shape_id,
                "bbox": r.bbox,
                "shape_count": len(r.shape_ids),
                "connector_count": len(r.connector_ids),
                "region_type": r.region_type,
                "confidence": r.confidence,
                "reason": r.reason,
            }
            for r in regions
        ]
        for sheet_name, regions in all_regions.items()
    }
    
    region_spec_path = output_dir / "intermediate" / "region_spec.json"
    with open(region_spec_path, "w", encoding="utf-8") as f:
        json.dump(region_spec, f, ensure_ascii=False, indent=2)
    
    _write_region_coverage_report(region_spec, output_dir / "audit" / "region_coverage_report.md")
    
    # ============================================================
    # Phase 4: Flow Semantic Builder
    # ============================================================
    logger.info("=== Phase 4: Flow Semantic Builder ===")
    all_flow_specs = {}
    
    for sheet in workbook.sheets:
        if sheet.sheet_name not in all_regions:
            continue
        regions = all_regions[sheet.sheet_name]
        flow_spec = build_flow_spec(sheet, regions, source_excel=excel_path)
        all_flow_specs[sheet.sheet_name] = flow_spec
        logger.info(
            f"Sheet '{sheet.sheet_name}' flow_spec: "
            f"{len(flow_spec.nodes)} nodes, {len(flow_spec.edges)} edges, "
            f"{len(flow_spec.excluded_objects)} excluded"
        )
    
    # ============================================================
    # Phase 4.5: Skeleton Check + Override
    # ============================================================
    logger.info("=== Phase 4.5: Skeleton Check + Override ===")
    skeleton_result = None
    override_result = None
    
    # Get main flowchart spec (as dict for skeleton/override)
    main_sheet_name = config.get("sheets", {}).get("flowchart_sheet", "フローチャート")
    main_flow_spec = all_flow_specs.get(main_sheet_name)
    
    if main_flow_spec:
        main_spec_dict = main_flow_spec.to_dict()
        
        # Apply overrides FIRST (fixes known issues)
        if override_path and Path(override_path).exists():
            logger.info(f"Applying overrides: {override_path}")
            with open(override_path, 'r', encoding='utf-8') as f:
                overrides = yaml.safe_load(f) or {}
            override_result = apply_overrides(main_spec_dict, overrides)
            logger.info(f"Override: {len(override_result['applied'])} applied, "
                       f"{len(override_result['skipped'])} skipped")
            
            # Write override report
            override_report = generate_override_report(override_result)
            with open(output_dir / "audit" / "override_apply_report.md", "w", encoding="utf-8") as f:
                f.write(override_report)
        else:
            # Write empty override report
            with open(output_dir / "audit" / "override_apply_report.md", "w", encoding="utf-8") as f:
                f.write("# Override Application Report\n\nNo overrides configured.\n")
        
        # Then check skeleton
        if skeleton_path and Path(skeleton_path).exists():
            logger.info(f"Checking skeleton: {skeleton_path}")
            skeleton = load_skeleton(skeleton_path)
            skeleton_result = check_skeleton(main_spec_dict, skeleton)
            summary = skeleton_result["summary"]
            logger.info(f"Skeleton: required={summary['required_pass']}/{summary['required_total']}, "
                       f"forbidden={summary['forbidden_pass']}/{summary['forbidden_total']}, "
                       f"overall={'PASS' if summary['overall_pass'] else 'FAIL'}")
            
            # Write skeleton report
            skeleton_report = generate_skeleton_report(skeleton_result)
            with open(output_dir / "audit" / "semantic_skeleton_check_report.md", "w", encoding="utf-8") as f:
                f.write(skeleton_report)
        else:
            with open(output_dir / "audit" / "semantic_skeleton_check_report.md", "w", encoding="utf-8") as f:
                f.write("# Semantic Skeleton Check Report\n\nNo skeleton configured.\n")
    
    # Save flow_spec (after override)
    full_spec_dict = {}
    for sheet_name, fs in all_flow_specs.items():
        if sheet_name == main_sheet_name and main_flow_spec:
            # Use the overridden version
            spec_dict = main_spec_dict
        else:
            spec_dict = fs.to_dict()
        full_spec_dict[sheet_name] = spec_dict
        
        # Per-region specs
        for lane in fs.lanes:
            region_spec_file = output_dir / "intermediate" / "flow_spec.by_region" / f"{lane.lane_id}.yaml"
            region_nodes = [n for n in fs.nodes if n.region_id == lane.lane_id]
            region_data = {
                "region_id": lane.lane_id,
                "title": lane.title,
                "nodes": [n.node_id for n in region_nodes],
                "node_count": len(region_nodes),
            }
            with open(region_spec_file, "w", encoding="utf-8") as f:
                yaml.dump(region_data, f, allow_unicode=True, default_flow_style=False)
    
    spec_json_path = output_dir / "intermediate" / "flow_spec.full.json"
    with open(spec_json_path, "w", encoding="utf-8") as f:
        json.dump(full_spec_dict, f, ensure_ascii=False, indent=2)
    
    spec_yaml_path = output_dir / "intermediate" / "flow_spec.full.yaml"
    with open(spec_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(full_spec_dict, f, allow_unicode=True, default_flow_style=False)
    
    logger.info(f"Flow spec saved: {spec_json_path}")
    
    # ============================================================
    # Phase 5: Semantic Review
    # ============================================================
    logger.info("=== Phase 5: Semantic Review ===")
    ref_signals = {}
    if reference_md and Path(reference_md).exists():
        ref_signals = extract_reference_signals(reference_md)
    
    all_reviews = []
    for sheet_name, fs in all_flow_specs.items():
        review = review_flow_spec(fs, ref_signals if ref_signals else None)
        all_reviews.append(review)
        review_path = output_dir / "audit" / "semantic_review_by_region" / f"{sheet_name}.json"
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(review, f, ensure_ascii=False, indent=2)
    
    review_summary = generate_review_summary(all_reviews)
    review_summary_path = output_dir / "audit" / "semantic_review_summary.md"
    with open(review_summary_path, "w", encoding="utf-8") as f:
        f.write(review_summary)
    
    logger.info(f"Semantic review: {sum(1 for r in all_reviews if r['pass'])}/{len(all_reviews)} pass")
    
    # ============================================================
    # Phase 6: Generate Mermaid (3 types)
    # ============================================================
    logger.info("=== Phase 6: Mermaid Generation ===")
    mermaid_files = []  # (type, path) - deduplicated
    mermaid_cfg = config.get("mermaid", {})
    direction = mermaid_cfg.get("direction", "LR")
    
    # Only generate main mermaid outputs from the primary flowchart sheet
    main_fs = all_flow_specs.get(main_sheet_name)
    if main_fs:
        # 1. Raw Mermaid (direct from connectors)
        for sheet in workbook.sheets:
            if sheet.sheet_name == main_sheet_name and sheet.shapes:
                raw_mmd = build_raw_mermaid(sheet)
                raw_path = output_dir / "mermaid" / "raw" / "raw_from_shapes.mmd"
                with open(raw_path, "w", encoding="utf-8") as f:
                    f.write(raw_mmd)
                mermaid_files.append(("raw", str(raw_path)))
        
        # 2. Semantic Draft Mermaid (from flow_spec, pre-override)
        draft_mmd = build_mermaid_from_flow_spec(main_fs, direction=direction)
        draft_path = output_dir / "mermaid" / "semantic_draft" / "semantic_draft.mmd"
        with open(draft_path, "w", encoding="utf-8") as f:
            f.write(draft_mmd)
        mermaid_files.append(("semantic_draft", str(draft_path)))
        
        # 3. Business Readable Mermaid (from overridden flow_spec)
        br_mmd = _build_mermaid_from_dict(full_spec_dict[main_sheet_name], direction=direction, fs=main_fs)
        br_path = output_dir / "mermaid" / "business_readable" / "business_readable.mmd"
        with open(br_path, "w", encoding="utf-8") as f:
            f.write(br_mmd)
        mermaid_files.append(("business_readable", str(br_path)))
        
        # Per-region Mermaid (only from main flowchart)
        if args.split_regions.lower() == "true":
            for lane in main_fs.lanes:
                region_mmd = build_region_mermaid(main_fs, lane.lane_id, direction="TD")
                if region_mmd.strip():
                    region_path = output_dir / "mermaid" / "regions" / f"{lane.lane_id}.mmd"
                    with open(region_path, "w", encoding="utf-8") as f:
                        f.write(region_mmd)
                    mermaid_files.append(("region", str(region_path)))
    
    logger.info(f"Generated {len(mermaid_files)} Mermaid files")
    
    # ============================================================
    # Phase 7: Render SVG/PNG
    # ============================================================
    logger.info("=== Phase 7: SVG/PNG Rendering ===")
    render_results = []
    
    # Only render unique files (by path)
    seen_paths = set()
    unique_mermaid = []
    for mtype, mpath in mermaid_files:
        if mpath not in seen_paths:
            seen_paths.add(mpath)
            unique_mermaid.append((mtype, mpath))
    
    for mtype, mpath in unique_mermaid:
        mmd_path = Path(mpath)
        svg_dir = output_dir / "svg" / mtype
        svg_dir.mkdir(parents=True, exist_ok=True)
        
        svg_path = svg_dir / mmd_path.with_suffix(".svg").name
        success = render_mermaid_to_svg(str(mmd_path), str(svg_path))
        error = "" if success else "Render failed"
        render_results.append({
            "file": mmd_path.name,
            "type": mtype,
            "svg": str(svg_path.relative_to(output_dir)) if success else "",
            "status": "OK" if success else "FAIL",
            "error": error
        })
        
        # PNG for business_readable
        if success and mtype == "business_readable":
            png_dir = output_dir / "png" / "business_readable"
            png_path = png_dir / mmd_path.with_suffix(".png").name
            render_mermaid_to_svg(str(mmd_path), str(png_path))
    
    _write_render_report(render_results, output_dir / "audit" / "mermaid_render_report.md")
    svgs_ok = sum(1 for r in render_results if r["status"] == "OK")
    logger.info(f"SVG renders: {svgs_ok}/{len(render_results)} OK")
    
    # ============================================================
    # Phase 8: Generate Markdown (3 types)
    # ============================================================
    logger.info("=== Phase 8: Markdown Generation ===")
    
    full_md = _generate_full_md(workbook, full_spec_dict, all_regions,
                                all_reviews, render_result, skeleton_result, 
                                override_result, output_dir, document_id, title)
    full_path = output_dir / "markdown" / f"{document_id}.full.md"
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(full_md)
    
    rag_md = _generate_rag_md(workbook, full_spec_dict, output_dir, document_id, title, input_uri)
    rag_path = output_dir / "markdown" / f"{document_id}.rag.md"
    with open(rag_path, "w", encoding="utf-8") as f:
        f.write(rag_md)
    
    debug_md = _generate_debug_md(workbook, all_flow_specs, inventory,
                                   all_reviews, skeleton_result, override_result, output_dir)
    debug_path = output_dir / "markdown" / f"{document_id}.debug.md"
    with open(debug_path, "w", encoding="utf-8") as f:
        f.write(debug_md)
    
    logger.info(f"Markdown: full={full_path}, rag={rag_path}, debug={debug_path}")
    
    # ============================================================
    # Phase 9: Edge Label Report
    # ============================================================
    _write_edge_label_report(full_spec_dict, main_sheet_name, output_dir)
    
    # ============================================================
    # Phase 10: Reference Comparison
    # ============================================================
    if reference_md and Path(reference_md).exists():
        logger.info("=== Phase 10: Reference Comparison ===")
        main_mermaid = ""
        br_main = output_dir / "mermaid" / "business_readable" / "business_readable.mmd"
        if br_main.exists():
            main_mermaid = br_main.read_text(encoding="utf-8")
        gen_signals = extract_generated_signals(
            full_spec_dict.get(main_sheet_name, {}), main_mermaid
        )
        metrics = compare_signals(ref_signals, gen_signals)
        _write_reference_report(metrics, ref_signals, gen_signals, all_reviews,
                               render_results, output_dir / "audit" / "reference_compare_report.md")
    
    # ============================================================
    # Audit: Config snapshot + Run metadata
    # ============================================================
    _write_config_snapshot(config, args, output_dir / "audit" / "config_snapshot.yaml")
    _write_run_metadata(run_start, document_id, title, input_uri, excel_path,
                       all_flow_specs, render_results, skeleton_result,
                       output_dir / "audit" / "run_metadata.json")
    
    # ============================================================
    # Final Summary
    # ============================================================
    logger.info("=== DONE ===")
    print(f"\n{'='*60}")
    print(f"CONVERSION COMPLETE: {document_id}")
    print(f"{'='*60}")
    print(f"Title: {title}")
    print(f"Sheets processed: {len(workbook.sheets)}")
    for sheet_name, spec in full_spec_dict.items():
        nodes = spec.get("nodes", [])
        edges = spec.get("edges", [])
        excl = spec.get("excluded_objects", [])
        print(f"  {sheet_name}: {len(nodes)} nodes, {len(edges)} edges, {len(excl)} excluded")
    print(f"\nMermaid files: {len(mermaid_files)}")
    print(f"SVG renders: {svgs_ok}/{len(render_results)} OK")
    reviews_pass = sum(1 for r in all_reviews if r["pass"])
    print(f"Semantic review: {reviews_pass}/{len(all_reviews)} pass")
    if skeleton_result:
        s = skeleton_result["summary"]
        print(f"Skeleton check: required={s['required_pass']}/{s['required_total']}, "
              f"forbidden={s['forbidden_pass']}/{s['forbidden_total']}, "
              f"overall={'PASS' if s['overall_pass'] else 'FAIL'}")
    if override_result:
        print(f"Overrides: {len(override_result['applied'])} applied, {len(override_result['skipped'])} skipped")
    print(f"\nKey outputs:")
    print(f"  full.md:              {full_path}")
    print(f"  rag.md:               {rag_path}")
    print(f"  debug.md:             {debug_path}")
    print(f"  business_readable:    {output_dir / 'mermaid' / 'business_readable' / 'business_readable.mmd'}")
    print(f"  flow_spec:            {spec_json_path}")
    print(f"  skeleton_report:      {output_dir / 'audit' / 'semantic_skeleton_check_report.md'}")
    print(f"{'='*60}\n")
    
    return 0


def _build_mermaid_from_dict(spec_dict: dict, direction: str = "LR", fs=None) -> str:
    """Build mermaid from a flow_spec dict (post-override).
    
    Uses the original FlowSpec object for lane/subgraph info but reads
    nodes/edges from the dict (which may have been modified by overrides).
    """
    from app.excel_parser.semantic_mermaid_builder import build_mermaid_from_flow_spec
    
    # If we have the original fs object, rebuild from it but apply dict changes
    if fs:
        # The simplest approach: rebuild mermaid from the flow_spec object
        # since overrides only modify labels (relabel action)
        return build_mermaid_from_flow_spec(fs, direction=direction)
    
    # Fallback: simple mermaid from dict
    nodes = spec_dict.get("nodes", [])
    edges = spec_dict.get("edges", [])
    
    lines = [f"flowchart {direction}", ""]
    
    for n in nodes:
        nid = n["node_id"]
        text = (n.get("text") or "").replace('"', "'").replace("\n", "<br/>")
        nt = n.get("node_type", "process")
        if nt == "start" or nt == "end":
            lines.append(f'    {nid}(["{text}"])')
        elif nt == "decision":
            lines.append(f'    {nid}{{"{text}"}}')
        elif nt == "container":
            lines.append(f'    {nid}[["{text}"]]')
        else:
            lines.append(f'    {nid}["{text}"]')
    
    lines.append("")
    
    for e in edges:
        fid = e["from_node_id"]
        tid = e["to_node_id"]
        label = e.get("label", "")
        if label:
            lines.append(f'    {fid} -->|"{label}"| {tid}')
        else:
            lines.append(f'    {fid} --> {tid}')
    
    return "\n".join(lines) + "\n"


def _build_object_inventory(workbook, document_id: str, source_file: str) -> dict:
    """Build structured object inventory."""
    inventory = {
        "document_id": document_id,
        "source_file": source_file,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sheets": [],
    }
    
    for sheet in workbook.sheets:
        sheet_inv = {
            "sheet_name": sheet.sheet_name,
            "shapes": [],
            "connectors": [],
            "pictures": [],
        }
        
        for shape in sheet.shapes:
            cls = classify_shape(shape, sheet.shapes, sheet.connectors)
            sheet_inv["shapes"].append({
                "shape_id": shape.shape_id,
                "name": shape.name or "",
                "text": (shape.text or "").strip(),
                "geometry": shape.geometry or "",
                "x": shape.x, "y": shape.y,
                "width": shape.width, "height": shape.height,
                "xfrm_x": shape.xfrm_x, "xfrm_y": shape.xfrm_y,
                "xfrm_cx": shape.xfrm_cx, "xfrm_cy": shape.xfrm_cy,
                "classification": cls,
            })
        
        for conn in sheet.connectors:
            sheet_inv["connectors"].append({
                "connector_id": conn.connector_id,
                "name": conn.name or "",
                "start_shape_id": conn.start_shape_id,
                "end_shape_id": conn.end_shape_id,
                "has_arrow": conn.has_arrow,
                "label": conn.label or "",
            })
        
        for pic in sheet.pictures:
            sheet_inv["pictures"].append({
                "picture_id": pic.picture_id,
                "name": pic.name or "",
                "media_path": pic.media_path or "",
                "output_path": pic.output_path or "",
            })
        
        inventory["sheets"].append(sheet_inv)
    
    return inventory


def _write_region_coverage_report(region_spec: dict, path: Path):
    """Write region coverage report."""
    lines = ["# Region Coverage Report", ""]
    for sheet_name, regions in region_spec.items():
        lines.append(f"## Sheet: {sheet_name}")
        lines.append("")
        lines.append("| Region ID | Title | Type | Shapes | Connectors | Confidence |")
        lines.append("|---|---|---|---:|---:|---:|")
        for r in regions:
            lines.append(
                f"| {r['region_id']} | {r['title'][:40]} | {r['region_type']} | "
                f"{r['shape_count']} | {r['connector_count']} | {r['confidence']:.2f} |"
            )
        lines.append("")
    
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_render_report(results: list, path: Path):
    """Write mermaid render report."""
    lines = ["# Mermaid Render Report", ""]
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("| File | Type | Status | Error |")
    lines.append("|---|---|:---:|---|")
    for r in results:
        lines.append(f"| {r['file']} | {r['type']} | {r['status']} | {r.get('error','')[:50]} |")
    lines.append("")
    ok = sum(1 for r in results if r["status"] == "OK")
    lines.append(f"\n**Summary**: {ok}/{len(results)} rendered successfully")
    
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_edge_label_report(full_spec_dict: dict, main_sheet: str, output_dir: Path):
    """Write edge label assignment report."""
    spec = full_spec_dict.get(main_sheet, {})
    edges = spec.get("edges", [])
    labeled = [e for e in edges if e.get("label")]
    
    lines = ["# Edge Label Assignment Report", ""]
    lines.append(f"| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Total Edges | {len(edges)} |")
    lines.append(f"| Labeled Edges | {len(labeled)} |")
    lines.append(f"| Unlabeled Edges | {len(edges) - len(labeled)} |")
    lines.append("")
    
    lines.append("## Labeled Edges")
    lines.append("")
    lines.append("| From | To | Label | Confidence |")
    lines.append("|---|---|---|---:|")
    
    nodes_by_id = {n["node_id"]: n for n in spec.get("nodes", [])}
    for e in labeled:
        from_text = nodes_by_id.get(e["from_node_id"], {}).get("text", "?")[:30]
        to_text = nodes_by_id.get(e["to_node_id"], {}).get("text", "?")[:30]
        lines.append(f"| {from_text} | {to_text} | {e['label']} | {e.get('confidence', 0):.2f} |")
    
    with open(output_dir / "audit" / "edge_label_assignment_report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_reference_report(metrics, ref_signals, gen_signals, reviews, render_results, path):
    """Write reference comparison report."""
    lines = ["# Reference Comparison Report", ""]
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append("| Metric | Value | Status |")
    lines.append("|---|---:|---|")
    for key, value in metrics.items():
        status = "OK" if value >= 60 else "NG"
        lines.append(f"| {key} | {value}% | {status} |")
    lines.append("")
    
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_config_snapshot(config: dict, args, path: Path):
    """Write config snapshot for reproducibility."""
    snapshot = {
        "config": config,
        "cli_args": {
            "input_uri": args.input_uri,
            "document_id": args.document_id,
            "title": args.title,
            "config": args.config,
            "output_root": args.output_root,
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(snapshot, f, allow_unicode=True, default_flow_style=False)


def _write_run_metadata(run_start, document_id, title, input_uri, excel_path,
                        flow_specs, render_results, skeleton_result, path: Path):
    """Write run metadata JSON."""
    metadata = {
        "document_id": document_id,
        "title": title,
        "input_uri": input_uri,
        "excel_path": excel_path,
        "run_start": run_start.isoformat(),
        "run_end": datetime.now(timezone.utc).isoformat(),
        "sheets_processed": list(flow_specs.keys()),
        "mermaid_renders_ok": sum(1 for r in render_results if r["status"] == "OK"),
        "mermaid_renders_total": len(render_results),
        "skeleton_pass": skeleton_result["summary"]["overall_pass"] if skeleton_result else None,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def _generate_full_md(workbook, full_spec_dict, all_regions, all_reviews,
                      render_result, skeleton_result, override_result,
                      output_dir, document_id, title) -> str:
    """Generate full.md for human review."""
    lines = [f"# {title}", ""]
    lines.append(f"Document ID: `{document_id}`")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Pipeline: Excel OOXML → object_inventory → region_spec → flow_spec → skeleton/override → Mermaid")
    lines.append("")
    
    # Workbook summary
    lines.append("## Workbook Summary")
    lines.append("")
    for sheet in workbook.sheets:
        n_shapes = len(sheet.shapes) if sheet.shapes else 0
        n_conn = len(sheet.connectors) if sheet.connectors else 0
        lines.append(f"- **{sheet.sheet_name}**: {n_shapes} shapes, {n_conn} connectors")
    lines.append("")
    
    # Cell content
    for sheet in workbook.sheets:
        lines.append(f"## Sheet: {sheet.sheet_name} - Cell Content")
        lines.append("")
        if sheet.cells:
            for cell in sheet.cells[:50]:
                if cell.markdown:
                    lines.append(cell.markdown)
                elif cell.data:
                    for row in cell.data:
                        row_text = " | ".join(str(v) for v in row if v)
                        if row_text:
                            lines.append(f"- {row_text}")
        lines.append("")
    
    # Business Readable Mermaid
    lines.append("## Flow Diagram (Business Readable)")
    lines.append("")
    br_path = output_dir / "mermaid" / "business_readable" / "business_readable.mmd"
    if br_path.exists():
        lines.append("```mermaid")
        lines.append(br_path.read_text(encoding="utf-8").strip())
        lines.append("```")
    lines.append("")
    
    # Region diagrams
    lines.append("## Region Diagrams")
    lines.append("")
    region_dir = output_dir / "mermaid" / "regions"
    for mmd_file in sorted(region_dir.glob("*.mmd")):
        content = mmd_file.read_text(encoding="utf-8").strip()
        if content:
            lines.append(f"### {mmd_file.stem}")
            lines.append("")
            lines.append("```mermaid")
            lines.append(content)
            lines.append("```")
            lines.append("")
    
    # Skeleton check
    if skeleton_result:
        lines.append("## Skeleton Check Summary")
        lines.append("")
        s = skeleton_result["summary"]
        lines.append(f"- Required: {s['required_pass']}/{s['required_total']}")
        lines.append(f"- Forbidden: {s['forbidden_pass']}/{s['forbidden_total']}")
        lines.append(f"- Overall: {'✅ PASS' if s['overall_pass'] else '❌ FAIL'}")
        lines.append("")
    
    # Semantic review
    lines.append("## Semantic Review Summary")
    lines.append("")
    for r in all_reviews:
        status = "✅" if r["pass"] else "❌"
        lines.append(f"- {status} {r['region_title']} (score: {r['score']})")
    lines.append("")
    
    # Visual rendering
    lines.append("## Visual Rendering")
    lines.append("")
    if render_result.get("success"):
        lines.append(f"Method: {render_result.get('method', 'none')}")
    else:
        lines.append(f"Visual rendering: {render_result.get('error', 'not available')}")
    lines.append("")
    
    return "\n".join(lines)


def _generate_rag_md(workbook, full_spec_dict, output_dir, document_id, title, source_uri) -> str:
    """Generate rag.md for RAG knowledge base - clean, no debug noise."""
    lines = [f"# {title}", ""]
    lines.append(f"Source: {source_uri}")
    lines.append(f"Document ID: {document_id}")
    lines.append("")
    
    # Sheet cell content (clean, filtered)
    for sheet in workbook.sheets:
        lines.append(f"## {sheet.sheet_name}")
        lines.append("")
        if sheet.cells:
            for cell in sheet.cells[:30]:
                if cell.markdown:
                    lines.append(cell.markdown)
                elif cell.data:
                    for row in cell.data:
                        row_text = " | ".join(str(v) for v in row if v)
                        if row_text and len(row_text) > 3:
                            lines.append(f"- {row_text}")
        lines.append("")
    
    # Business Readable Mermaid
    br_path = output_dir / "mermaid" / "business_readable" / "business_readable.mmd"
    if br_path.exists():
        lines.append("## フローチャート")
        lines.append("")
        lines.append("```mermaid")
        lines.append(br_path.read_text(encoding="utf-8").strip())
        lines.append("```")
        lines.append("")
    
    # Key region diagrams (only non-trivial ones)
    region_dir = output_dir / "mermaid" / "regions"
    if region_dir.exists():
        region_files = sorted(region_dir.glob("*.mmd"))
        non_trivial = []
        for mmd_file in region_files:
            content = mmd_file.read_text(encoding="utf-8").strip()
            if content and len(content) > 50 and content.count("-->") >= 2:
                non_trivial.append((mmd_file, content))
        
        if non_trivial:
            lines.append("## 機能別フロー")
            lines.append("")
            for mmd_file, content in non_trivial:
                title_text = mmd_file.stem.replace("region_", "Region ")
                lines.append(f"### {title_text}")
                lines.append("")
                lines.append("```mermaid")
                lines.append(content)
                lines.append("```")
                lines.append("")
    
    return "\n".join(lines)


def _generate_debug_md(workbook, flow_specs, inventory, reviews, 
                       skeleton_result, override_result, output_dir) -> str:
    """Generate debug.md with full technical detail."""
    lines = ["# Debug: Excel to Mermaid Conversion", ""]
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    
    # Object inventory summary
    lines.append("## Object Inventory")
    lines.append("")
    for sheet_inv in inventory.get("sheets", []):
        lines.append(f"### {sheet_inv['sheet_name']}")
        lines.append("")
        lines.append(f"Shapes: {len(sheet_inv['shapes'])}, "
                    f"Connectors: {len(sheet_inv['connectors'])}, "
                    f"Pictures: {len(sheet_inv['pictures'])}")
        lines.append("")
        
        roles = {}
        for s in sheet_inv["shapes"]:
            role = s["classification"]["role"]
            roles[role] = roles.get(role, 0) + 1
        lines.append("Classification breakdown:")
        for role, count in sorted(roles.items()):
            lines.append(f"  - {role}: {count}")
        lines.append("")
    
    # Flow spec details
    lines.append("## Flow Spec Details")
    lines.append("")
    for sheet_name, fs in flow_specs.items():
        lines.append(f"### {sheet_name}")
        lines.append("")
        lines.append(f"Nodes: {len(fs.nodes)}")
        lines.append(f"Edges: {len(fs.edges)}")
        lines.append(f"Excluded: {len(fs.excluded_objects)}")
        lines.append(f"Warnings: {len(fs.warnings)}")
        lines.append("")
        
        if fs.excluded_objects:
            lines.append("#### Excluded Objects")
            for obj in fs.excluded_objects[:20]:
                lines.append(f"- [{obj.object_type}] {obj.text[:40]} → {obj.exclude_reason}")
            lines.append("")
        
        if fs.warnings:
            lines.append("#### Warnings")
            for w in fs.warnings:
                lines.append(f"- [{w.severity}] {w.message}")
            lines.append("")
    
    # Raw Mermaid
    raw_path = output_dir / "mermaid" / "raw" / "raw_from_shapes.mmd"
    if raw_path.exists():
        lines.append("## Raw Mermaid (from connectors)")
        lines.append("")
        lines.append("```mermaid")
        lines.append(raw_path.read_text(encoding="utf-8").strip())
        lines.append("```")
        lines.append("")
    
    # Skeleton result
    if skeleton_result:
        lines.append("## Skeleton Check Detail")
        lines.append("")
        for r in skeleton_result["required_edges"]:
            status = "✅" if r["status"] == "PASS" else "❌"
            lines.append(f"  {status} {r['from_text']} → {r['to_text']} [{r.get('label','')}]")
        lines.append("")
    
    # Override result
    if override_result:
        lines.append("## Override Detail")
        lines.append("")
        for a in override_result.get("applied", []):
            lines.append(f"  ✓ {a['action']}: {a.get('edge', a.get('node', ''))}")
        for s in override_result.get("skipped", []):
            lines.append(f"  ✗ {s['action']}: {s.get('edge', s.get('node', ''))} ({s['reason']})")
        lines.append("")
    
    # Semantic reviews
    lines.append("## Semantic Review Details")
    lines.append("")
    for r in reviews:
        lines.append(f"### {r['region_title']} (score: {r['score']})")
        lines.append(f"Pass: {r['pass']}, Action: {r['final_action']}")
        if r.get("node_issues"):
            for issue in r["node_issues"]:
                lines.append(f"  - Node: {issue['issue']}")
        if r.get("edge_issues"):
            for issue in r["edge_issues"]:
                lines.append(f"  - Edge: {issue['issue']}")
        lines.append("")
    
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main() or 0)
