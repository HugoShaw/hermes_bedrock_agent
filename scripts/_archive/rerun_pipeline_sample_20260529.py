#!/usr/bin/env python3
"""
Full pipeline rerun for sample_20260529 project.

Orchestrates the entire Dual-RAG pipeline:
1. Excel → PDF (LibreOffice UNO — requires /usr/bin/python3 subprocess)
2. PDF → Images (pdf2image)
3. Images → VLM Markdown (Bedrock Claude Sonnet multimodal)
4. Markdown → Chunks → LanceDB (vector embeddings)
5. Markdown → Graph → Neptune (knowledge graph)
6. Validate QA retrieval

Project identity:
  project_id = sample_20260529
  project_name = サンプル20260529

RUN: cd ~/projects/hermes_bedrock_agent && source .venv/bin/activate && python scripts/rerun_pipeline_sample_20260529.py
"""

from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure we're running from the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Load .env
from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from hermes_bedrock_agent.config import config

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

PROJECT_ID = "sample_20260529"
PROJECT_NAME = "サンプル20260529"
SOURCE_DIR = PROJECT_ROOT / "outputs" / "サンプル20260529"

# We'll discover workbooks dynamically
WB1_XLSX = SOURCE_DIR / "01_基本設計" / "M社様_DSSスクリプト改修概要_フローチャート.xlsx"
WB2_XLSX = SOURCE_DIR / "02_詳細設計" / "MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx"

FLOWCHART_MMD = SOURCE_DIR / "01_基本設計" / "flowchart.mmd"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(SOURCE_DIR / "pipeline.log", mode="w"),
    ],
)
logger = logging.getLogger("pipeline")


# ──────────────────────────────────────────────────────────────────────────────
# Step 1: Excel → PDF via system python3 subprocess
# ──────────────────────────────────────────────────────────────────────────────

def step1_excel_to_pdf(xlsx_path: Path, pdf_dir: Path) -> list[dict]:
    """Convert Excel workbook to per-sheet PDFs using system python3 + UNO."""
    pdf_dir.mkdir(parents=True, exist_ok=True)
    
    script = f'''
import json, os, sys, logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
sys.path.insert(0, "{PROJECT_ROOT / 'src'}")
from hermes_bedrock_agent.parsing.excel_parser import convert_excel_to_pdfs

results = convert_excel_to_pdfs("{xlsx_path}", "{pdf_dir}")
out = []
for r in results:
    out.append({{
        "index": r.sheet_info.index,
        "name": r.sheet_info.name,
        "pdf_path": r.pdf_path,
        "pages": r.pages,
        "cols": r.sheet_info.cols,
        "rows": r.sheet_info.rows,
        "has_shapes": r.sheet_info.has_shapes,
        "page_width_pt": r.sheet_info.page_width_pt,
        "page_height_pt": r.sheet_info.page_height_pt,
    }})
# Output JSON on last line
print("__JSON__" + json.dumps(out, ensure_ascii=False))
'''
    
    script_path = Path("/tmp/_excel_to_pdf.py")
    script_path.write_text(script)
    
    logger.info("Step 1: Excel → PDF: %s", xlsx_path.name)
    result = subprocess.run(
        ["/usr/bin/python3", str(script_path)],
        capture_output=True, text=True, timeout=300,
    )
    
    if result.returncode != 0:
        logger.error("  STDERR: %s", result.stderr[-2000:])
        raise RuntimeError(f"Excel→PDF failed: {xlsx_path.name}")
    
    # Extract JSON from output
    for line in result.stdout.split("\n"):
        if line.startswith("__JSON__"):
            sheets = json.loads(line[8:])
            break
    else:
        raise RuntimeError("No JSON output from Excel→PDF script")
    
    ok = sum(1 for s in sheets if s["pdf_path"])
    logger.info("  → %d/%d sheets exported to PDF", ok, len(sheets))
    return sheets


# ──────────────────────────────────────────────────────────────────────────────
# Step 2: PDF → Images
# ──────────────────────────────────────────────────────────────────────────────

def step2_pdf_to_images(pdf_sheets: list[dict], image_dir: Path) -> list:
    """Render PDFs to images using pdf2image."""
    from hermes_bedrock_agent.parsing.models import SheetInfo, SheetPDF
    from hermes_bedrock_agent.parsing.pdf_parser import render_all_sheets
    
    image_dir.mkdir(parents=True, exist_ok=True)
    
    sheet_pdfs = []
    for s in pdf_sheets:
        if not s["pdf_path"] or not os.path.exists(s["pdf_path"]):
            logger.warning("  Skipping sheet %d — no PDF", s["index"])
            continue
        info = SheetInfo(
            index=s["index"],
            name=s["name"],
            rows=s["rows"],
            cols=s["cols"],
            has_shapes=s.get("has_shapes", False),
            page_width_pt=s.get("page_width_pt", 0.0),
            page_height_pt=s.get("page_height_pt", 0.0),
        )
        sp = SheetPDF(
            sheet_info=info,
            pdf_path=s["pdf_path"],
            pages=s["pages"],
            page_size=(s.get("page_width_pt", 0.0), s.get("page_height_pt", 0.0)),
        )
        sheet_pdfs.append(sp)
    
    logger.info("Step 2: PDF → Images: %d sheets → %s", len(sheet_pdfs), image_dir)
    images = render_all_sheets(sheet_pdfs, str(image_dir))
    logger.info("  → %d sheet images rendered", len(images))
    return images


# ──────────────────────────────────────────────────────────────────────────────
# Step 3: Images → VLM Markdown (the long step)
# ──────────────────────────────────────────────────────────────────────────────

def step3_vlm_parsing(all_images: list, vlm_dir: Path) -> list:
    """VLM-parse all sheet images to markdown via Bedrock Claude Sonnet."""
    from hermes_bedrock_agent.parsing.vlm_client import parse_all_sheets
    
    vlm_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Step 3: VLM Parsing: %d sheets → %s", len(all_images), vlm_dir)
    logger.info("  Model: %s", config.vlm_model_id)
    logger.info("  ⚠️  This will take ~90 minutes for 27 sheets. Do NOT interrupt.")
    
    results = parse_all_sheets(all_images, str(vlm_dir), resume=True)
    
    parsed_ok = sum(1 for r in results if len(r.markdown) > 200)
    total_chars = sum(len(r.markdown) for r in results)
    logger.info("  → %d/%d sheets parsed (%d total chars)", parsed_ok, len(results), total_chars)
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Step 4: Chunks → LanceDB
# ──────────────────────────────────────────────────────────────────────────────

def step4_build_vector_kb(vlm_dir: Path, wb_name: str, s3_project_prefix: str, is_first_workbook: bool = True) -> dict:
    """Chunk markdown and embed into LanceDB with correct metadata.
    
    Args:
        vlm_dir: Path to vlm_parsed directory.
        wb_name: Workbook name.
        s3_project_prefix: S3 prefix for original project files.
        is_first_workbook: If True, delete existing project rows before insert.
            If False, append without deleting (multi-workbook pipeline).
    """
    from hermes_bedrock_agent.knowledge_base.chunker import build_chunks
    from hermes_bedrock_agent.knowledge_base.vector_store import load_vector_store
    
    dual_rag_dir = vlm_dir.parent / "dual_rag"
    dual_rag_dir.mkdir(parents=True, exist_ok=True)
    chunks_jsonl = dual_rag_dir / "chunks.jsonl"
    
    # CRITICAL: Include project name in S3 paths for correct evidence tracing
    dir_name = vlm_dir.parent.name
    s3_pdf_prefix = f"outputs/{PROJECT_NAME}/{dir_name}/pdf"
    s3_vlm_prefix = f"outputs/{PROJECT_NAME}/{dir_name}/vlm_parsed"
    
    # Check for sheet_name_mapping.csv
    mapping_csv = vlm_dir.parent / "sheet_name_mapping.csv"
    
    logger.info("Step 4: Building vector KB (project_id=%s, wb=%s)", PROJECT_ID, wb_name)
    logger.info("  S3 PDF prefix: %s", s3_pdf_prefix)
    logger.info("  S3 VLM prefix: %s", s3_vlm_prefix)
    logger.info("  is_first_workbook=%s (replace_project=%s)", is_first_workbook, is_first_workbook)
    
    chunks = build_chunks(
        vlm_parsed_dir=vlm_dir,
        sheet_name_mapping_csv=mapping_csv if mapping_csv.exists() else None,
        workbook_name=wb_name,
        s3_bucket=config.s3_bucket,
        s3_pdf_prefix=s3_pdf_prefix,
        s3_vlm_prefix=s3_vlm_prefix,
        s3_excel_key=f"{s3_project_prefix}/{wb_name}.xlsx",
        output_path=chunks_jsonl,
        project_id=PROJECT_ID,
    )
    logger.info("  → %d chunks built → %s", len(chunks), chunks_jsonl)
    
    result = {"chunks": len(chunks), "vector_written": 0}
    
    if chunks:
        logger.info("  Loading into LanceDB...")
        written = load_vector_store(chunks, project_id=PROJECT_ID, replace_project=is_first_workbook)
        result["vector_written"] = written
        logger.info("  → %d records written to LanceDB", written)
    
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Step 5: Graph Extraction → Neptune
# ──────────────────────────────────────────────────────────────────────────────

def step5_build_graph(project_dir: Path) -> dict:
    """Extract graph from vlm_parsed markdown and load into Neptune."""
    from hermes_bedrock_agent.graph_pipeline import run_pipeline, GraphPipelineConfig
    
    cfg = GraphPipelineConfig(
        project_id=PROJECT_ID,
        project_name=PROJECT_NAME,
        dry_run=False,
        skip_load=False,
        output_dir=str(project_dir / "graph_output"),
        llm_delay_seconds=3.0,
    )
    
    logger.info("Step 5: Graph extraction → Neptune")
    logger.info("  project_dir: %s", project_dir)
    logger.info("  project_id: %s, project_name: %s", PROJECT_ID, PROJECT_NAME)
    
    result = run_pipeline(str(project_dir), cfg)
    
    stats = {
        "nodes": len(result.nodes),
        "edges": len(result.edges),
        "validation_errors": len(result.validation_errors),
        "load_stats": result.load_stats,
        "output_dir": result.output_dir,
    }
    logger.info("  → %d nodes, %d edges loaded", stats["nodes"], stats["edges"])
    if stats["validation_errors"]:
        logger.warning("  → %d validation errors", stats["validation_errors"])
    return stats


# ──────────────────────────────────────────────────────────────────────────────
# Step 6: Validate QA
# ──────────────────────────────────────────────────────────────────────────────

def step6_validate_qa() -> dict:
    """Test QA retrieval for the new project."""
    from hermes_bedrock_agent.knowledge_base.vector_store import query_vector_store
    
    validation = {
        "vector_search": False,
        "vector_count": 0,
        "graph_query": False,
        "graph_node_count": 0,
        "evidence_path_correct": False,
        "old_project_intact": False,
    }
    
    # Test 1: Vector search for new project
    logger.info("Step 6: QA Validation")
    logger.info("  6a. Testing vector search for project_id=%s...", PROJECT_ID)
    try:
        results = query_vector_store("発注情報 マッピング", project_id=PROJECT_ID, top_k=5)
        if results:
            validation["vector_search"] = True
            validation["vector_count"] = len(results)
            logger.info("    → %d results found ✓", len(results))
            
            # Check evidence path contains new project name
            for r in results:
                meta = r.get("metadata", r) if isinstance(r, dict) else {}
                s3_path = meta.get("source_pdf_s3_path", "") or ""
                if PROJECT_NAME in s3_path:
                    validation["evidence_path_correct"] = True
                    logger.info("    → Evidence path correct: %s ✓", s3_path[:80])
                    break
            if not validation["evidence_path_correct"]:
                logger.warning("    → Evidence path missing project name!")
        else:
            logger.warning("    → No results for new project!")
    except Exception as e:
        logger.error("    → Vector search failed: %s", e)
    
    # Test 2: Graph query for new project
    logger.info("  6b. Testing Neptune graph for project_id=%s...", PROJECT_ID)
    try:
        from hermes_bedrock_agent.clients.neptune import NeptuneClient
        c = NeptuneClient()
        if c.is_configured:
            # Count new project nodes
            res = c.execute_query(
                f"MATCH (n) WHERE n.project_id = '{PROJECT_ID}' RETURN count(n) AS cnt"
            )
            cnt = res.get("results", [{}])[0].get("cnt", 0) if res.get("results") else 0
            validation["graph_query"] = cnt > 0
            validation["graph_node_count"] = cnt
            if cnt:
                logger.info("    → %d nodes for %s ✓", cnt, PROJECT_ID)
            else:
                logger.info("    → 0 nodes (empty!)")
    except Exception as e:
        logger.error("    → Graph query failed: %s", e)
    
    # Test 3: Verify old project data is intact
    # NOTE: Old project uses Japanese project_id 'サンプル20260519', not ASCII 'sample_20260519'
    logger.info("  6c. Verifying old project (サンプル20260519) is intact...")
    try:
        old_results = query_vector_store("発注情報", project_id="サンプル20260519", top_k=3)
        if old_results:
            validation["old_project_intact"] = True
            logger.info("    → Old project has %d results ✓", len(old_results))
        else:
            logger.warning("    → Old project has no results!")
    except Exception as e:
        logger.error("    → Old project check failed: %s", e)
    
    return validation


# ──────────────────────────────────────────────────────────────────────────────
# Generate sheet_name_mapping.csv
# ──────────────────────────────────────────────────────────────────────────────

def write_sheet_name_mapping(pdf_sheets: list[dict], output_path: Path):
    """Write sheet_name_mapping.csv for chunker.
    
    Required columns: sheet_index (0-based), original_sheet_name, safe_pdf_filename
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sheet_index", "original_sheet_name", "safe_pdf_filename"])
        for s in pdf_sheets:
            # sheet_index is 0-based (chunker adds 1 to get 1-based index)
            writer.writerow([s["index"] - 1, s["name"], f"sheet_{s['index']:02d}.pdf"])
    logger.info("  Sheet name mapping: %s", output_path)


# ──────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ──────────────────────────────────────────────────────────────────────────────

def main():
    start_time = time.time()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    report = {
        "project_id": PROJECT_ID,
        "project_name": PROJECT_NAME,
        "timestamp": ts,
        "source_dir": str(SOURCE_DIR),
        "workbooks": [],
        "steps": {},
        "totals": {
            "sheets_parsed": 0,
            "chunks_created": 0,
            "vector_records": 0,
            "graph_nodes": 0,
            "graph_edges": 0,
        },
        "issues_found": [],
        "issues_fixed": [],
    }
    
    logger.info("=" * 70)
    logger.info("DUAL-RAG FULL PIPELINE RERUN")
    logger.info("  Project ID: %s", PROJECT_ID)
    logger.info("  Project Name: %s", PROJECT_NAME)
    logger.info("  Source: %s", SOURCE_DIR)
    logger.info("  Timestamp: %s", ts)
    logger.info("  Neptune: %s", config.neptune_graph_id)
    logger.info("  LanceDB: %s", config.lancedb_path)
    logger.info("  VLM Model: %s", config.vlm_model_id)
    logger.info("=" * 70)
    
    # Preserve Mermaid flowchart
    if FLOWCHART_MMD.exists():
        mmd_dest = SOURCE_DIR / "flowchart.mmd"
        if not mmd_dest.exists():
            shutil.copy2(FLOWCHART_MMD, mmd_dest)
        logger.info("Mermaid flowchart preserved: %s", mmd_dest)
        report["flowchart_preserved"] = str(mmd_dest)
    
    # Process workbook 1 (flowchart workbook — 2 sheets)
    all_workbooks = [
        (WB1_XLSX, "wb1_flowchart"),
        (WB2_XLSX, "wb2_mapping"),
    ]
    
    all_vlm_dirs = []
    
    for wb_idx, (xlsx_path, wb_label) in enumerate(all_workbooks):
        if not xlsx_path.exists():
            logger.error("Workbook not found: %s", xlsx_path)
            report["issues_found"].append(f"Missing workbook: {xlsx_path}")
            continue
        
        wb_name = xlsx_path.stem
        run_dir = SOURCE_DIR / wb_label
        pdf_dir = run_dir / "pdf"
        image_dir = run_dir / "images"
        vlm_dir = run_dir / "vlm_parsed"
        
        wb_report = {"name": wb_name, "label": wb_label, "source": str(xlsx_path)}
        
        logger.info("\n" + "═" * 70)
        logger.info("WORKBOOK: %s (%s)", wb_name, wb_label)
        logger.info("═" * 70)
        
        try:
            # Step 1
            pdf_sheets = step1_excel_to_pdf(xlsx_path, pdf_dir)
            wb_report["pdf_sheets"] = len(pdf_sheets)
            report["steps"][f"{wb_label}_excel_to_pdf"] = "ok"
            
            # Write sheet name mapping
            write_sheet_name_mapping(pdf_sheets, run_dir / "sheet_name_mapping.csv")
            
            # Step 2
            all_images = step2_pdf_to_images(pdf_sheets, image_dir)
            wb_report["images_rendered"] = len(all_images)
            report["steps"][f"{wb_label}_pdf_to_images"] = "ok"
            
            # Step 3 (long step)
            parse_results = step3_vlm_parsing(all_images, vlm_dir)
            parsed_ok = sum(1 for r in parse_results if len(r.markdown) > 200)
            total_chars = sum(len(r.markdown) for r in parse_results)
            wb_report["sheets_parsed"] = parsed_ok
            wb_report["total_chars"] = total_chars
            report["totals"]["sheets_parsed"] += parsed_ok
            report["steps"][f"{wb_label}_vlm_parsing"] = "ok"
            all_vlm_dirs.append(vlm_dir)
            
            # Write VLM run summary
            vlm_summary = {
                "workbook": wb_name,
                "model": config.vlm_model_id,
                "sheets_total": len(all_images),
                "sheets_parsed": parsed_ok,
                "total_chars": total_chars,
            }
            (vlm_dir / "run_summary.json").write_text(
                json.dumps(vlm_summary, ensure_ascii=False, indent=2)
            )
            
            # Step 4 (only if VLM produced files)
            md_files = list(vlm_dir.glob("sheet_*.md"))
            if md_files:
                s3_prefix = f"サンプル20260519/{xlsx_path.parent.name}"  # S3 original path
                is_first = (wb_idx == 0)  # Only first workbook deletes existing project rows
                kb_stats = step4_build_vector_kb(vlm_dir, wb_name, s3_prefix, is_first_workbook=is_first)
                wb_report["chunks"] = kb_stats["chunks"]
                wb_report["vector_records"] = kb_stats["vector_written"]
                report["totals"]["chunks_created"] += kb_stats["chunks"]
                report["totals"]["vector_records"] += kb_stats["vector_written"]
                report["steps"][f"{wb_label}_vector_kb"] = "ok"
            else:
                logger.warning("  No VLM markdown files — skipping vector KB")
                report["steps"][f"{wb_label}_vector_kb"] = "skipped (no md files)"
            
        except Exception as e:
            logger.error("WORKBOOK FAILED: %s — %s", wb_name, e)
            wb_report["error"] = str(e)
            report["issues_found"].append(f"Workbook {wb_label} failed: {e}")
            import traceback
            traceback.print_exc()
        
        report["workbooks"].append(wb_report)
    
    # Step 5: Graph extraction (project-level)
    try:
        logger.info("\n" + "═" * 70)
        logger.info("GRAPH EXTRACTION (project-level)")
        logger.info("═" * 70)
        graph_stats = step5_build_graph(SOURCE_DIR)
        report["totals"]["graph_nodes"] = graph_stats["nodes"]
        report["totals"]["graph_edges"] = graph_stats["edges"]
        report["steps"]["graph_extraction"] = "ok"
    except Exception as e:
        logger.error("Graph extraction failed: %s", e)
        report["steps"]["graph_extraction"] = f"error: {e}"
        report["issues_found"].append(f"Graph extraction failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 6: QA Validation
    try:
        logger.info("\n" + "═" * 70)
        logger.info("QA VALIDATION")
        logger.info("═" * 70)
        validation = step6_validate_qa()
        report["validation"] = validation
        report["steps"]["qa_validation"] = "ok"
    except Exception as e:
        logger.error("QA validation failed: %s", e)
        report["steps"]["qa_validation"] = f"error: {e}"
    
    # Finalize
    elapsed = time.time() - start_time
    report["elapsed_seconds"] = round(elapsed)
    report["elapsed_human"] = f"{int(elapsed//3600)}h {int((elapsed%3600)//60)}m {int(elapsed%60)}s"
    
    # Save report
    report_path = SOURCE_DIR / f"pipeline_report_{ts}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    
    logger.info("\n" + "=" * 70)
    logger.info("PIPELINE COMPLETE in %s", report["elapsed_human"])
    logger.info("  Report: %s", report_path)
    logger.info("  Sheets parsed: %d", report["totals"]["sheets_parsed"])
    logger.info("  Chunks: %d", report["totals"]["chunks_created"])
    logger.info("  Vector records: %d", report["totals"]["vector_records"])
    logger.info("  Graph nodes: %d", report["totals"]["graph_nodes"])
    logger.info("  Graph edges: %d", report["totals"]["graph_edges"])
    if report["issues_found"]:
        logger.warning("  Issues: %d", len(report["issues_found"]))
        for issue in report["issues_found"]:
            logger.warning("    - %s", issue)
    logger.info("=" * 70)
    
    return report


if __name__ == "__main__":
    main()
