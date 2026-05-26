"""
Pipeline: Load Excel Neptune (X5).

Orchestrates the full X5 pipeline:
1. Load linked graph data from X4 outputs
2. Generate Cypher export with Excel-specific metadata
3. Validate (dry-run)
4. Optionally clear existing Neptune data and load new graph
5. Run verification queries
6. Generate reports
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_neptune_exporter import ExcelNeptuneCypherExporter
from hermes_bedrock_agent.v2.excel.excel_neptune_loader import ExcelNeptuneLoader
from hermes_bedrock_agent.v2.excel.excel_neptune_load_reporter import ExcelNeptuneLoadReporter
from hermes_bedrock_agent.v2.graph.neptune_loader import NeptuneLoaderConfig

logger = logging.getLogger(__name__)


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
    run_id: str = "sample_20260519_excel_v1",
    dataset: str = "sample_20260519",
    layer: str = "all",
    dry_run: bool = True,
    execute: bool = False,
    clear_before_load: bool = False,
    cypher_output_path: str | None = None,
    neptune_graph_id: str = "",
    neptune_region: str = "ap-northeast-1",
    batch_size: int = 50,
    delay: float = 3.0,
) -> dict[str, Any]:
    """Execute the full X5 Excel Neptune pipeline."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Default Cypher output path
    if cypher_output_path is None:
        if layer == "all":
            cypher_output_path = str(output_dir / "load_neptune.cypher")
        else:
            cypher_output_path = str(output_dir / f"load_neptune_{layer}.cypher")

    # ======================================================================
    # Phase 1: Load inputs
    # ======================================================================
    print("[X5] Loading inputs...")
    linked_nodes = load_jsonl(output_dir / "graph_nodes_linked.jsonl")
    linked_edges = load_jsonl(output_dir / "graph_edges_linked.jsonl")
    evidence_links = load_jsonl(output_dir / "evidence_links.jsonl")

    # Try reviewed chunks first, fall back to base chunks
    evidence_chunks_path = output_dir / "evidence_chunks_reviewed.jsonl"
    if not evidence_chunks_path.exists():
        evidence_chunks_path = output_dir / "evidence_chunks.jsonl"
    evidence_chunks = load_jsonl(evidence_chunks_path)

    print(f"  Linked nodes: {len(linked_nodes)}")
    print(f"  Linked edges: {len(linked_edges)}")
    print(f"  Evidence links: {len(evidence_links)}")
    print(f"  Evidence chunks: {len(evidence_chunks)}")
    print(f"  Layer filter: {layer}")

    if not linked_nodes:
        raise RuntimeError(
            f"No linked nodes found at {output_dir / 'graph_nodes_linked.jsonl'}. "
            f"Run X4 first."
        )

    # ======================================================================
    # Phase 2: Generate Cypher with Excel-specific metadata
    # ======================================================================
    print("\n[X5] Generating Cypher export...")
    exporter = ExcelNeptuneCypherExporter(
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

    # ======================================================================
    # Phase 3: Neptune Loader setup
    # ======================================================================
    loader_config = NeptuneLoaderConfig(
        graph_id=neptune_graph_id,
        region=neptune_region,
        execute=execute,
        clear_before_load=clear_before_load,
        batch_size=batch_size,
        delay_between_batches_s=delay,
    )
    loader = ExcelNeptuneLoader(loader_config, run_id=run_id, dataset=dataset)
    config_validation = loader.validate_config()

    print(f"\n[X5] Neptune config:")
    print(f"  Graph ID: {config_validation['graph_id']}")
    print(f"  Region: {config_validation['region']}")
    print(f"  Configured: {config_validation['is_configured']}")

    # ======================================================================
    # Phase 4: Dry-run or Execute
    # ======================================================================
    queries = exporter.get_parameterized_queries()

    if execute and not dry_run:
        if not config_validation['is_configured']:
            raise RuntimeError(
                "Neptune not configured. Cannot execute load. "
                f"graph_id={neptune_graph_id!r}, region={neptune_region!r}"
            )
        if not clear_before_load:
            raise RuntimeError(
                "For Excel project load, --clear-before-load is REQUIRED "
                "to avoid mixing with existing graph data."
            )

        print(f"\n[X5] EXECUTING Neptune clear + load...")
        print(f"  Total queries: {len(queries)}")
        print(f"  Batch size: {batch_size}")
        print(f"  Delay between batches: {delay}s")

        start_time = time.time()
        loader_stats = loader.execute_load(queries)
        elapsed = time.time() - start_time

        print(f"  Executed: {loader_stats['statements_executed']}")
        print(f"  Failed: {loader_stats['statements_failed']}")
        print(f"  Cleared: {loader_stats['cleared']}")
        print(f"  Time: {elapsed:.1f}s")

        # Run verification
        print(f"\n[X5] Running verification queries...")
        verification_results = loader.verify_load()
        for vr in verification_results:
            name = vr.get('query_name', '')
            if vr.get('success'):
                results_data = vr.get('result', {}).get('results', [])
                if results_data and len(results_data) == 1 and 'cnt' in results_data[0]:
                    print(f"  ✅ {name}: {results_data[0]['cnt']}")
                elif results_data:
                    print(f"  ✅ {name}: {len(results_data)} results")
                else:
                    print(f"  ✅ {name}: (empty)")
            else:
                print(f"  ❌ {name}: {vr.get('error', 'failed')[:80]}")
    else:
        print(f"\n[X5] Running dry-run validation...")
        loader_stats = loader.dry_run(queries)
        verification_results = []
        print(f"  Statements validated: {loader_stats['statements_total']}")
        print(f"  Valid: {loader_stats.get('valid', True)}")
        val_errors = loader_stats.get('validation_errors', [])
        if val_errors:
            print(f"  ⚠️ Validation errors: {len(val_errors)}")
            for e in val_errors[:5]:
                print(f"    - {e}")

    # ======================================================================
    # Phase 5: Generate reports
    # ======================================================================
    print(f"\n[X5] Generating reports...")
    reporter = ExcelNeptuneLoadReporter(
        export_stats=export_stats,
        loader_stats=loader_stats,
        config_validation=config_validation,
        verification_results=verification_results,
        cypher_output_path=cypher_output_path,
        run_id=run_id,
        dataset=dataset,
    )

    # Main load report
    load_report = reporter.generate_load_report()
    load_report_path = output_dir / "neptune_load_report.md"
    load_report_path.write_text(load_report, encoding="utf-8")
    print(f"  → neptune_load_report.md")

    # Validation report
    validation_report = reporter.generate_validation_report()
    validation_report_path = output_dir / "neptune_load_validation_report.md"
    validation_report_path.write_text(validation_report, encoding="utf-8")
    print(f"  → neptune_load_validation_report.md")

    # ======================================================================
    # Done
    # ======================================================================
    mode = "execute" if (execute and not dry_run) else "dry_run"
    print(f"\n[X5] COMPLETE (mode={mode})")
    print(f"  Cypher: {cypher_output_path}")
    print(f"  Total statements: {export_stats['total_statements']}")
    if mode == "dry_run":
        print(f"  ℹ️  No actual Neptune writes performed.")
        print(f"  To execute: add --execute --clear-before-load")

    return {
        "mode": mode,
        "export_stats": export_stats,
        "loader_stats": loader_stats,
        "config_validation": config_validation,
        "verification_results": verification_results,
        "cypher_output_path": cypher_output_path,
    }
