"""v4.4 Graph Extraction Experiment.

Runs the same chunk x graph evaluation as chunk_graph_eval.py but uses the
v4.4 Semantic Map prompt instead of v4.3.

Chunks are reused from the existing v4.3 experiment (same source files, same
chunking strategies) — only the graph extraction prompt changes.

All outputs go to outputs/experiments/chunk_graph_eval_v44/ — completely
isolated from the v4.3 and baseline experiments.

Usage:
    python -m hermes_bedrock_agent.experiments.chunk_graph_eval_v44 \
        --output-dir outputs/experiments/chunk_graph_eval_v44
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .v44_prompts import (
    V44_EDGE_EXTRACTION_PROMPT,
    V44_NODE_EXTRACTION_PROMPT,
    V44_PROMPT_FILE,
    V44_PROMPT_VERSION,
    V44_SYSTEM_PROMPT,
)
from .chunk_graph_eval import (
    CHUNKING_CONFIGS,
    SOURCE_PROJECTS,
    _build_project_sheet_summary,
    _scan_source_project,
    run_chunking,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_V43_EXPERIMENT_DIR = _PROJECT_ROOT / "outputs" / "experiments" / "chunk_graph_eval"


# ── Chunk reuse from v4.3 ───────────────────────────────────────────────────


def _load_v43_chunks(
    source_project_key: str,
    chunking_strategy: str,
) -> list[dict]:
    """Load chunks from the existing v4.3 experiment run."""
    v43_experiment_id = f"exp_{source_project_key}__chunk_{chunking_strategy}__graph_v43"
    chunks_path = (
        _V43_EXPERIMENT_DIR / "runs" / v43_experiment_id / "chunks" / "chunks.jsonl"
    )

    if not chunks_path.exists():
        logger.warning("v4.3 chunks not found at %s", chunks_path)
        return []

    chunks: list[dict] = []
    with open(chunks_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))

    logger.info(
        "Loaded %d chunks from v4.3 experiment: %s",
        len(chunks),
        v43_experiment_id,
    )
    return chunks


def _rewrite_chunk_metadata(
    chunks: list[dict],
    experiment_project_id: str,
    graph_run_id: str,
) -> list[dict]:
    """Rewrite chunk metadata for the v4.4 experiment.

    Keeps all content and source metadata unchanged, only updates
    experiment-level identifiers and prompt version.
    """
    rewritten: list[dict] = []
    for chunk in chunks:
        new_chunk = dict(chunk)
        new_chunk["experiment_project_id"] = experiment_project_id
        new_chunk["graph_run_id"] = graph_run_id
        new_chunk["graph_prompt_version"] = V44_PROMPT_VERSION
        rewritten.append(new_chunk)
    return rewritten


def _write_chunks(chunks: list[dict], output_dir: Path) -> dict:
    """Write chunks.jsonl and chunk_stats.json for the v4.4 run."""
    chunks_dir = output_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunks_path = chunks_dir / "chunks.jsonl"
    with open(chunks_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    lengths = [c["content_length"] for c in chunks]
    stats = {
        "experiment_project_id": chunks[0]["experiment_project_id"] if chunks else "",
        "chunking_strategy": chunks[0]["chunking_strategy"] if chunks else "",
        "total_chunks": len(chunks),
        "total_source_files": len({c["parsed_markdown_path"] for c in chunks}),
        "avg_chunk_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "max_chunk_length": max(lengths) if lengths else 0,
        "min_chunk_length": min(lengths) if lengths else 0,
        "median_chunk_length": sorted(lengths)[len(lengths) // 2] if lengths else 0,
        "chunks_with_tables": sum(1 for c in chunks if c.get("has_table")),
        "chunks_with_mermaid": sum(1 for c in chunks if c.get("has_mermaid")),
        "chunks_with_empty_metadata": sum(
            1 for c in chunks
            if not c.get("section_title") and not c.get("workbook_name")
        ),
        "config": CHUNKING_CONFIGS.get(
            chunks[0]["chunking_strategy"] if chunks else "fixed_length", {}
        ),
        "note": "Chunks reused from v4.3 experiment with updated metadata",
    }

    stats_path = chunks_dir / "chunk_stats.json"
    stats_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    config_path = output_dir / "chunking_config.json"
    config_path.write_text(
        json.dumps(
            CHUNKING_CONFIGS.get(
                chunks[0]["chunking_strategy"] if chunks else "fixed_length", {}
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.info(
        "Wrote %d chunks (reused from v4.3) to %s",
        len(chunks),
        chunks_path,
    )
    return stats


# ── v4.4 graph extraction ──────────────────────────────────────────────────


def _get_v44_prompt_snapshot() -> tuple[str, str]:
    """Read the v4.4 prompt file and compute SHA256."""
    prompt_path = _PROJECT_ROOT / V44_PROMPT_FILE
    if prompt_path.exists():
        prompt_text = prompt_path.read_text(encoding="utf-8")
    else:
        prompt_text = (
            "=== V44 SYSTEM PROMPT ===\n"
            + V44_SYSTEM_PROMPT
            + "\n\n=== V44 NODE EXTRACTION PROMPT ===\n"
            + V44_NODE_EXTRACTION_PROMPT
            + "\n\n=== V44 EDGE EXTRACTION PROMPT ===\n"
            + V44_EDGE_EXTRACTION_PROMPT
        )

    sha256 = hashlib.sha256(prompt_text.encode()).hexdigest()
    return prompt_text, sha256


def run_v44_graph_extraction(
    chunks: list[dict],
    inventory: list[dict],
    experiment_project_id: str,
    graph_run_id: str,
    source_project_key: str,
    output_dir: Path,
    delay_seconds: float = 3.0,
    model_id: Optional[str] = None,
    region: Optional[str] = None,
) -> tuple[list[dict], list[dict]]:
    """Run graph extraction using v4.4 prompts.

    Same per-file-group approach as baseline but with v4.4 prompt enhancements.
    """
    import signal
    from ..clients.bedrock import converse_text, make_bedrock_client
    from ..graph_pipeline.extractor import _parse_edge_response, _parse_node_response

    class _APITimeout(Exception):
        pass

    def _timeout_handler(signum, frame):
        raise _APITimeout("Bedrock API call timed out")

    def _converse_with_timeout(client, model_id, prompt, max_tokens, timeout_sec=120):
        """Wrapper around converse_text with signal-based timeout."""
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout_sec)
        try:
            result = converse_text(
                client=client,
                model_id=model_id,
                prompt=prompt,
                max_tokens=max_tokens,
            )
            signal.alarm(0)
            return result
        except _APITimeout:
            signal.alarm(0)
            raise
        finally:
            signal.signal(signal.SIGALRM, old_handler)
            signal.alarm(0)

    region = region or os.getenv("AWS_REGION", "ap-northeast-1")
    model_id = model_id or os.getenv(
        "BEDROCK_EXTRACTION_MODEL_ID",
        os.getenv("BEDROCK_MODEL_ID", "jp.anthropic.claude-sonnet-4-6"),
    )

    graph_dir = output_dir / "graph_output"
    graph_dir.mkdir(parents=True, exist_ok=True)

    prompt_text, prompt_sha = _get_v44_prompt_snapshot()
    prompt_config = {
        "file_path": V44_PROMPT_FILE,
        "version": V44_PROMPT_VERSION,
        "sha256": prompt_sha,
        "snapshot_path": "graph_prompt_snapshot.md",
        "model_id": model_id,
        "region": region,
        "max_tokens": 16000,
        "adapter_module": "hermes_bedrock_agent.experiments.v44_prompts",
    }
    (output_dir / "graph_prompt_config.json").write_text(
        json.dumps(prompt_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "graph_prompt_snapshot.md").write_text(prompt_text, encoding="utf-8")

    project_sheet_summary = _build_project_sheet_summary(inventory)
    project_display = SOURCE_PROJECTS[source_project_key].display_name

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
        "Starting v4.4 graph extraction: %d files, model=%s",
        total_files,
        model_id,
    )

    for file_idx, (file_path, file_chunk_list) in enumerate(file_chunks.items()):
        representative = file_chunk_list[0]
        workbook_name = representative["workbook_name"]
        sheet_name = representative["sheet_name"]
        sheet_type = representative.get("source_type", "excel")

        combined_content = "\n\n---\n\n".join(c["content"] for c in file_chunk_list)
        if len(combined_content) > 25000:
            combined_content = combined_content[:25000] + "\n\n[...content truncated for extraction...]"

        log_entry: dict[str, Any] = {
            "file_path": file_path,
            "file_index": file_idx,
            "workbook_name": workbook_name,
            "sheet_name": sheet_name,
            "chunks_in_file": len(file_chunk_list),
            "content_length": len(combined_content),
        }

        # Pass 1: Node extraction with v4.4 prompt
        node_prompt = V44_NODE_EXTRACTION_PROMPT.format(
            project_name=project_display,
            project_id=source_project_key,
            workbook_name=workbook_name,
            sheet_name=sheet_name,
            sheet_type=sheet_type,
            source_file=file_path,
            project_sheet_summary=project_sheet_summary,
            content=combined_content,
        )
        full_prompt = f"<system>\n{V44_SYSTEM_PROMPT}\n</system>\n\n{node_prompt}"

        nodes: list[dict] = []
        try:
            response, usage = _converse_with_timeout(
                client=client,
                model_id=model_id,
                prompt=full_prompt,
                max_tokens=16000,
                timeout_sec=180,
            )
            nodes = _parse_node_response(response)
            log_entry["node_count"] = len(nodes)
            log_entry["node_usage"] = usage
            logger.info(
                "[%d/%d] %s/%s: %d nodes extracted (v4.4)",
                file_idx + 1, total_files, workbook_name, sheet_name, len(nodes),
            )
        except Exception as exc:
            log_entry["node_error"] = str(exc)
            logger.error(
                "[%d/%d] Node extraction failed for %s: %s",
                file_idx + 1, total_files, sheet_name, exc,
            )

        time.sleep(delay_seconds)

        # Pass 2: Edge extraction with v4.4 prompt
        edges: list[dict] = []
        if nodes:
            node_id_list = "\n".join(
                f"- {n.get('id', '?')} ({n.get('entity_type', '?')}): {n.get('name', '')}"
                for n in nodes[:80]
            )
            edge_prompt = V44_EDGE_EXTRACTION_PROMPT.format(
                project_name=project_display,
                project_id=source_project_key,
                workbook_name=workbook_name,
                sheet_name=sheet_name,
                sheet_type=sheet_type,
                source_file=file_path,
                node_id_list=node_id_list,
                content=combined_content,
            )
            full_prompt2 = f"<system>\n{V44_SYSTEM_PROMPT}\n</system>\n\n{edge_prompt}"

            try:
                response2, usage2 = _converse_with_timeout(
                    client=client,
                    model_id=model_id,
                    prompt=full_prompt2,
                    max_tokens=16000,
                    timeout_sec=180,
                )
                edges = _parse_edge_response(response2)
                log_entry["edge_count"] = len(edges)
                log_entry["edge_usage"] = usage2
                logger.info(
                    "[%d/%d] %s/%s: %d edges extracted (v4.4)",
                    file_idx + 1, total_files, workbook_name, sheet_name, len(edges),
                )
            except Exception as exc:
                log_entry["edge_error"] = str(exc)
                logger.error(
                    "[%d/%d] Edge extraction failed for %s: %s",
                    file_idx + 1, total_files, sheet_name, exc,
                )

            time.sleep(delay_seconds)

        # Attach experiment metadata
        chunk_ids = [c["chunk_id"] for c in file_chunk_list]
        for node in nodes:
            node["experiment_project_id"] = experiment_project_id
            node["source_project_key"] = source_project_key
            node["chunk_run_id"] = file_chunk_list[0]["chunk_run_id"]
            node["graph_run_id"] = graph_run_id
            node["graph_prompt_version"] = V44_PROMPT_VERSION
            node["chunking_strategy"] = file_chunk_list[0]["chunking_strategy"]
            node["source_chunk_ids"] = chunk_ids
            node["source_file"] = file_path
            node["parsed_markdown_path"] = file_path

        for edge in edges:
            edge["experiment_project_id"] = experiment_project_id
            edge["source_project_key"] = source_project_key
            edge["chunk_run_id"] = file_chunk_list[0]["chunk_run_id"]
            edge["graph_run_id"] = graph_run_id
            edge["graph_prompt_version"] = V44_PROMPT_VERSION
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
        "graph_prompt_version": V44_PROMPT_VERSION,
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
        f"Prompt version: v4.4 (Semantic Map v4.4 Full Clean)\n\n"
        f"This directory is a placeholder for future QA evaluation.\n"
        f"Chunks and graph outputs are ready for retrieval testing.\n",
        encoding="utf-8",
    )

    logger.info(
        "v4.4 graph extraction complete: %d nodes, %d edges from %d files",
        len(all_nodes), len(all_edges), total_files,
    )
    return all_nodes, all_edges


# ── Run report ───────────────────────────────────────────────────────────────


def _write_run_report(
    output_dir: Path,
    experiment_project_id: str,
    source_project_key: str,
    chunking_strategy: str,
    chunk_stats: dict,
    graph_stats: dict,
) -> None:
    """Write a markdown run report."""
    report = f"""# Experiment Run Report — v4.4

## Experiment ID
`{experiment_project_id}`

## Configuration
- Source Project: `{source_project_key}` ({SOURCE_PROJECTS[source_project_key].display_name})
- Chunking Strategy: `{chunking_strategy}`
- Graph Prompt Version: `{V44_PROMPT_VERSION}` (Semantic Map v4.4 Full Clean)
- Prompt File: `{V44_PROMPT_FILE}`

## Chunking Results (reused from v4.3)
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


# ── Comparison ───────────────────────────────────────────────────────────────


def generate_comparison(output_dir: Path, experiments: list[dict]) -> None:
    """Generate comparison CSVs and summary across all v4.4 experiments."""
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
    summary = "# v4.4 Experiment Summary\n\n"
    summary += f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n"
    summary += "## Prompt Version\n\n"
    summary += f"- **v4.4** — Semantic Map v4.4 Full Clean (`{V44_PROMPT_FILE}`)\n"
    summary += "- Adapted for per-file-group extraction via `v44_prompts.py`\n\n"
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

    summary += "\n## Chunking Comparison (reused from v4.3)\n\n"
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

    summary += "\n## Key Differences from v4.3 / Baseline\n\n"
    summary += "- P0 Original Technical Name Preservation Rule (section 0A)\n"
    summary += "- FieldGroup as first-class entity with parent context resolution\n"
    summary += "- Canonical Entity Registry — deduplicate before generating relationships\n"
    summary += "- Stricter weak-link exclusion (confidence ≤ 0.70, MUST be pending)\n"
    summary += "- Display Graph quality gates (evidence:semantic ratio ≤ 0.20)\n"
    summary += "- HAS_FIELD_GROUP relationship type\n"
    summary += "- DUPLICATE_OF / SAME_AS for canonicalization\n"
    summary += "- Test Specification Extraction (TestSpec, TestCase)\n"
    summary += "- Source Code Handling (CodeModule, CodeFunction)\n"
    summary += "- Annotation type for Mermaid annotations\n"
    summary += "- Structural inference excluded from Display Graph core\n"

    (comp_dir / "experiment_summary.md").write_text(summary, encoding="utf-8")
    logger.info("Comparison reports written to %s", comp_dir)


# ── Main orchestrator ────────────────────────────────────────────────────────


def main(
    output_dir: Optional[Path] = None,
    source_projects: Optional[list[str]] = None,
    chunking_strategies: Optional[list[str]] = None,
    delay_seconds: float = 3.0,
    model_id: Optional[str] = None,
    region: Optional[str] = None,
    skip_graph: bool = False,
) -> None:
    """Run the v4.4 experiment pipeline."""
    output_dir = output_dir or (
        _PROJECT_ROOT / "outputs" / "experiments" / "chunk_graph_eval_v44"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    project_keys = source_projects or list(SOURCE_PROJECTS.keys())
    strategies = chunking_strategies or list(CHUNKING_CONFIGS.keys())

    logger.info("=" * 60)
    logger.info("v4.4 GRAPH EXTRACTION EXPERIMENT")
    logger.info("=" * 60)
    logger.info("Output dir: %s", output_dir)
    logger.info("Projects: %s", project_keys)
    logger.info("Chunking strategies: %s", strategies)
    logger.info("Graph prompt version: %s", V44_PROMPT_VERSION)
    logger.info("Skip graph extraction: %s", skip_graph)
    logger.info("=" * 60)

    # Phase 1: Source inventory (reuse scan logic)
    logger.info("Phase 1: Building source inventories...")
    inv_dir = output_dir / "source_inventory"
    inv_dir.mkdir(parents=True, exist_ok=True)

    inventories: dict[str, list[dict]] = {}
    for key in project_keys:
        if key not in SOURCE_PROJECTS:
            logger.error("Unknown source project: %s", key)
            continue
        inv = _scan_source_project(SOURCE_PROJECTS[key])
        inventories[key] = inv
        inv_path = inv_dir / f"{key}_inventory.json"
        inv_path.write_text(
            json.dumps(inv, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Saved inventory: %s (%d files)", inv_path.name, len(inv))

    # Phase 2 & 3: Run experiments
    experiments: list[dict] = []
    runs_dir = output_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    for project_key in project_keys:
        if project_key not in SOURCE_PROJECTS:
            continue

        inventory = inventories.get(project_key, [])
        if not inventory:
            logger.warning("No files found for project: %s", project_key)
            continue

        for strategy in strategies:
            if strategy not in CHUNKING_CONFIGS:
                if strategy == "fixed":
                    strategy = "fixed_length"
                elif strategy not in CHUNKING_CONFIGS:
                    logger.error("Unknown chunking strategy: %s", strategy)
                    continue

            experiment_project_id = (
                f"exp_{project_key}__chunk_{strategy}__graph_{V44_PROMPT_VERSION}"
            )
            chunk_run_id = f"{project_key}__chunk_{strategy}"
            graph_run_id = (
                f"{project_key}__chunk_{strategy}__graph_{V44_PROMPT_VERSION}"
            )

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
                "graph_prompt_version": V44_PROMPT_VERSION,
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

            # Phase 2: Chunk reuse from v4.3
            try:
                v43_chunks = _load_v43_chunks(project_key, strategy)
                if v43_chunks:
                    chunks = _rewrite_chunk_metadata(
                        v43_chunks, experiment_project_id, graph_run_id
                    )
                else:
                    logger.info(
                        "v4.3 chunks not available, running chunking from scratch"
                    )
                    chunks = run_chunking(
                        inventory=inventory,
                        chunking_strategy=strategy,
                        experiment_project_id=experiment_project_id,
                        chunk_run_id=chunk_run_id,
                        graph_run_id=graph_run_id,
                        graph_prompt_version=V44_PROMPT_VERSION,
                        output_dir=exp_dir,
                    )

                if v43_chunks:
                    chunk_stats = _write_chunks(chunks, exp_dir)
                else:
                    chunk_stats_path = exp_dir / "chunks" / "chunk_stats.json"
                    chunk_stats = (
                        json.loads(chunk_stats_path.read_text(encoding="utf-8"))
                        if chunk_stats_path.exists()
                        else {}
                    )
            except Exception as exc:
                logger.error(
                    "Chunking failed for %s: %s", experiment_project_id, exc
                )
                exp_record["status"] = "chunking_failed"
                exp_record["error"] = str(exc)
                experiments.append(exp_record)
                continue

            # Phase 3: Graph extraction
            graph_stats: dict = {}
            if not skip_graph:
                try:
                    all_nodes, all_edges = run_v44_graph_extraction(
                        chunks=chunks,
                        inventory=inventory,
                        experiment_project_id=experiment_project_id,
                        graph_run_id=graph_run_id,
                        source_project_key=project_key,
                        output_dir=exp_dir,
                        delay_seconds=delay_seconds,
                        model_id=model_id,
                        region=region,
                    )
                    graph_stats_path = exp_dir / "graph_output" / "graph_stats.json"
                    if graph_stats_path.exists():
                        graph_stats = json.loads(
                            graph_stats_path.read_text(encoding="utf-8")
                        )
                    exp_record["status"] = "completed"
                except Exception as exc:
                    logger.error(
                        "Graph extraction failed for %s: %s",
                        experiment_project_id,
                        exc,
                    )
                    exp_record["status"] = "graph_failed"
                    exp_record["error"] = str(exc)
            else:
                exp_record["status"] = "chunking_only"
                prompt_text, prompt_sha = _get_v44_prompt_snapshot()
                (exp_dir / "graph_prompt_config.json").write_text(
                    json.dumps({
                        "file_path": V44_PROMPT_FILE,
                        "version": V44_PROMPT_VERSION,
                        "sha256": prompt_sha,
                        "snapshot_path": "graph_prompt_snapshot.md",
                        "note": "Graph extraction was skipped (--skip-graph)",
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (exp_dir / "graph_prompt_snapshot.md").write_text(
                    prompt_text, encoding="utf-8"
                )

            exp_record["completed_at"] = datetime.now(timezone.utc).isoformat()
            experiments.append(exp_record)

            # Write run report
            _write_run_report(
                exp_dir,
                experiment_project_id,
                project_key,
                strategy,
                chunk_stats,
                graph_stats,
            )

    # Phase 4: Comparison
    logger.info("Phase 4: Generating comparison reports...")
    generate_comparison(output_dir, experiments)

    # Write experiment manifest
    manifest = {
        "framework_version": "1.0.0",
        "prompt_version": V44_PROMPT_VERSION,
        "prompt_file": V44_PROMPT_FILE,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "experiments": experiments,
        "source_projects": {
            k: {"display_name": v.display_name, "base_path": str(v.base_path)}
            for k, v in SOURCE_PROJECTS.items()
        },
        "chunking_strategies": list(CHUNKING_CONFIGS.keys()),
        "graph_prompt_version": V44_PROMPT_VERSION,
        "total_experiments": len(experiments),
        "completed": sum(1 for e in experiments if e.get("status") == "completed"),
        "failed": sum(1 for e in experiments if "failed" in e.get("status", "")),
    }
    (output_dir / "experiment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("=" * 60)
    logger.info("v4.4 EXPERIMENT COMPLETE")
    logger.info("Total experiments: %d", len(experiments))
    logger.info("Completed: %d", manifest["completed"])
    logger.info("Failed: %d", manifest["failed"])
    logger.info("Output: %s", output_dir)
    logger.info("=" * 60)


# ── CLI entry point ──────────────────────────────────────────────────────────


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="v4.4 Graph Extraction Experiment (Semantic Map v4.4 Full Clean)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_PROJECT_ROOT / "outputs" / "experiments" / "chunk_graph_eval_v44",
        help="Output directory for experiment results",
    )
    parser.add_argument(
        "--source-project",
        action="append",
        dest="source_projects",
        help="Source project key (can be repeated)",
    )
    parser.add_argument(
        "--chunking",
        action="append",
        dest="chunking_strategies",
        help="Chunking strategy: fixed_length or semantic (can be repeated)",
    )
    parser.add_argument(
        "--skip-graph",
        action="store_true",
        default=False,
        help="Skip graph extraction (write chunks only)",
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
        delay_seconds=args.delay_seconds,
        model_id=args.model_id,
        region=args.region,
        skip_graph=args.skip_graph,
    )


if __name__ == "__main__":
    cli()
