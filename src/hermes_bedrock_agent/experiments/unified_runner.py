"""Unified experiment runner — registry-driven prompt selection.

Replaces the need for version-specific runners (chunk_graph_eval_baseline.py,
chunk_graph_eval_v44.py) by using the Prompt Registry + adapters for any
registered prompt version.

Usage:
    python -m hermes_bedrock_agent.experiments.unified_runner \
        --graph-prompt v4.4 \
        --output-dir outputs/experiments/unified \
        --dry-run-graph

    python -m hermes_bedrock_agent.experiments.unified_runner \
        --graph-prompt baseline \
        --source-project sample_20260519 \
        --chunking semantic
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
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

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


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


class UnifiedExperimentRunner:
    """Registry-driven experiment runner for any prompt version."""

    def __init__(
        self,
        output_dir: Path,
        graph_prompt_version: str,
        source_projects: list[str] | None = None,
        chunking_strategies: list[str] | None = None,
        delay_seconds: float = 3.0,
        model_id: str | None = None,
        region: str | None = None,
        skip_graph: bool = False,
    ):
        from ..prompts.adapters import get_extraction_prompts
        from ..prompts.registry import get_experiment_metadata, get_version

        self.output_dir = output_dir
        self.graph_prompt_version = graph_prompt_version
        self.delay_seconds = delay_seconds
        self.model_id = model_id or os.getenv(
            "BEDROCK_EXTRACTION_MODEL_ID",
            os.getenv("BEDROCK_MODEL_ID", "jp.anthropic.claude-sonnet-4-6"),
        )
        self.region = region or os.getenv("AWS_REGION", "ap-northeast-1")
        self.skip_graph = skip_graph

        self.source_project_keys = source_projects or list(SOURCE_PROJECTS.keys())
        self.chunking_strategies = chunking_strategies or list(CHUNKING_CONFIGS.keys())

        self.pv = get_version(graph_prompt_version)
        self.extraction_prompts = get_extraction_prompts(graph_prompt_version)
        self.experiment_metadata = get_experiment_metadata(graph_prompt_version)

    def _scan_source_project(self, project: SourceProject) -> list[dict]:
        """Scan parsed markdown files for a source project."""
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

        logger.info("Scanned %s: %d source files", project.display_name, len(inventory))
        return inventory

    def _split_into_chunks(self, markdown: str, max_size: int, min_size: int, mode: str = "fixed", target: int = 0) -> list[str]:
        from ..knowledge_base.chunker import _split_into_chunks as _chunker
        return _chunker(markdown, max_size, min_size, mode=mode, target=target)

    def _run_chunking(
        self,
        inventory: list[dict],
        chunking_strategy: str,
        experiment_project_id: str,
        chunk_run_id: str,
        graph_run_id: str,
        output_dir: Path,
    ) -> list[dict]:
        """Run chunking on all files in inventory."""
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

            text_chunks = self._split_into_chunks(markdown, max_chars, min_chars, mode=mode, target=target)

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
                    "graph_prompt_version": self.graph_prompt_version,
                    "created_at": created_at,
                    "content": chunk_text,
                    "content_length": len(chunk_text),
                    "content_hash": content_hash,
                    "has_table": has_table,
                    "has_mermaid": has_mermaid,
                }
                all_chunks.append(chunk_rec)

        chunks_path = chunks_dir / "chunks.jsonl"
        with open(chunks_path, "w", encoding="utf-8") as f:
            for chunk in all_chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

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
            "config": cfg,
        }

        (chunks_dir / "chunk_stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "chunking_config.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(
            "Chunking [%s]: %d chunks from %d files (avg len: %.0f)",
            chunking_strategy, len(all_chunks), len(inventory), stats["avg_chunk_length"],
        )
        return all_chunks

    def _build_project_sheet_summary(self, inventory: list[dict]) -> str:
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

    def _run_graph_extraction(
        self,
        chunks: list[dict],
        inventory: list[dict],
        experiment_project_id: str,
        graph_run_id: str,
        source_project_key: str,
        output_dir: Path,
    ) -> tuple[list[dict], list[dict]]:
        """Run graph extraction using registry-driven prompts."""
        from ..clients.bedrock import converse_text, make_bedrock_client
        from ..graph_pipeline.extractor import _parse_edge_response, _parse_node_response

        graph_dir = output_dir / "graph_output"
        graph_dir.mkdir(parents=True, exist_ok=True)

        system_prompt = self.extraction_prompts.system_prompt
        node_prompt_template = self.extraction_prompts.node_prompt
        edge_prompt_template = self.extraction_prompts.edge_prompt

        prompt_combined = (
            "=== SYSTEM PROMPT ===\n" + system_prompt
            + "\n\n=== NODE EXTRACTION PROMPT ===\n" + node_prompt_template
            + "\n\n=== EDGE EXTRACTION PROMPT ===\n" + edge_prompt_template
        )
        prompt_sha = hashlib.sha256(prompt_combined.encode()).hexdigest()

        prompt_config = {
            **self.experiment_metadata,
            "model_id": self.model_id,
            "region": self.region,
            "max_tokens": 16000,
            "prompt_sha256_combined": prompt_sha,
        }
        (output_dir / "graph_prompt_config.json").write_text(
            json.dumps(prompt_config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (output_dir / "graph_prompt_snapshot.md").write_text(prompt_combined, encoding="utf-8")

        project_sheet_summary = self._build_project_sheet_summary(inventory)
        project_display = SOURCE_PROJECTS[source_project_key].display_name

        file_chunks: dict[str, list[dict]] = {}
        for chunk in chunks:
            key = chunk["parsed_markdown_path"]
            if key not in file_chunks:
                file_chunks[key] = []
            file_chunks[key].append(chunk)

        client = make_bedrock_client(self.region)
        all_nodes: list[dict] = []
        all_edges: list[dict] = []
        extraction_log: list[dict] = []
        total_files = len(file_chunks)

        logger.info(
            "Starting graph extraction: %d files, model=%s, prompt=%s (adapter=%s)",
            total_files, self.model_id, self.graph_prompt_version, self.pv.adapter,
        )

        for file_idx, (file_path, file_chunk_list) in enumerate(sorted(file_chunks.items())):
            file_chunk_list.sort(key=lambda c: c["chunk_index"])
            combined_content = "\n\n---\n\n".join(c["content"] for c in file_chunk_list)

            first_chunk = file_chunk_list[0]
            workbook_name = first_chunk["workbook_name"]
            sheet_name = first_chunk["sheet_name"]
            source_file = first_chunk["source_file"]

            logger.info(
                "  [%d/%d] %s/%s (%d chunks)",
                file_idx + 1, total_files, workbook_name, sheet_name, len(file_chunk_list),
            )

            node_prompt = node_prompt_template.format(
                project_name=project_display,
                project_id=source_project_key,
                workbook_name=workbook_name,
                sheet_name=sheet_name,
                sheet_type=first_chunk.get("document_role", "sheet"),
                source_file=source_file,
                project_sheet_summary=project_sheet_summary,
                content=combined_content,
            ) if "{project_name}" in node_prompt_template else node_prompt_template + "\n\n" + combined_content

            t0 = time.time()
            try:
                node_response = converse_text(
                    client,
                    prompt=node_prompt,
                    system=system_prompt,
                    model_id=self.model_id,
                    max_tokens=16000,
                )
            except Exception as exc:
                logger.error("    Node extraction failed: %s", exc)
                extraction_log.append({
                    "file": file_path, "phase": "node", "error": str(exc),
                })
                time.sleep(self.delay_seconds)
                continue
            node_time = time.time() - t0

            nodes = _parse_node_response(node_response)
            for node in nodes:
                node["project_name"] = project_display
                node["project_id"] = source_project_key
                node["workbook_name"] = workbook_name
                node["sheet_name"] = sheet_name
                node["source_file"] = source_file

            time.sleep(self.delay_seconds)

            node_id_list = ", ".join(n.get("id", "") for n in nodes)
            edge_prompt = edge_prompt_template.format(
                project_name=project_display,
                project_id=source_project_key,
                workbook_name=workbook_name,
                sheet_name=sheet_name,
                sheet_type=first_chunk.get("document_role", "sheet"),
                source_file=source_file,
                node_id_list=node_id_list,
                content=combined_content,
            ) if "{project_name}" in edge_prompt_template else edge_prompt_template + "\n\nNode IDs: " + node_id_list + "\n\n" + combined_content

            t0 = time.time()
            try:
                edge_response = converse_text(
                    client,
                    prompt=edge_prompt,
                    system=system_prompt,
                    model_id=self.model_id,
                    max_tokens=16000,
                )
            except Exception as exc:
                logger.error("    Edge extraction failed: %s", exc)
                extraction_log.append({
                    "file": file_path, "phase": "edge", "error": str(exc),
                })
                all_nodes.extend(nodes)
                time.sleep(self.delay_seconds)
                continue
            edge_time = time.time() - t0

            edges = _parse_edge_response(edge_response)
            for edge in edges:
                edge["project_name"] = project_display
                edge["project_id"] = source_project_key
                edge["source_file"] = source_file

            all_nodes.extend(nodes)
            all_edges.extend(edges)

            extraction_log.append({
                "file": file_path,
                "workbook": workbook_name,
                "sheet": sheet_name,
                "chunks": len(file_chunk_list),
                "nodes": len(nodes),
                "edges": len(edges),
                "node_time_s": round(node_time, 2),
                "edge_time_s": round(edge_time, 2),
            })

            logger.info("    -> %d nodes, %d edges (%.1fs + %.1fs)", len(nodes), len(edges), node_time, edge_time)
            time.sleep(self.delay_seconds)

        with open(graph_dir / "nodes.jsonl", "w", encoding="utf-8") as f:
            for n in all_nodes:
                f.write(json.dumps(n, ensure_ascii=False) + "\n")
        with open(graph_dir / "edges.jsonl", "w", encoding="utf-8") as f:
            for e in all_edges:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        with open(graph_dir / "extraction_log.jsonl", "w", encoding="utf-8") as f:
            for rec in extraction_log:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        graph_stats = {
            "experiment_project_id": experiment_project_id,
            "graph_prompt_version": self.graph_prompt_version,
            "graph_prompt_adapter": self.pv.adapter,
            "graph_prompt_scope": self.pv.scope,
            "model_id": self.model_id,
            "total_nodes": len(all_nodes),
            "total_edges": len(all_edges),
            "total_files_processed": total_files,
            "errors": sum(1 for r in extraction_log if "error" in r),
        }
        (graph_dir / "graph_stats.json").write_text(
            json.dumps(graph_stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info(
            "Graph extraction complete: %d nodes, %d edges",
            len(all_nodes), len(all_edges),
        )
        return all_nodes, all_edges

    def run(self) -> dict:
        """Execute the full experiment matrix."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        runs_dir = self.output_dir / "runs"
        runs_dir.mkdir(exist_ok=True)

        experiments: list[dict] = []

        for project_key in self.source_project_keys:
            if project_key not in SOURCE_PROJECTS:
                logger.error("Unknown source project: %s", project_key)
                continue

            project = SOURCE_PROJECTS[project_key]
            inventory = self._scan_source_project(project)
            if not inventory:
                logger.warning("No files found for %s", project_key)
                continue

            inv_dir = self.output_dir / "source_inventory"
            inv_dir.mkdir(parents=True, exist_ok=True)
            (inv_dir / f"{project_key}_inventory.json").write_text(
                json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            for strategy in self.chunking_strategies:
                if strategy == "fixed":
                    strategy = "fixed_length"
                if strategy not in CHUNKING_CONFIGS:
                    logger.error("Unknown chunking strategy: %s", strategy)
                    continue

                prompt_ver = self.graph_prompt_version
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
                    "source_project_display": project.display_name,
                    "chunking_strategy": strategy,
                    "graph_prompt_version": prompt_ver,
                    "graph_prompt_adapter": self.pv.adapter,
                    "graph_prompt_scope": self.pv.scope,
                    "chunk_run_id": chunk_run_id,
                    "graph_run_id": graph_run_id,
                    "status": "running",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    **self.experiment_metadata,
                }

                (exp_dir / "experiment_metadata.json").write_text(
                    json.dumps(self.experiment_metadata, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                try:
                    chunks = self._run_chunking(
                        inventory=inventory,
                        chunking_strategy=strategy,
                        experiment_project_id=experiment_project_id,
                        chunk_run_id=chunk_run_id,
                        graph_run_id=graph_run_id,
                        output_dir=exp_dir,
                    )
                except Exception as exc:
                    logger.error("Chunking failed for %s: %s", experiment_project_id, exc)
                    exp_record["status"] = "chunking_failed"
                    exp_record["error"] = str(exc)
                    experiments.append(exp_record)
                    continue

                if not self.skip_graph:
                    try:
                        self._run_graph_extraction(
                            chunks=chunks,
                            inventory=inventory,
                            experiment_project_id=experiment_project_id,
                            graph_run_id=graph_run_id,
                            source_project_key=project_key,
                            output_dir=exp_dir,
                        )
                        exp_record["status"] = "completed"
                    except Exception as exc:
                        logger.error("Graph extraction failed for %s: %s", experiment_project_id, exc)
                        exp_record["status"] = "graph_failed"
                        exp_record["error"] = str(exc)
                else:
                    exp_record["status"] = "chunking_only"

                exp_record["completed_at"] = datetime.now(timezone.utc).isoformat()
                experiments.append(exp_record)

        manifest = {
            "framework_version": "2.0.0",
            "runner": "unified_runner",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(self.output_dir),
            "graph_prompt_version": self.graph_prompt_version,
            "graph_prompt_adapter": self.pv.adapter,
            "graph_prompt_scope": self.pv.scope,
            "experiments": experiments,
            "experiment_metadata": self.experiment_metadata,
            "source_projects": {
                k: {"display_name": v.display_name, "base_path": str(v.base_path)}
                for k, v in SOURCE_PROJECTS.items()
                if k in self.source_project_keys
            },
            "chunking_strategies": self.chunking_strategies,
            "total_experiments": len(experiments),
            "completed": sum(1 for e in experiments if e.get("status") == "completed"),
            "failed": sum(1 for e in experiments if "failed" in e.get("status", "")),
        }
        (self.output_dir / "experiment_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        logger.info("=" * 60)
        logger.info("EXPERIMENT COMPLETE")
        logger.info("Total experiments: %d", len(experiments))
        logger.info("Completed: %d", manifest["completed"])
        logger.info("Failed: %d", manifest["failed"])
        logger.info("Output: %s", self.output_dir)
        logger.info("=" * 60)

        return manifest


def main(
    output_dir: Path,
    graph_prompt_version: str = "v4.3",
    source_projects: list[str] | None = None,
    chunking_strategies: list[str] | None = None,
    delay_seconds: float = 3.0,
    model_id: str | None = None,
    region: str | None = None,
    skip_graph: bool = False,
) -> dict:
    """Main entry point for the unified experiment runner."""
    runner = UnifiedExperimentRunner(
        output_dir=output_dir,
        graph_prompt_version=graph_prompt_version,
        source_projects=source_projects,
        chunking_strategies=chunking_strategies,
        delay_seconds=delay_seconds,
        model_id=model_id,
        region=region,
        skip_graph=skip_graph,
    )
    return runner.run()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Unified Experiment Runner (registry-driven prompt selection)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_PROJECT_ROOT / "outputs" / "experiments" / "unified",
        help="Output directory for experiment results",
    )
    parser.add_argument(
        "--graph-prompt",
        type=str,
        default="v4.3",
        dest="graph_prompt_version",
        help="Graph prompt version from registry (e.g. v4.3, baseline, v4.4)",
    )
    parser.add_argument(
        "--source-project",
        action="append",
        dest="source_projects",
        help="Source project key (can be repeated; default: all)",
    )
    parser.add_argument(
        "--chunking",
        action="append",
        dest="chunking_strategies",
        help="Chunking strategy: fixed_length or semantic (can be repeated; default: all)",
    )
    parser.add_argument(
        "--dry-run-graph",
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
        graph_prompt_version=args.graph_prompt_version,
        source_projects=args.source_projects,
        chunking_strategies=args.chunking_strategies,
        delay_seconds=args.delay_seconds,
        model_id=args.model_id,
        region=args.region,
        skip_graph=args.dry_run_graph,
    )


if __name__ == "__main__":
    cli()
