#!/usr/bin/env python3
"""Demo: Test LLM-based graph extraction on a single Markdown chunk.

This script loads one parsed Markdown file, creates a chunk from it,
and runs the LLM-based Business + Implementation graph extraction.
Use this to verify that:
  1. Parsed Markdown is used as input (not raw Excel)
  2. Claude Sonnet LLM is called for extraction (not just keyword rules)
  3. Business and Implementation graphs are clearly separated
  4. Extracted nodes and edges are meaningful
  5. Graph nodes are linked back to source chunk/sheet/PDF

Usage:
  # Test on a specific sheet markdown file:
  uv run python scripts/demo_graph_extraction.py outputs/reparse_wb2/vlm_parsed/sheet_06.md

  # Dry-run on all sheets (counts only, no LLM calls):
  uv run python scripts/demo_graph_extraction.py --keyword-only outputs/reparse_wb2/vlm_parsed/

  # Full LLM extraction on first 3 sheets (costly):
  uv run python scripts/demo_graph_extraction.py --max-sheets 3 outputs/reparse_wb2/vlm_parsed/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("demo_graph")

for n in ("boto3", "botocore", "urllib3"):
    logging.getLogger(n).setLevel(logging.WARNING)


def _divider(title: str) -> str:
    return f"\n{'─' * 10} {title} {'─' * (60 - len(title))}"


def main():
    parser = argparse.ArgumentParser(description="Demo: LLM graph extraction")
    parser.add_argument("path", type=Path, help="Path to a sheet_NN.md file or vlm_parsed/ directory")
    parser.add_argument("--keyword-only", action="store_true", help="Use keyword extraction only (no LLM, no cost)")
    parser.add_argument("--max-sheets", type=int, default=1, help="Max sheets to process with LLM (default: 1)")
    parser.add_argument("--delay", type=float, default=3.0, help="Delay between LLM calls")
    args = parser.parse_args()

    from hermes_bedrock_agent.config import config
    from hermes_bedrock_agent.knowledge_base.schemas import Chunk
    from hermes_bedrock_agent.knowledge_base.graph_extractor import (
        extract_business_graph,
        extract_implementation_graph,
        extract_entities,
        _extract_business_graph_llm,
        _extract_implementation_graph_llm,
    )
    from hermes_bedrock_agent.clients.bedrock import make_bedrock_client

    # Build chunks from markdown file(s)
    target = args.path.resolve()
    md_files: list[Path] = []

    if target.is_file() and target.suffix == ".md":
        md_files = [target]
    elif target.is_dir():
        md_files = sorted(target.glob("sheet_*.md"))[:args.max_sheets]
    else:
        print(f"Error: {target} is not a .md file or directory")
        sys.exit(1)

    if not md_files:
        print(f"No sheet_*.md files found in {target}")
        sys.exit(1)

    print(_divider("LLM Graph Extraction Demo"))
    print(f"  Source: {target}")
    print(f"  Files: {len(md_files)}")
    print(f"  Mode: {'keyword-only' if args.keyword_only else 'LLM (Claude Sonnet)'}")
    print(f"  Model: {config.vlm_model_id}")

    # Create chunks from markdown files
    chunks: list[Chunk] = []
    import hashlib
    import re

    for md_path in md_files:
        match = re.search(r"sheet_(\d+)", md_path.stem)
        sheet_idx = int(match.group(1)) if match else 0
        content = md_path.read_text(encoding="utf-8")
        if not content.strip():
            continue

        content_hash = hashlib.sha256(content.encode()).hexdigest()[:12]
        chunk = Chunk(
            chunk_id=f"sheet{sheet_idx:02d}_full_{content_hash}",
            content=content[:6000],  # Limit for LLM
            chunk_type="mapping_table",
            sheet_index=sheet_idx,
            sheet_name=f"sheet_{sheet_idx:02d}",
            workbook_name="demo_workbook",
            source_pdf_s3_path=f"s3://{config.s3_bucket}/outputs/reparse_wb2/pdf/sheet_{sheet_idx:02d}.pdf",
            source_excel_s3_path=f"s3://{config.s3_bucket}/outputs/reparse_wb2/source.xlsx",
            source_markdown_s3_path=f"s3://{config.s3_bucket}/outputs/reparse_wb2/vlm_parsed/sheet_{sheet_idx:02d}.md",
            related_sheets=[],
            systems=[],
            apis=[],
            fields=[],
            embedding_text=content[:200],
        )
        chunks.append(chunk)
        print(f"\n  Loaded: {md_path.name} ({len(content)} chars, sheet {sheet_idx})")

    if not chunks:
        print("No non-empty chunks created")
        sys.exit(1)

    if args.keyword_only:
        # Keyword-only extraction
        print(_divider("Keyword Extraction (no LLM)"))
        all_nodes = []
        all_edges = []
        for chunk in chunks:
            nodes, edges = extract_entities(chunk)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

        print(f"  Nodes: {len(all_nodes)}")
        for n in all_nodes[:15]:
            print(f"    [{n.label}] {n.name} (id={n.node_id[:40]})")
        print(f"  Edges: {len(all_edges)}")
        for e in all_edges[:15]:
            print(f"    {e.from_id[:30]} --{e.relationship}--> {e.to_id[:30]}")
        return

    # LLM extraction
    client = make_bedrock_client(config.aws_region)
    model_id = config.vlm_model_id

    print(_divider("① Business Semantic Graph (LLM)"))
    t0 = time.time()
    biz_nodes, biz_edges = extract_business_graph(chunks, cfg=config, delay_seconds=args.delay)
    t1 = time.time()
    print(f"\n  Extracted in {t1-t0:.1f}s")
    print(f"  Nodes: {len(biz_nodes)}")
    for n in biz_nodes[:20]:
        desc = n.properties.get("description", "")[:50]
        print(f"    [{n.label}] {n.name}{f' — {desc}' if desc else ''}")
    print(f"  Edges: {len(biz_edges)}")
    for e in biz_edges[:20]:
        desc = e.properties.get("description", "")[:40]
        print(f"    {e.from_id[:30]} --{e.relationship}--> {e.to_id[:30]}{f' ({desc})' if desc else ''}")

    time.sleep(args.delay)

    print(_divider("② Implementation / Evidence Graph (LLM)"))
    t2 = time.time()
    impl_nodes, impl_edges = extract_implementation_graph(chunks, cfg=config, delay_seconds=args.delay)
    t3 = time.time()
    print(f"\n  Extracted in {t3-t2:.1f}s")
    print(f"  Nodes: {len(impl_nodes)}")
    for n in impl_nodes[:20]:
        props_str = ""
        if n.properties.get("source_field"):
            props_str = f" [src={n.properties['source_field']}]"
        elif n.properties.get("transformation"):
            props_str = f" [transform={n.properties['transformation'][:30]}]"
        print(f"    [{n.label}] {n.name}{props_str}")
    print(f"  Edges: {len(impl_edges)}")
    for e in impl_edges[:20]:
        print(f"    {e.from_id[:30]} --{e.relationship}--> {e.to_id[:30]}")

    # Evidence traceability check
    print(_divider("③ Evidence Traceability"))
    print("  Checking that nodes link back to source...")
    traced = 0
    for n in biz_nodes + impl_nodes:
        if n.evidence_pdf_s3_path:
            traced += 1
    print(f"  {traced}/{len(biz_nodes) + len(impl_nodes)} nodes have evidence_pdf_s3_path ✓")

    chunk_linked = 0
    for e in biz_edges + impl_edges:
        if e.properties.get("chunk_id"):
            chunk_linked += 1
    print(f"  {chunk_linked}/{len(biz_edges) + len(impl_edges)} edges have chunk_id ✓")

    print(_divider("Summary"))
    print(f"  Business Graph: {len(biz_nodes)} nodes, {len(biz_edges)} edges")
    print(f"  Implementation Graph: {len(impl_nodes)} nodes, {len(impl_edges)} edges")
    print(f"  Total LLM time: {(t1-t0) + (t3-t2):.1f}s")
    print(f"  Evidence traceability: {traced}/{len(biz_nodes)+len(impl_nodes)} nodes linked to PDF")
    print()


if __name__ == "__main__":
    main()
