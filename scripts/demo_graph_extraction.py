#!/usr/bin/env python3
"""Demo: Test LLM-based graph extraction on parsed Markdown.

Tests the full two-pass extraction pipeline:
  Pass 1: Business Semantic Graph (workbook-level context + per-sheet)
  Pass 2: Implementation/Evidence Graph (per-chunk, field-level)

Usage:
  # Single sheet LLM extraction (~60s):
  python scripts/demo_graph_extraction.py outputs/reparse_wb2/vlm_parsed/sheet_06.md

  # Full directory (all sheets):
  python scripts/demo_graph_extraction.py outputs/reparse_wb2/vlm_parsed/

  # Keyword-only (no LLM, instant):
  python scripts/demo_graph_extraction.py --keyword-only outputs/reparse_wb2/vlm_parsed/sheet_06.md

  # Limit sheets for cost control:
  python scripts/demo_graph_extraction.py --max-sheets 3 outputs/reparse_wb2/vlm_parsed/

  # Skip implementation pass (business only):
  python scripts/demo_graph_extraction.py --business-only outputs/reparse_wb2/vlm_parsed/sheet_06.md
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from hermes_bedrock_agent.knowledge_base.schemas import Chunk
from hermes_bedrock_agent.knowledge_base.graph_extractor import (
    extract_business_graph,
    extract_implementation_graph,
    extract_entities,
    _load_workbook_summary,
)


def _build_chunks_from_path(path: Path, max_sheets: int = 99) -> list[Chunk]:
    """Build Chunk objects from markdown files."""
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = sorted(path.glob("sheet_*.md"))[:max_sheets]
        # Also include cross_sheet_summary if present
        summary_file = path / "cross_sheet_summary.md"
        if summary_file.exists():
            files = [summary_file] + files
    else:
        print(f"ERROR: {path} not found")
        sys.exit(1)

    chunks: list[Chunk] = []
    for f in files:
        content = f.read_text()
        # Detect sheet index from filename
        m = __import__("re").search(r"sheet_(\d+)", f.name)
        sheet_idx = int(m.group(1)) if m else 0

        # Detect sheet name from content
        sheet_name = f.stem
        for line in content.split("\n")[:5]:
            if line.startswith("# Sheet:") or line.startswith("# Cross-Sheet"):
                sheet_name = line.lstrip("# ").strip()
                break

        # Determine chunk type based on content
        chunk_type = "overview"
        if "cross_sheet" in f.name:
            chunk_type = "cross_sheet_summary"
        elif "マッピング" in content[:500] or "Mapping" in content[:500]:
            chunk_type = "mapping_table"
        elif "API" in content[:500] or "呼出順序" in content[:500]:
            chunk_type = "api_spec"
        elif "ルール" in content[:500] or "条件" in content[:500]:
            chunk_type = "business_rule"
        elif "フロー" in content[:500] or "flowchart" in content[:500].lower():
            chunk_type = "flowchart"

        chunk = Chunk(
            chunk_id=f"chunk_{f.stem}",
            content=content,
            chunk_type=chunk_type,
            sheet_index=sheet_idx,
            sheet_name=sheet_name,
            workbook_name="MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx",
            source_pdf_s3_path=f"s3://bucket/docs/sheet_{sheet_idx:02d}.pdf",
            source_excel_s3_path="s3://bucket/docs/workbook.xlsx",
            source_markdown_s3_path=f"s3://bucket/parsed/{f.name}",
            related_sheets=[],
            systems=[],
            apis=[],
            fields=[],
            embedding_text="",
        )
        chunks.append(chunk)

    return chunks


def _print_nodes(nodes, title):
    """Pretty-print extracted nodes."""
    print(f"\n{'='*70}")
    print(f" {title}: {len(nodes)} nodes")
    print(f"{'='*70}")

    # Group by label
    by_label: dict[str, list] = {}
    for n in nodes:
        by_label.setdefault(n.label, []).append(n)

    for label in sorted(by_label):
        print(f"\n  [{label}] ({len(by_label[label])} nodes)")
        for n in by_label[label][:10]:  # Show max 10 per type
            desc = n.properties.get("description", "")[:60]
            print(f"    • {n.name}")
            if desc:
                print(f"      ↳ {desc}")
        if len(by_label[label]) > 10:
            print(f"    ... +{len(by_label[label]) - 10} more")


def _print_edges(edges, title):
    """Pretty-print extracted edges."""
    print(f"\n{'='*70}")
    print(f" {title}: {len(edges)} edges")
    print(f"{'='*70}")

    # Group by relationship type
    by_rel: dict[str, list] = {}
    for e in edges:
        by_rel.setdefault(e.relationship, []).append(e)

    for rel in sorted(by_rel):
        print(f"\n  [{rel}] ({len(by_rel[rel])} edges)")
        for e in by_rel[rel][:8]:
            desc = e.properties.get("description", "") or e.properties.get("mapping_logic", "")
            desc = desc[:60] if desc else ""
            print(f"    {e.from_id} → {e.to_id}")
            if desc:
                print(f"      ↳ {desc}")
        if len(by_rel[rel]) > 8:
            print(f"    ... +{len(by_rel[rel]) - 8} more")


def _print_evidence_stats(nodes, edges):
    """Print evidence traceability stats."""
    print(f"\n{'─'*70}")
    print(" Evidence Traceability:")
    n_with_pdf = sum(1 for n in nodes if n.evidence_pdf_s3_path)
    e_with_chunk = sum(1 for e in edges if e.properties.get("chunk_id"))
    e_with_sheet = sum(1 for e in edges if e.properties.get("sheet_index") is not None)
    n_with_sheet = sum(1 for n in nodes if n.properties.get("sheet_name"))
    print(f"   Nodes with PDF evidence: {n_with_pdf}/{len(nodes)}")
    print(f"   Nodes with sheet_name: {n_with_sheet}/{len(nodes)}")
    print(f"   Edges with chunk_id: {e_with_chunk}/{len(edges)}")
    print(f"   Edges with sheet_index: {e_with_sheet}/{len(edges)}")
    print(f"{'─'*70}")


def main():
    parser = argparse.ArgumentParser(description="Demo: LLM graph extraction")
    parser.add_argument("path", type=Path, help="Path to .md file or directory")
    parser.add_argument("--keyword-only", action="store_true", help="Skip LLM, keyword extraction only")
    parser.add_argument("--business-only", action="store_true", help="Only run Business Semantic Graph pass")
    parser.add_argument("--impl-only", action="store_true", help="Only run Implementation Graph pass")
    parser.add_argument("--max-sheets", type=int, default=99, help="Max sheets to process")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay between LLM calls (seconds)")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    chunks = _build_chunks_from_path(args.path, args.max_sheets)
    print(f"\nLoaded {len(chunks)} chunks from {args.path}")
    for c in chunks:
        print(f"  [{c.chunk_type}] sheet_{c.sheet_index:02d}: {c.sheet_name} ({len(c.content)} chars)")

    # Show workbook summary context
    wb_summary = _load_workbook_summary(chunks)
    print(f"\nWorkbook summary context: {len(wb_summary)} chars")
    if wb_summary and wb_summary != "(No workbook summary available)":
        print(f"  (First 200 chars): {wb_summary[:200]}...")

    if args.keyword_only:
        print("\n>>> Keyword-only extraction (no LLM)")
        all_nodes, all_edges = [], []
        for chunk in chunks:
            nodes, edges = extract_entities(chunk)
            all_nodes.extend(nodes)
            all_edges.extend(edges)
        _print_nodes(all_nodes, "Keyword Extraction — Nodes")
        _print_edges(all_edges, "Keyword Extraction — Edges")
        _print_evidence_stats(all_nodes, all_edges)
        return

    # LLM extraction
    t_total = time.time()
    all_biz_nodes, all_biz_edges = [], []
    all_impl_nodes, all_impl_edges = [], []

    if not args.impl_only:
        print("\n>>> Pass 1: Business Semantic Graph (LLM)")
        t0 = time.time()
        all_biz_nodes, all_biz_edges = extract_business_graph(chunks, delay_seconds=args.delay)
        t1 = time.time()
        _print_nodes(all_biz_nodes, "Business Semantic Graph — Nodes")
        _print_edges(all_biz_edges, "Business Semantic Graph — Edges")
        _print_evidence_stats(all_biz_nodes, all_biz_edges)
        print(f"\n  ⏱ Business Graph: {t1 - t0:.1f}s")

    if not args.business_only:
        print("\n>>> Pass 2: Implementation / Evidence Graph (LLM)")
        t0 = time.time()
        all_impl_nodes, all_impl_edges = extract_implementation_graph(chunks, delay_seconds=args.delay)
        t1 = time.time()
        _print_nodes(all_impl_nodes, "Implementation Graph — Nodes")
        _print_edges(all_impl_edges, "Implementation Graph — Edges")
        _print_evidence_stats(all_impl_nodes, all_impl_edges)
        print(f"\n  ⏱ Implementation Graph: {t1 - t0:.1f}s")

    # Summary
    total_time = time.time() - t_total
    print(f"\n{'═'*70}")
    print(f" TOTAL EXTRACTION SUMMARY")
    print(f"{'═'*70}")
    print(f"  Business Graph:       {len(all_biz_nodes)} nodes, {len(all_biz_edges)} edges")
    print(f"  Implementation Graph: {len(all_impl_nodes)} nodes, {len(all_impl_edges)} edges")
    print(f"  Combined:             {len(all_biz_nodes) + len(all_impl_nodes)} nodes, {len(all_biz_edges) + len(all_impl_edges)} edges")
    print(f"  Total time:           {total_time:.1f}s")
    print(f"{'═'*70}")

    # Show sample mapping chains if found
    maps_to = [e for e in all_impl_edges if e.relationship in ("MAPS_TO", "TRANSFORMS_TO")]
    if maps_to:
        print(f"\n  Sample field mappings ({min(len(maps_to), 5)} of {len(maps_to)}):")
        for e in maps_to[:5]:
            logic = e.properties.get("mapping_logic", "")[:50]
            suffix = f" [{logic}]" if logic else ""
            print(f"    {e.from_id} --{e.relationship}--> {e.to_id}{suffix}")


if __name__ == "__main__":
    main()
