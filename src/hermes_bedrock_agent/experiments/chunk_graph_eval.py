"""Chunk x Graph Prompt Experiment Framework.

Generates and preserves separate local outputs for each combination of:
  source_project x chunking_strategy x graph_extraction_prompt_version

Usage:
    python -m hermes_bedrock_agent.experiments.chunk_graph_eval \
        --output-dir outputs/experiments/chunk_graph_eval \
        --dry-run-graph
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Project root ─────────────────────────────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# ── Source project definitions ───────────────────────────────────────────────

@dataclass
class SourceProject:
    key: str
    display_name: str
    base_path: Path
    workbooks: list[dict] = field(default_factory=list)


SOURCE_PROJECTS: dict[str, SourceProject] = {
    "saimu_bugyo_cloud": SourceProject(
        key="saimu_bugyo_cloud",
        display_name="14_債務奉行クラウド",
        base_path=_PROJECT_ROOT / "outputs" / "14_債務奉行クラウド" / "run_20260602_072107",
    ),
    "sample_20260519": SourceProject(
        key="sample_20260519",
        display_name="サンプル20260519",
        base_path=_PROJECT_ROOT / "outputs" / "サンプル20260519" / "run_20260602_074637",
    ),
}

# ── Chunking strategy configs ────────────────────────────────────────────────

CHUNKING_CONFIGS = {
    "fixed_length": {
        "mode": "fixed",
        "chunk_max_chars": 3200,
        "chunk_min_chars": 200,
        "split_by_heading_first": True,
        "preserve_table_block": True,
        "note": "Character-based fixed chunking (approx 800 tokens at 4 chars/token)",
    },
    "semantic": {
        "mode": "semantic",
        "chunk_max_chars": 4000,
        "chunk_min_chars": 200,
        "chunk_semantic_group_target": 2000,
        "note": "Semantic block-aware chunking respecting section/table boundaries",
    },
}

# ── Source inventory ─────────────────────────────────────────────────────────


def _scan_source_project(project: SourceProject) -> list[dict]:
    """Scan parsed markdown files for a source project and build inventory."""
    inventory: list[dict] = []
    base = project.base_path

    if not base.exists():
        logger.warning("Source path does not exist: %s", base)
        return inventory

    for workbook_dir in sorted(base.iterdir()):
        if not workbook_dir.is_dir():
            continue
        workbook_name = workbook_dir.name

        if workbook_name in ("graph_output", "downloads"):
            continue

        # VLM parsed markdown
        vlm_dir = workbook_dir / "vlm_parsed"
        if vlm_dir.exists():
            for md_file in sorted(vlm_dir.glob("sheet_*.md")):
                m = re.match(r"sheet_(\d+)\.md$", md_file.name)
                if not m:
                    continue
                sheet_index = int(m.group(1))
                inventory.append({
                    "source_project_key": project.key,
                    "source_project_display": project.display_name,
                    "source_file": str(md_file.relative_to(_PROJECT_ROOT)),
                    "parsed_markdown_path": str(md_file),
                    "source_type": "excel",
                    "parser_type": "vlm",
                    "document_role": "sheet",
                    "workbook_name": workbook_name,
                    "sheet_name": f"sheet_{sheet_index:02d}",
                    "sheet_index": sheet_index,
                    "page_index": 0,
                    "evidence_paths": [],
                })

    # CSV parsed (saimu_bugyo_cloud)
    csv_dir = base / "csv_parsed"
    if csv_dir.exists():
        for md_file in sorted(csv_dir.glob("*.md")):
            inventory.append({
                "source_project_key": project.key,
                "source_project_display": project.display_name,
                "source_file": str(md_file.relative_to(_PROJECT_ROOT)),
                "parsed_markdown_path": str(md_file),
                "source_type": "csv",
                "parser_type": "csv",
                "document_role": "data_file",
                "workbook_name": "csv_parsed",
                "sheet_name": md_file.stem,
                "sheet_index": 0,
                "page_index": 0,
                "evidence_paths": [],
            })

    # Mermaid (sample_20260519)
    mermaid_dir = base / "mermaid" / "flowchart"
    if mermaid_dir.exists():
        for md_file in sorted(mermaid_dir.glob("*.md")):
            inventory.append({
                "source_project_key": project.key,
                "source_project_display": project.display_name,
                "source_file": str(md_file.relative_to(_PROJECT_ROOT)),
                "parsed_markdown_path": str(md_file),
                "source_type": "mermaid",
                "parser_type": "mermaid",
                "document_role": "flowchart",
                "workbook_name": "mermaid",
                "sheet_name": md_file.stem,
                "sheet_index": 0,
                "page_index": 0,
                "evidence_paths": [],
            })

    logger.info(
        "Scanned %s: %d source files",
        project.display_name,
        len(inventory),
    )
    return inventory


def build_source_inventories(output_dir: Path) -> dict[str, list[dict]]:
    """Build and save source inventories for all projects."""
    inv_dir = output_dir / "source_inventory"
    inv_dir.mkdir(parents=True, exist_ok=True)

    inventories: dict[str, list[dict]] = {}
    for key, project in SOURCE_PROJECTS.items():
        inv = _scan_source_project(project)
        inventories[key] = inv
        inv_path = inv_dir / f"{key}_inventory.json"
        inv_path.write_text(
            json.dumps(inv, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved inventory: %s (%d files)", inv_path.name, len(inv))

    return inventories


# ── Chunking phase ───────────────────────────────────────────────────────────


def _split_into_chunks(markdown: str, max_size: int, min_size: int, mode: str = "fixed", target: int = 0) -> list[str]:
    """Import and call the existing chunker."""
    from ..knowledge_base.chunker import _split_into_chunks as _chunker
    return _chunker(markdown, max_size, min_size, mode=mode, target=target)


def run_chunking(
    inventory: list[dict],
    chunking_strategy: str,
    experiment_project_id: str,
    chunk_run_id: str,
    graph_run_id: str,
    graph_prompt_version: str,
    output_dir: Path,
) -> list[dict]:
    """Run chunking on all files in inventory, write chunks.jsonl and stats."""
    cfg = CHUNKING_CONFIGS[chunking_strategy]
    mode = cfg["mode"]
    max_chars = cfg["chunk_max_chars"]
    min_chars = cfg["chunk_min_chars"]
    target = cfg.get("chunk_semantic_group_target", 0)

    chunks_dir = output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    all_chunks: list[dict] = []
    created_at = datetime.now(timezone.utc).isoformat()

    for file_rec in inventory:
        md_path = Path(file_rec["parsed_markdown_path"])
        if not md_path.exists():
            logger.warning("File not found: %s", md_path)
            continue

        markdown = md_path.read_text(encoding="utf-8")
        if not markdown.strip():
            continue

        text_chunks = _split_into_chunks(markdown, max_chars, min_chars, mode=mode, target=target)

        for i, chunk_text in enumerate(text_chunks):
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:12]
            section_title = ""
            m = re.search(r"^##\s+(.+)", chunk_text, re.MULTILINE)
            if m:
                section_title = m.group(1).strip()

            has_table = "|" in chunk_text and re.search(r"^\|.+\|", chunk_text, re.MULTILINE) is not None
            has_mermaid = "```mermaid" in chunk_text or "flowchart" in chunk_text.lower()

            chunk_id = f"{chunk_run_id}__chunk{i:04d}_{content_hash}"
            chunk_rec = {
                "experiment_project_id": experiment_project_id,
                "source_project_key": file_rec["source_project_key"],
                "chunk_run_id": chunk_run_id,
                "graph_run_id": graph_run_id,
                "source_file": file_rec["source_file"],
                "source_type": file_rec["source_type"],
                "parser_type": file_rec["parser_type"],
                "parsed_markdown_path": file_rec["parsed_markdown_path"],
                "chunking_strategy": chunking_strategy,
                "chunk_id": chunk_id,
                "chunk_index": i,
                "section_title": section_title,
                "document_role": file_rec["document_role"],
                "workbook_name": file_rec["workbook_name"],
                "sheet_name": file_rec["sheet_name"],
                "sheet_index": file_rec["sheet_index"],
                "page_index": file_rec["page_index"],
                "evidence_paths": file_rec["evidence_paths"],
                "graph_prompt_version": graph_prompt_version,
                "created_at": created_at,
                "content": chunk_text,
                "content_length": len(chunk_text),
                "content_hash": content_hash,
                "has_table": has_table,
                "has_mermaid": has_mermaid,
            }
            all_chunks.append(chunk_rec)

    # Write chunks.jsonl
    chunks_path = chunks_dir / "chunks.jsonl"
    with open(chunks_path, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    # Compute stats
    lengths = [c["content_length"] for c in all_chunks]
    stats = {
        "experiment_project_id": experiment_project_id,
        "chunking_strategy": chunking_strategy,
        "total_chunks": len(all_chunks),
        "total_source_files": len(inventory),
        "avg_chunk_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "max_chunk_length": max(lengths) if lengths else 0,
        "min_chunk_length": min(lengths) if lengths else 0,
        "median_chunk_length": sorted(lengths)[len(lengths) // 2] if lengths else 0,
        "chunks_with_tables": sum(1 for c in all_chunks if c["has_table"]),
        "chunks_with_mermaid": sum(1 for c in all_chunks if c["has_mermaid"]),
        "chunks_with_empty_metadata": sum(
            1 for c in all_chunks
            if not c["section_title"] and not c["workbook_name"]
        ),
        "config": cfg,
    }

    stats_path = chunks_dir / "chunk_stats.json"
    stats_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Write chunking config
    config_path = output_dir / "chunking_config.json"
    config_path.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info(
        "Chunking [%s]: %d chunks from %d files (avg len: %.0f)",
        chunking_strategy,
        len(all_chunks),
        len(inventory),
        stats["avg_chunk_length"],
    )
    return all_chunks


# ── Graph extraction phase ───────────────────────────────────────────────────


def _get_prompt_snapshot() -> tuple[str, str]:
    """Get the v4.3 prompt text and its SHA256 hash."""
    from ..graph_pipeline.extractor import (
        _SYSTEM_PROMPT,
        _V4_EDGE_EXTRACTION_PROMPT,
        _V4_NODE_EXTRACTION_PROMPT,
    )

    full_prompt = (
        "=== SYSTEM PROMPT ===\n"
        + _SYSTEM_PROMPT
        + "\n\n=== NODE EXTRACTION PROMPT (v4.3) ===\n"
        + _V4_NODE_EXTRACTION_PROMPT
        + "\n\n=== EDGE EXTRACTION PROMPT (v4.3) ===\n"
        + _V4_EDGE_EXTRACTION_PROMPT
    )
    sha256 = hashlib.sha256(full_prompt.encode()).hexdigest()
    return full_prompt, sha256


def _build_project_sheet_summary(inventory: list[dict]) -> str:
    """Build a summary of all sheets in a project for cross-sheet context."""
    lines = []
    wb_sheets: dict[str, list[str]] = {}
    for rec in inventory:
        wb = rec["workbook_name"]
        sheet = rec["sheet_name"]
        if wb not in wb_sheets:
            wb_sheets[wb] = []
        wb_sheets[wb].append(sheet)

    for wb, sheets in wb_sheets.items():
        lines.append(f"Workbook: {wb}")
        for s in sheets:
            lines.append(f"  - {s}")
    return "\n".join(lines)


def run_graph_extraction(
    chunks: list[dict],
    inventory: list[dict],
    experiment_project_id: str,
    graph_run_id: str,
    graph_prompt_version: str,
    source_project_key: str,
    output_dir: Path,
    delay_seconds: float = 3.0,
    model_id: Optional[str] = None,
    region: Optional[str] = None,
) -> tuple[list[dict], list[dict]]:
    """Run graph extraction on chunks using v4.3 prompts.

    Groups chunks by source file, calls LLM for each file's combined content.
    """
    from ..clients.bedrock import converse_text, make_bedrock_client
    from ..graph_pipeline.extractor import (
        _SYSTEM_PROMPT,
        _V4_EDGE_EXTRACTION_PROMPT,
        _V4_NODE_EXTRACTION_PROMPT,
        _parse_edge_response,
        _parse_node_response,
    )

    region = region or os.getenv("AWS_REGION", "ap-northeast-1")
    model_id = model_id or os.getenv(
        "BEDROCK_EXTRACTION_MODEL_ID",
        os.getenv("BEDROCK_MODEL_ID", "jp.anthropic.claude-sonnet-4-6"),
    )

    graph_dir = output_dir / "graph_output"
    graph_dir.mkdir(parents=True, exist_ok=True)

    # Save prompt config and snapshot
    prompt_text, prompt_sha = _get_prompt_snapshot()
    prompt_config = {
        "file_path": "src/hermes_bedrock_agent/graph_pipeline/extractor.py",
        "version": "v4.3",
        "sha256": prompt_sha,
        "snapshot_path": "graph_prompt_snapshot.md",
        "model_id": model_id,
        "region": region,
        "max_tokens": 16000,
    }
    (output_dir / "graph_prompt_config.json").write_text(
        json.dumps(prompt_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "graph_prompt_snapshot.md").write_text(prompt_text, encoding="utf-8")

    project_sheet_summary = _build_project_sheet_summary(inventory)
    project_display = SOURCE_PROJECTS[source_project_key].display_name

    # Group chunks by source file for efficient extraction
    file_chunks: dict[str, list[dict]] = {}
    for chunk in chunks:
        key = chunk["parsed_markdown_path"]
        if key not in file_chunks:
            file_chunks[key] = []
        file_chunks[key].append(chunk)

    client = make_bedrock_client(region)
    all_nodes: list[dict] = []
    all_edges: list[dict] = []
    extraction_log: list[dict] = []
    total_files = len(file_chunks)

    logger.info(
        "Starting graph extraction: %d files, model=%s",
        total_files,
        model_id,
    )

    for file_idx, (file_path, file_chunk_list) in enumerate(file_chunks.items()):
        representative = file_chunk_list[0]
        workbook_name = representative["workbook_name"]
        sheet_name = representative["sheet_name"]
        sheet_type = representative.get("source_type", "excel")

        # Combine all chunks from this file into one content block
        combined_content = "\n\n---\n\n".join(c["content"] for c in file_chunk_list)
        if len(combined_content) > 25000:
            combined_content = combined_content[:25000] + "\n\n[...content truncated for extraction...]"

        log_entry = {
            "file_path": file_path,
            "file_index": file_idx,
            "workbook_name": workbook_name,
            "sheet_name": sheet_name,
            "chunks_in_file": len(file_chunk_list),
            "content_length": len(combined_content),
        }

        # Pass 1: Node extraction
        node_prompt = _V4_NODE_EXTRACTION_PROMPT.format(
            project_name=project_display,
            project_id=source_project_key,
            workbook_name=workbook_name,
            sheet_name=sheet_name,
            sheet_type=sheet_type,
            source_file=file_path,
            project_sheet_summary=project_sheet_summary,
            content=combined_content,
        )
        full_prompt = f"<system>\n{_SYSTEM_PROMPT}\n</system>\n\n{node_prompt}"

        nodes: list[dict] = []
        try:
            response, usage = converse_text(
                client=client,
                model_id=model_id,
                prompt=full_prompt,
                max_tokens=16000,
            )
            nodes = _parse_node_response(response)
            log_entry["node_count"] = len(nodes)
            log_entry["node_usage"] = usage
            logger.info(
                "[%d/%d] %s/%s: %d nodes extracted",
                file_idx + 1, total_files, workbook_name, sheet_name, len(nodes),
            )
        except Exception as exc:
            log_entry["node_error"] = str(exc)
            logger.error(
                "[%d/%d] Node extraction failed for %s: %s",
                file_idx + 1, total_files, sheet_name, exc,
            )

        time.sleep(delay_seconds)

        # Pass 2: Edge extraction
        edges: list[dict] = []
        if nodes:
            node_id_list = "\n".join(
                f"- {n.get('id', '?')} ({n.get('entity_type', '?')}): {n.get('name', '')}"
                for n in nodes[:80]
            )
            edge_prompt = _V4_EDGE_EXTRACTION_PROMPT.format(
                project_name=project_display,
                project_id=source_project_key,
                workbook_name=workbook_name,
                sheet_name=sheet_name,
                sheet_type=sheet_type,
                source_file=file_path,
                node_id_list=node_id_list,
                content=combined_content,
            )
            full_prompt2 = f"<system>\n{_SYSTEM_PROMPT}\n</system>\n\n{edge_prompt}"

            try:
                response2, usage2 = converse_text(
                    client=client,
                    model_id=model_id,
                    prompt=full_prompt2,
                    max_tokens=16000,
                )
                edges = _parse_edge_response(response2)
                log_entry["edge_count"] = len(edges)
                log_entry["edge_usage"] = usage2
                logger.info(
                    "[%d/%d] %s/%s: %d edges extracted",
                    file_idx + 1, total_files, workbook_name, sheet_name, len(edges),
                )
            except Exception as exc:
                log_entry["edge_error"] = str(exc)
                logger.error(
                    "[%d/%d] Edge extraction failed for %s: %s",
                    file_idx + 1, total_files, sheet_name, exc,
                )

            time.sleep(delay_seconds)

        # Attach experiment metadata to nodes
        chunk_ids = [c["chunk_id"] for c in file_chunk_list]
        for node in nodes:
            node["experiment_project_id"] = experiment_project_id
            node["source_project_key"] = source_project_key
            node["chunk_run_id"] = file_chunk_list[0]["chunk_run_id"]
            node["graph_run_id"] = graph_run_id
            node["graph_prompt_version"] = graph_prompt_version
            node["chunking_strategy"] = file_chunk_list[0]["chunking_strategy"]
            node["source_chunk_ids"] = chunk_ids
            node["source_file"] = file_path
            node["parsed_markdown_path"] = file_path

        for edge in edges:
            edge["experiment_project_id"] = experiment_project_id
            edge["source_project_key"] = source_project_key
            edge["chunk_run_id"] = file_chunk_list[0]["chunk_run_id"]
            edge["graph_run_id"] = graph_run_id
            edge["graph_prompt_version"] = graph_prompt_version
            edge["chunking_strategy"] = file_chunk_list[0]["chunking_strategy"]
            edge["source_chunk_ids"] = chunk_ids
            edge["source_file"] = file_path
            edge["parsed_markdown_path"] = file_path

        all_nodes.extend(nodes)
        all_edges.extend(edges)
        extraction_log.append(log_entry)

    # Write outputs
    nodes_path = graph_dir / "nodes.jsonl"
    with open(nodes_path, "w", encoding="utf-8") as f:
        for node in all_nodes:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    edges_path = graph_dir / "edges.jsonl"
    with open(edges_path, "w", encoding="utf-8") as f:
        for edge in all_edges:
            f.write(json.dumps(edge, ensure_ascii=False) + "\n")

    # Graph stats
    entity_types: dict[str, int] = {}
    for n in all_nodes:
        et = n.get("entity_type", "unknown")
        entity_types[et] = entity_types.get(et, 0) + 1

    edge_types: dict[str, int] = {}
    for e in all_edges:
        et = e.get("type", "unknown")
        edge_types[et] = edge_types.get(et, 0) + 1

    graph_stats = {
        "experiment_project_id": experiment_project_id,
        "graph_prompt_version": graph_prompt_version,
        "model_id": model_id,
        "total_nodes": len(all_nodes),
        "total_edges": len(all_edges),
        "files_processed": total_files,
        "files_with_errors": sum(
            1 for log in extraction_log
            if "node_error" in log or "edge_error" in log
        ),
        "entity_type_distribution": entity_types,
        "edge_type_distribution": edge_types,
        "avg_nodes_per_file": round(len(all_nodes) / total_files, 1) if total_files else 0,
        "avg_edges_per_file": round(len(all_edges) / total_files, 1) if total_files else 0,
    }
    (graph_dir / "graph_stats.json").write_text(
        json.dumps(graph_stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Dry run report
    dry_run_report = {
        "mode": "dry_run",
        "neptune_import": False,
        "lancedb_write": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "extraction_log": extraction_log,
        "summary": {
            "total_llm_calls": sum(
                (1 if "node_count" in log else 0) + (1 if "edge_count" in log else 0)
                for log in extraction_log
            ),
            "total_nodes_extracted": len(all_nodes),
            "total_edges_extracted": len(all_edges),
            "errors": sum(
                (1 if "node_error" in log else 0) + (1 if "edge_error" in log else 0)
                for log in extraction_log
            ),
        },
    }
    (graph_dir / "dry_run_report.json").write_text(
        json.dumps(dry_run_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # QA eval ready placeholder
    qa_dir = output_dir / "qa_eval_ready"
    qa_dir.mkdir(parents=True, exist_ok=True)
    (qa_dir / "retrieval_config.json").write_text(
        json.dumps({
            "experiment_project_id": experiment_project_id,
            "chunks_path": str(output_dir / "chunks" / "chunks.jsonl"),
            "nodes_path": str(nodes_path),
            "edges_path": str(edges_path),
            "status": "ready_for_evaluation",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (qa_dir / "notes.md").write_text(
        f"# QA Evaluation Ready\n\n"
        f"Experiment: `{experiment_project_id}`\n\n"
        f"This directory is a placeholder for future QA evaluation.\n"
        f"Chunks and graph outputs are ready for retrieval testing.\n",
        encoding="utf-8",
    )

    logger.info(
        "Graph extraction complete: %d nodes, %d edges from %d files",
        len(all_nodes), len(all_edges), total_files,
    )
    return all_nodes, all_edges


# ── Run report ───────────────────────────────────────────────────────────────


def _write_run_report(
    output_dir: Path,
    experiment_project_id: str,
    source_project_key: str,
    chunking_strategy: str,
    graph_prompt_version: str,
    chunk_stats: dict,
    graph_stats: dict,
) -> None:
    """Write a markdown run report summarizing the experiment."""
    report = f"""# Experiment Run Report

## Experiment ID
`{experiment_project_id}`

## Configuration
- Source Project: `{source_project_key}` ({SOURCE_PROJECTS[source_project_key].display_name})
- Chunking Strategy: `{chunking_strategy}`
- Graph Prompt Version: `{graph_prompt_version}`

## Chunking Results
- Total chunks: {chunk_stats.get('total_chunks', 0)}
- Avg chunk length: {chunk_stats.get('avg_chunk_length', 0):.0f} chars
- Max chunk length: {chunk_stats.get('max_chunk_length', 0)} chars
- Min chunk length: {chunk_stats.get('min_chunk_length', 0)} chars
- Chunks with tables: {chunk_stats.get('chunks_with_tables', 0)}
- Chunks with mermaid: {chunk_stats.get('chunks_with_mermaid', 0)}

## Graph Extraction Results
- Total nodes: {graph_stats.get('total_nodes', 0)}
- Total edges: {graph_stats.get('total_edges', 0)}
- Files processed: {graph_stats.get('files_processed', 0)}
- Files with errors: {graph_stats.get('files_with_errors', 0)}
- Avg nodes/file: {graph_stats.get('avg_nodes_per_file', 0):.1f}
- Avg edges/file: {graph_stats.get('avg_edges_per_file', 0):.1f}

## Entity Type Distribution
"""
    for et, count in sorted(
        graph_stats.get("entity_type_distribution", {}).items(),
        key=lambda x: -x[1],
    ):
        report += f"- {et}: {count}\n"

    report += "\n## Edge Type Distribution\n"
    for et, count in sorted(
        graph_stats.get("edge_type_distribution", {}).items(),
        key=lambda x: -x[1],
    )[:20]:
        report += f"- {et}: {count}\n"

    report += f"\n## Timestamp\n{datetime.now(timezone.utc).isoformat()}\n"

    (output_dir / "run_report.md").write_text(report, encoding="utf-8")


# ── Comparison phase ─────────────────────────────────────────────────────────


def generate_comparison(output_dir: Path, experiments: list[dict]) -> None:
    """Generate comparison CSVs and summary across all experiments."""
    comp_dir = output_dir / "comparison"
    comp_dir.mkdir(parents=True, exist_ok=True)

    # Chunking comparison
    chunk_rows: list[dict] = []
    for exp in experiments:
        run_dir = output_dir / "runs" / exp["experiment_project_id"]
        stats_path = run_dir / "chunks" / "chunk_stats.json"
        if stats_path.exists():
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            chunk_rows.append({
                "experiment_project_id": exp["experiment_project_id"],
                "source_project_key": exp["source_project_key"],
                "chunking_strategy": exp["chunking_strategy"],
                "total_chunks": stats.get("total_chunks", 0),
                "avg_chunk_length": stats.get("avg_chunk_length", 0),
                "max_chunk_length": stats.get("max_chunk_length", 0),
                "min_chunk_length": stats.get("min_chunk_length", 0),
                "median_chunk_length": stats.get("median_chunk_length", 0),
                "chunks_with_tables": stats.get("chunks_with_tables", 0),
                "chunks_with_mermaid": stats.get("chunks_with_mermaid", 0),
            })

    if chunk_rows:
        chunk_csv = comp_dir / "chunking_comparison.csv"
        with open(chunk_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=chunk_rows[0].keys())
            writer.writeheader()
            writer.writerows(chunk_rows)

    # Graph extraction comparison
    graph_rows: list[dict] = []
    for exp in experiments:
        run_dir = output_dir / "runs" / exp["experiment_project_id"]
        stats_path = run_dir / "graph_output" / "graph_stats.json"
        if stats_path.exists():
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            graph_rows.append({
                "experiment_project_id": exp["experiment_project_id"],
                "source_project_key": exp["source_project_key"],
                "chunking_strategy": exp["chunking_strategy"],
                "graph_prompt_version": exp["graph_prompt_version"],
                "total_nodes": stats.get("total_nodes", 0),
                "total_edges": stats.get("total_edges", 0),
                "files_processed": stats.get("files_processed", 0),
                "files_with_errors": stats.get("files_with_errors", 0),
                "avg_nodes_per_file": stats.get("avg_nodes_per_file", 0),
                "avg_edges_per_file": stats.get("avg_edges_per_file", 0),
                "model_id": stats.get("model_id", ""),
            })

    if graph_rows:
        graph_csv = comp_dir / "graph_extraction_comparison.csv"
        with open(graph_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=graph_rows[0].keys())
            writer.writeheader()
            writer.writerows(graph_rows)

    # Experiment summary markdown
    summary = "# Experiment Summary\n\n"
    summary += f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n"
    summary += "## Experiment Matrix\n\n"
    summary += "| Experiment ID | Source Project | Chunking | Graph Prompt | Status |\n"
    summary += "|---|---|---|---|---|\n"
    for exp in experiments:
        summary += (
            f"| `{exp['experiment_project_id']}` "
            f"| {exp['source_project_key']} "
            f"| {exp['chunking_strategy']} "
            f"| {exp['graph_prompt_version']} "
            f"| {exp.get('status', 'unknown')} |\n"
        )

    summary += "\n## Chunking Comparison\n\n"
    if chunk_rows:
        summary += "| Source | Strategy | Chunks | Avg Len | Max Len | Tables | Mermaid |\n"
        summary += "|---|---|---|---|---|---|---|\n"
        for r in chunk_rows:
            summary += (
                f"| {r['source_project_key']} "
                f"| {r['chunking_strategy']} "
                f"| {r['total_chunks']} "
                f"| {r['avg_chunk_length']:.0f} "
                f"| {r['max_chunk_length']} "
                f"| {r['chunks_with_tables']} "
                f"| {r['chunks_with_mermaid']} |\n"
            )

    summary += "\n## Graph Extraction Comparison\n\n"
    if graph_rows:
        summary += "| Source | Strategy | Prompt | Nodes | Edges | Files | Errors |\n"
        summary += "|---|---|---|---|---|---|---|\n"
        for r in graph_rows:
            summary += (
                f"| {r['source_project_key']} "
                f"| {r['chunking_strategy']} "
                f"| {r['graph_prompt_version']} "
                f"| {r['total_nodes']} "
                f"| {r['total_edges']} "
                f"| {r['files_processed']} "
                f"| {r['files_with_errors']} |\n"
            )

    summary += "\n## Graph Prompt Versions Discovered\n\n"
    summary += "- **v4.3** (CURRENT PRODUCTION) — Used in this experiment\n"
    summary += "- **v3** (LEGACY) — Discovered but skipped (different pipeline architecture)\n"
    summary += "- **v2_business** (ARCHIVED) — Discovered but skipped (different schema)\n"
    summary += "- **v2_implementation** (ARCHIVED) — Discovered but skipped (different schema)\n"

    (comp_dir / "experiment_summary.md").write_text(summary, encoding="utf-8")
    logger.info("Comparison reports written to %s", comp_dir)


# ── Main orchestrator ────────────────────────────────────────────────────────


def main(
    output_dir: Optional[Path] = None,
    source_projects: Optional[list[str]] = None,
    chunking_strategies: Optional[list[str]] = None,
    graph_prompt_versions: Optional[list[str]] = None,
    dry_run_graph: bool = True,
    delay_seconds: float = 3.0,
    model_id: Optional[str] = None,
    region: Optional[str] = None,
    skip_graph: bool = False,
) -> None:
    """Run the full experiment pipeline."""
    output_dir = output_dir or (_PROJECT_ROOT / "outputs" / "experiments" / "chunk_graph_eval")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve parameters
    project_keys = source_projects or list(SOURCE_PROJECTS.keys())
    strategies = chunking_strategies or list(CHUNKING_CONFIGS.keys())
    prompt_versions = graph_prompt_versions or ["v43"]

    logger.info("=" * 60)
    logger.info("CHUNK x GRAPH PROMPT EXPERIMENT FRAMEWORK")
    logger.info("=" * 60)
    logger.info("Output dir: %s", output_dir)
    logger.info("Projects: %s", project_keys)
    logger.info("Chunking strategies: %s", strategies)
    logger.info("Graph prompt versions: %s", prompt_versions)
    logger.info("Dry run graph: %s", dry_run_graph)
    logger.info("Skip graph extraction: %s", skip_graph)
    logger.info("=" * 60)

    # Phase 1: Source inventory
    logger.info("Phase 1: Building source inventories...")
    inventories = build_source_inventories(output_dir)

    # Phase 2 & 3: Run experiments
    experiments: list[dict] = []
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    for project_key in project_keys:
        if project_key not in SOURCE_PROJECTS:
            # Try to match by display name
            matched = None
            for k, p in SOURCE_PROJECTS.items():
                if p.display_name == project_key:
                    matched = k
                    break
            if matched:
                project_key = matched
            else:
                logger.error("Unknown source project: %s", project_key)
                continue

        inventory = inventories.get(project_key, [])
        if not inventory:
            logger.warning("No files found for project: %s", project_key)
            continue

        for strategy in strategies:
            if strategy not in CHUNKING_CONFIGS:
                # Normalize: "fixed" -> "fixed_length"
                if strategy == "fixed":
                    strategy = "fixed_length"
                elif strategy not in CHUNKING_CONFIGS:
                    logger.error("Unknown chunking strategy: %s", strategy)
                    continue

            for prompt_ver in prompt_versions:
                experiment_project_id = f"exp_{project_key}__chunk_{strategy}__graph_{prompt_ver}"
                chunk_run_id = f"{project_key}__chunk_{strategy}"
                graph_run_id = f"{project_key}__chunk_{strategy}__graph_{prompt_ver}"

                logger.info("-" * 50)
                logger.info("Experiment: %s", experiment_project_id)
                logger.info("-" * 50)

                exp_dir = runs_dir / experiment_project_id
                exp_dir.mkdir(parents=True, exist_ok=True)

                exp_record = {
                    "experiment_project_id": experiment_project_id,
                    "source_project_key": project_key,
                    "source_project_display": SOURCE_PROJECTS[project_key].display_name,
                    "chunking_strategy": strategy,
                    "graph_prompt_version": prompt_ver,
                    "chunk_run_id": chunk_run_id,
                    "graph_run_id": graph_run_id,
                    "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }

                # Source manifest
                (exp_dir / "source_manifest.json").write_text(
                    json.dumps({
                        "experiment_project_id": experiment_project_id,
                        "source_project_key": project_key,
                        "source_project_display": SOURCE_PROJECTS[project_key].display_name,
                        "source_files_count": len(inventory),
                        "base_path": str(SOURCE_PROJECTS[project_key].base_path),
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                # Phase 2: Chunking
                try:
                    chunks = run_chunking(
                        inventory=inventory,
                        chunking_strategy=strategy,
                        experiment_project_id=experiment_project_id,
                        chunk_run_id=chunk_run_id,
                        graph_run_id=graph_run_id,
                        graph_prompt_version=prompt_ver,
                        output_dir=exp_dir,
                    )
                except Exception as exc:
                    logger.error("Chunking failed for %s: %s", experiment_project_id, exc)
                    exp_record["status"] = "chunking_failed"
                    exp_record["error"] = str(exc)
                    experiments.append(exp_record)
                    continue

                # Load chunk stats
                chunk_stats_path = exp_dir / "chunks" / "chunk_stats.json"
                chunk_stats = (
                    json.loads(chunk_stats_path.read_text(encoding="utf-8"))
                    if chunk_stats_path.exists()
                    else {}
                )

                # Phase 3: Graph extraction
                graph_stats: dict = {}
                if not skip_graph:
                    try:
                        all_nodes, all_edges = run_graph_extraction(
                            chunks=chunks,
                            inventory=inventory,
                            experiment_project_id=experiment_project_id,
                            graph_run_id=graph_run_id,
                            graph_prompt_version=prompt_ver,
                            source_project_key=project_key,
                            output_dir=exp_dir,
                            delay_seconds=delay_seconds,
                            model_id=model_id,
                            region=region,
                        )
                        graph_stats_path = exp_dir / "graph_output" / "graph_stats.json"
                        if graph_stats_path.exists():
                            graph_stats = json.loads(graph_stats_path.read_text(encoding="utf-8"))
                        exp_record["status"] = "completed"
                    except Exception as exc:
                        logger.error("Graph extraction failed for %s: %s", experiment_project_id, exc)
                        exp_record["status"] = "graph_failed"
                        exp_record["error"] = str(exc)
                else:
                    exp_record["status"] = "chunking_only"
                    # Still create graph prompt config for reference
                    prompt_text, prompt_sha = _get_prompt_snapshot()
                    (exp_dir / "graph_prompt_config.json").write_text(
                        json.dumps({
                            "file_path": "src/hermes_bedrock_agent/graph_pipeline/extractor.py",
                            "version": "v4.3",
                            "sha256": prompt_sha,
                            "snapshot_path": "graph_prompt_snapshot.md",
                            "note": "Graph extraction was skipped (--skip-graph)",
                        }, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    (exp_dir / "graph_prompt_snapshot.md").write_text(prompt_text, encoding="utf-8")

                exp_record["completed_at"] = datetime.now(timezone.utc).isoformat()
                experiments.append(exp_record)

                # Write run report
                _write_run_report(
                    exp_dir,
                    experiment_project_id,
                    project_key,
                    strategy,
                    prompt_ver,
                    chunk_stats,
                    graph_stats,
                )

    # Phase 4: Comparison
    logger.info("Phase 4: Generating comparison reports...")
    generate_comparison(output_dir, experiments)

    # Write experiment manifest
    manifest = {
        "framework_version": "1.0.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "experiments": experiments,
        "source_projects": {
            k: {"display_name": v.display_name, "base_path": str(v.base_path)}
            for k, v in SOURCE_PROJECTS.items()
        },
        "chunking_strategies": list(CHUNKING_CONFIGS.keys()),
        "graph_prompt_versions": prompt_versions,
        "total_experiments": len(experiments),
        "completed": sum(1 for e in experiments if e.get("status") == "completed"),
        "failed": sum(1 for e in experiments if "failed" in e.get("status", "")),
    }
    (output_dir / "experiment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("=" * 60)
    logger.info("EXPERIMENT COMPLETE")
    logger.info("Total experiments: %d", len(experiments))
    logger.info("Completed: %d", manifest["completed"])
    logger.info("Failed: %d", manifest["failed"])
    logger.info("Output: %s", output_dir)
    logger.info("=" * 60)


# ── CLI entry point ──────────────────────────────────────────────────────────


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Chunk x Graph Prompt Experiment Framework",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_PROJECT_ROOT / "outputs" / "experiments" / "chunk_graph_eval",
        help="Output directory for experiment results",
    )
    parser.add_argument(
        "--source-project",
        action="append",
        dest="source_projects",
        help="Source project key or display name (can be repeated)",
    )
    parser.add_argument(
        "--chunking",
        action="append",
        dest="chunking_strategies",
        help="Chunking strategy: fixed_length or semantic (can be repeated)",
    )
    parser.add_argument(
        "--graph-prompt",
        action="append",
        dest="graph_prompt_versions",
        help="Graph prompt version (default: v43)",
    )
    parser.add_argument(
        "--dry-run-graph",
        action="store_true",
        default=True,
        help="Dry-run mode: generate graph output but don't import to Neptune",
    )
    parser.add_argument(
        "--no-neptune-import",
        action="store_true",
        default=True,
        help="Do not import to Neptune (always true in experiment mode)",
    )
    parser.add_argument(
        "--no-lancedb-write",
        action="store_true",
        default=True,
        help="Do not write to LanceDB (always true in experiment mode)",
    )
    parser.add_argument(
        "--skip-graph",
        action="store_true",
        default=False,
        help="Skip graph extraction (run chunking only)",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=3.0,
        help="Delay between LLM calls (default: 3.0)",
    )
    parser.add_argument(
        "--model-id",
        type=str,
        default=None,
        help="Override Bedrock model ID for extraction",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="Override AWS region",
    )

    args = parser.parse_args()

    main(
        output_dir=args.output_dir,
        source_projects=args.source_projects,
        chunking_strategies=args.chunking_strategies,
        graph_prompt_versions=args.graph_prompt_versions,
        dry_run_graph=args.dry_run_graph,
        delay_seconds=args.delay_seconds,
        model_id=args.model_id,
        region=args.region,
        skip_graph=args.skip_graph,
    )


if __name__ == "__main__":
    cli()
