"""
Pipeline: Load Neptune V2 (Stage 09).

Orchestrates the full Stage 09 pipeline:
1. Load linked graph data
2. Apply layer filter
3. Generate Cypher export
4. Validate (dry-run)
5. Optionally execute against Neptune
6. Generate report
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.graph.neptune_cypher_exporter import NeptuneCypherExporter
from hermes_bedrock_agent.v2.graph.neptune_loader import NeptuneLoader, NeptuneLoaderConfig
from hermes_bedrock_agent.v2.graph.neptune_load_reporter import NeptuneLoadReporter


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL file."""
    items = []
    if not path.exists():
        return items
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def run_pipeline(
    output_dir: str | Path,
    run_id: str = "murata_semantic_v2",
    dataset: str = "murata",
    layer: str = "all",
    dry_run: bool = True,
    execute: bool = False,
    clear_before_load: bool = False,
    cypher_output_path: str | None = None,
    neptune_graph_id: str = "",
    neptune_region: str = "ap-northeast-1",
) -> dict[str, Any]:
    """Execute the full Stage 09 pipeline."""
    output_dir = Path(output_dir)

    # Default Cypher output path
    if cypher_output_path is None:
        if layer == "all":
            cypher_output_path = str(output_dir / "load_neptune.cypher")
        else:
            cypher_output_path = str(output_dir / f"load_neptune_{layer}.cypher")

    # ======================================================================
    # Phase 1: Load inputs
    # ======================================================================
    print("[Stage 09] Loading inputs...")
    linked_nodes = load_jsonl(output_dir / "graph_nodes_linked.jsonl")
    linked_edges = load_jsonl(output_dir / "graph_edges_linked.jsonl")
    evidence_links = load_jsonl(output_dir / "evidence_links.jsonl")
    evidence_chunks = load_jsonl(output_dir / "evidence_chunks.jsonl")

    print(f"  Linked nodes: {len(linked_nodes)}")
    print(f"  Linked edges: {len(linked_edges)}")
    print(f"  Evidence links: {len(evidence_links)}")
    print(f"  Evidence chunks: {len(evidence_chunks)}")
    print(f"  Layer filter: {layer}")

    # ======================================================================
    # Phase 2: Generate Cypher
    # ======================================================================
    print("\n[Stage 09] Generating Cypher export...")
    exporter = NeptuneCypherExporter(
        linked_nodes=linked_nodes,
        linked_edges=linked_edges,
        evidence_links=evidence_links,
        evidence_chunks=evidence_chunks,
        layer_filter=layer,
        run_id=run_id,
        dataset=dataset,
    )
    cypher_content = exporter.export()
    export_stats = exporter.stats

    # Write Cypher file
    cypher_path = Path(cypher_output_path)
    cypher_path.parent.mkdir(parents=True, exist_ok=True)
    cypher_path.write_text(cypher_content, encoding="utf-8")

    print(f"  → {cypher_output_path}")
    print(f"  Graph nodes exported: {export_stats['exported_graph_nodes']}")
    print(f"  Evidence chunk nodes: {export_stats['exported_evidence_chunk_nodes']}")
    print(f"  Relationships: {export_stats['exported_relationships']}")
    print(f"  HAS_EVIDENCE edges: {export_stats['exported_has_evidence']}")
    print(f"  Total statements: {export_stats['total_statements']}")
    print(f"  Skipped edges: {export_stats['skipped_edges']}")
    print(f"  JOURNAL_BASE filtered: {export_stats['journal_base_filtered']}")

    # ======================================================================
    # Phase 3: Neptune Loader
    # ======================================================================
    loader_config = NeptuneLoaderConfig(
        graph_id=neptune_graph_id,
        region=neptune_region,
        execute=execute,
        clear_before_load=clear_before_load,
    )
    loader = NeptuneLoader(loader_config)
    config_validation = loader.validate_config()

    print(f"\n[Stage 09] Neptune config:")
    print(f"  Graph ID: {config_validation['graph_id']}")
    print(f"  Region: {config_validation['region']}")
    print(f"  Configured: {config_validation['is_configured']}")

    if execute and not dry_run:
        # Actual execution path
        print("\n[Stage 09] EXECUTING Neptune load...")
        queries = exporter.get_parameterized_queries()
        loader_stats = loader.execute_load(queries)
        print(f"  Executed: {loader_stats['statements_executed']}")
        print(f"  Failed: {loader_stats['statements_failed']}")
    else:
        # Dry-run validation
        print("\n[Stage 09] Running dry-run validation...")
        queries = exporter.get_parameterized_queries()
        loader_stats = loader.dry_run(queries)
        print(f"  Statements validated: {loader_stats['statements_total']}")
        print(f"  Valid: {loader_stats.get('valid', True)}")
        val_errors = loader_stats.get('validation_errors', [])
        if val_errors:
            print(f"  ⚠️ Validation errors: {len(val_errors)}")
            for e in val_errors[:5]:
                print(f"    - {e}")

    # ======================================================================
    # Phase 4: Generate Report
    # ======================================================================
    print("\n[Stage 09] Generating report...")
    reporter = NeptuneLoadReporter(
        export_stats=export_stats,
        loader_stats=loader_stats,
        config_validation=config_validation,
        cypher_output_path=cypher_output_path,
        run_id=run_id,
        dataset=dataset,
    )
    report = reporter.generate_report()
    report_path = output_dir / "neptune_load_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"  → neptune_load_report.md")

    # ======================================================================
    # Done
    # ======================================================================
    mode = "execute" if (execute and not dry_run) else "dry_run"
    print(f"\n[Stage 09] COMPLETE (mode={mode})")
    print(f"  Cypher: {cypher_output_path}")
    print(f"  Report: {report_path}")
    print(f"  Total statements: {export_stats['total_statements']}")
    if mode == "dry_run":
        print(f"  ℹ️ No actual Neptune writes performed.")

    return {
        "mode": mode,
        "export_stats": export_stats,
        "loader_stats": loader_stats,
        "config_validation": config_validation,
        "cypher_output_path": cypher_output_path,
    }
