"""Graph pipeline public API — v3.1 semantic map extraction.

Usage (Python):
    from hermes_bedrock_agent.graph_pipeline import run_pipeline, GraphPipelineConfig

    cfg = GraphPipelineConfig(
        project_id="sample_20260519",
        project_name="サンプル20260519",
        dry_run=True,
    )
    result = run_pipeline("outputs/サンプル20260519", cfg)
    print(result.summary)

Usage (CLI):
    dualrag graph outputs/サンプル20260519 --project-id sample_20260519 --dry-run
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ..clients.bedrock import make_bedrock_client
from ..clients.neptune import NeptuneClient
from ._utils import normalize_id
from .config import GraphPipelineConfig
from .cypher_gen import generate_cypher, generate_jsonl, write_cypher_file
from .display import build_display_graph, generate_review_tasks
from .evidence import split_evidence_units
from .extractor import extract_from_markdown
from .loader import run_load
from .normalizer import normalize_entities, save_registry
from .report import generate_extraction_report, generate_graph_explore_queries
from .scanner import scan_markdown_files
from .schemas import PipelineEdge, PipelineNode, PipelineResult
from .structure import build_cross_document_links, build_sheet_id_map, build_structure_layer
from .validator import post_load_verify, run_preflight_check

logger = logging.getLogger(__name__)

__all__ = ["run_pipeline", "GraphPipelineConfig", "PipelineResult"]


def _resolve_input_dirs(project_dir: Path) -> list[str]:
    """Find all vlm_parsed/ directories under project_dir."""
    dirs = [str(d) for d in project_dir.rglob("vlm_parsed") if d.is_dir()]
    if not dirs:
        # Fallback: use project_dir itself
        dirs = [str(project_dir)]
    return dirs


def _as_pipeline_node(d: dict) -> PipelineNode:
    """Convert a plain dict to a PipelineNode, tolerating extra/missing fields."""
    safe = {
        "id": d.get("id", ""),
        "labels": d.get("labels", d.get("entity_type", "Entity")),
        "name": d.get("name", d.get("display_name", d.get("id", ""))),
        "display_name": d.get("display_name", d.get("name", "")),
        "description": d.get("description", ""),
        "project_name": d.get("project_name", ""),
        "project_id": d.get("project_id", ""),
        "workbook_name": d.get("workbook_name", ""),
        "sheet_name": d.get("sheet_name", ""),
        "sheet_type": d.get("sheet_type", ""),
        "source_file": d.get("source_file", ""),
        "evidence_text": d.get("evidence_text", ""),
        "confidence": float(d.get("confidence", 0.75)),
        "review_status": d.get("review_status", "pending"),
        "view_scope": d.get("view_scope", "core"),
        "entity_type": d.get("entity_type", "Unknown"),
        "layer": d.get("layer", "project"),
        "category": d.get("category", ""),
        "importance": int(d.get("importance", 1)),
        "flow_node_kind": d.get("flow_node_kind", ""),
        "parent_function_id": d.get("parent_function_id", ""),
        "sequence_no": str(d.get("sequence_no", "")),
        "properties_text": d.get("properties_text", ""),
        "aliases_text": d.get("aliases_text", ""),
    }
    # clamp confidence
    safe["confidence"] = max(0.0, min(1.0, safe["confidence"]))
    # validate literals
    if safe["review_status"] not in ("verified", "pending", "rejected"):
        safe["review_status"] = "pending"
    if safe["view_scope"] not in ("core", "detail", "evidence"):
        safe["view_scope"] = "core"
    return PipelineNode(**safe)


def _as_pipeline_edge(d: dict) -> PipelineEdge:
    """Convert a plain dict to a PipelineEdge, tolerating extra/missing fields."""
    safe = {
        "id": d.get("id", ""),
        "start_id": d.get("start_id", ""),
        "end_id": d.get("end_id", ""),
        "type": d.get("type", "RELATED_TO"),
        "project_name": d.get("project_name", ""),
        "project_id": d.get("project_id", ""),
        "source_file": d.get("source_file", ""),
        "evidence_text": d.get("evidence_text", ""),
        "confidence": float(d.get("confidence", 0.75)),
        "review_status": d.get("review_status", "pending"),
        "view_scope": d.get("view_scope", "core"),
        "link_method": d.get("link_method", "explicit_text"),
        "layer": d.get("layer", "project"),
        "edge_label": d.get("edge_label", ""),
        "condition_text": d.get("condition_text", ""),
        "branch_label": d.get("branch_label", ""),
        "sequence_no": str(d.get("sequence_no", "")),
    }
    safe["confidence"] = max(0.0, min(1.0, safe["confidence"]))
    if safe["review_status"] not in ("verified", "pending", "rejected"):
        safe["review_status"] = "pending"
    if safe["view_scope"] not in ("core", "detail", "evidence"):
        safe["view_scope"] = "core"
    return PipelineEdge(**safe)


def run_pipeline(
    project_dir: str | Path,
    cfg: GraphPipelineConfig,
) -> PipelineResult:
    """Run the complete v3.1 graph extraction and loading pipeline.

    Phases:
      0. Scan markdown inventory
      1. Split evidence units
      2. LLM two-pass extraction (nodes then edges)
      3. Normalize and deduplicate (ID registry)
      4. Build project/workbook/sheet structure layer
      5. Cross-document link generation
      6. Review task generation
      7. Display graph filter
      8. Save JSONL outputs
      9. Preflight validation
     10. Cypher generation
     11. Graph Explore query generation
     12. Extraction report
     13. Neptune load (unless dry_run / skip_load)

    Returns a PipelineResult with summary statistics and output file paths.
    """
    project_dir = Path(project_dir).resolve()
    output_dir = cfg.resolve_output_dir(project_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / ".cache"
    cache_dir.mkdir(exist_ok=True)

    result = PipelineResult(
        project_id=cfg.project_id,
        project_name=cfg.project_name,
        output_dir=str(output_dir),
    )

    logger.info("═══ Semantic Map v3.1 Pipeline ═══")
    logger.info("Project: %s (%s)", cfg.project_name or "(auto)", cfg.project_id or "(auto)")
    logger.info("Output dir: %s", output_dir)

    # ── Phase 0: Scan ─────────────────────────────────────────────────────────
    logger.info("Phase 0: Scanning markdown files...")
    input_dirs = _resolve_input_dirs(project_dir)
    project_name = cfg.project_name or project_dir.name
    project_id = cfg.project_id or normalize_id(project_dir.name)

    # Update cfg fields so downstream callers get the resolved values
    cfg.project_name = project_name
    cfg.project_id = project_id
    result.project_name = project_name
    result.project_id = project_id

    inventory = scan_markdown_files(project_id, project_name, input_dirs)
    logger.info("  Found %d markdown files", len(inventory))

    (output_dir / "semantic_map_00_markdown_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not inventory:
        logger.warning("No markdown files found — pipeline complete (nothing to do)")
        return result

    # ── Phase 1: Evidence units ───────────────────────────────────────────────
    logger.info("Phase 1: Splitting evidence units...")
    evidence_units = split_evidence_units(inventory, project_id, project_name)
    logger.info("  Generated %d evidence units", len(evidence_units))

    with open(output_dir / "semantic_map_01_evidence_units.jsonl", "w", encoding="utf-8") as f:
        for eu in evidence_units:
            f.write(json.dumps(eu, ensure_ascii=False) + "\n")

    # ── Phase 2: LLM extraction ───────────────────────────────────────────────
    logger.info("Phase 2: LLM-based semantic extraction...")

    project_sheet_summary = "\n".join(
        f"- {f['workbook_name']}/{f['sheet_name']} ({f['sheet_type']})"
        for f in inventory if f["read_status"] == "success"
    )

    bedrock_client = make_bedrock_client(region=cfg.aws_region)

    processable = [
        f for f in inventory
        if f["read_status"] == "success" and f["content_length"] >= 100
    ]
    logger.info("  Processing %d files...", len(processable))

    all_raw_nodes: list[dict] = []
    all_raw_edges: list[dict] = []

    for idx, file_rec in enumerate(processable):
        logger.info(
            "  [%d/%d] %s/%s (%s)",
            idx + 1, len(processable),
            file_rec["workbook_name"], file_rec["sheet_name"], file_rec["sheet_type"],
        )
        nodes, edges = extract_from_markdown(
            file_rec, cfg, project_sheet_summary, bedrock_client, cache_dir
        )
        all_raw_nodes.extend(nodes)
        all_raw_edges.extend(edges)
        logger.info("    -> %d nodes, %d edges", len(nodes), len(edges))
        time.sleep(cfg.llm_delay_seconds)

    logger.info(
        "  Total raw extraction: %d nodes, %d edges",
        len(all_raw_nodes), len(all_raw_edges),
    )

    # ── Phase 3: Normalization ────────────────────────────────────────────────
    logger.info("Phase 3: Normalizing and building ID registry...")
    normalized_nodes, normalized_edges, registry = normalize_entities(
        all_raw_nodes, all_raw_edges, project_id, project_name
    )
    save_registry(registry, output_dir / "semantic_map_02_id_registry.json")

    # ── Phase 4: Structure layer ──────────────────────────────────────────────
    logger.info("Phase 4: Building structure layer...")
    struct_nodes, struct_edges = build_structure_layer(inventory, project_id, project_name)

    all_nodes = struct_nodes + normalized_nodes
    all_edges = struct_edges + normalized_edges

    # EXTRACTED_OBJECT links: sheet → semantic node
    sheet_id_map = build_sheet_id_map(inventory, project_id)
    link_counter = len(all_edges)
    sheet_node_ids = {n["id"] for n in struct_nodes if n.get("entity_type") == "Sheet"}
    for node in normalized_nodes:
        source_file = node.get("source_file", "")
        sheet_id = sheet_id_map.get(source_file)
        if sheet_id and sheet_id in sheet_node_ids:
            link_counter += 1
            all_edges.append({
                "id": f"rel:{project_id}:extracted_{link_counter:06d}",
                "start_id": sheet_id,
                "end_id": node["id"],
                "type": "EXTRACTED_OBJECT",
                "project_name": project_name,
                "project_id": project_id,
                "source_file": source_file,
                "evidence_id": node.get("evidence_id", ""),
                "evidence_text": "Extracted from sheet",
                "link_method": "structural",
                "confidence": 1.0,
                "review_status": "verified",
                "layer": "evidence",
            })

    # ── Phase 5: Cross-document linking ──────────────────────────────────────
    logger.info("Phase 5: Building cross-document links...")
    candidate_links = build_cross_document_links(normalized_nodes, all_edges, project_id, project_name)
    logger.info("  Generated %d candidate links", len(candidate_links))

    with open(output_dir / "semantic_map_11_candidate_links.jsonl", "w", encoding="utf-8") as f:
        for link in candidate_links:
            f.write(json.dumps(link, ensure_ascii=False) + "\n")

    for link in candidate_links:
        if link.get("confidence", 0) >= 0.70:
            link_counter += 1
            link["id"] = f"rel:{project_id}:cross_{link_counter:06d}"
            all_edges.append(link)

    # ── Phase 6: Review tasks ────────────────────────────────────────────────
    logger.info("Phase 6: Generating review tasks...")
    review_tasks = generate_review_tasks(all_nodes, all_edges, inventory, project_id, project_name)
    logger.info("  Generated %d review tasks", len(review_tasks))

    with open(output_dir / "semantic_map_13_review_tasks.jsonl", "w", encoding="utf-8") as f:
        for task in review_tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")

    # ── Phase 7: Display graph ────────────────────────────────────────────────
    logger.info("Phase 7: Building display graph...")
    display_nodes, display_edges = build_display_graph(all_nodes, all_edges)
    logger.info("  Display graph: %d nodes, %d edges", len(display_nodes), len(display_edges))

    # ── Phase 8: JSONL outputs ────────────────────────────────────────────────
    logger.info("Phase 8: Saving JSONL outputs...")

    def _write_jsonl(path: Path, items: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as fh:
            for item in items:
                fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    semantic_nodes = [n for n in all_nodes if n.get("layer") not in ("project", "evidence")]
    semantic_edges = [e for e in all_edges if e.get("layer") not in ("project", "evidence")]
    evidence_nodes = [n for n in all_nodes if n.get("layer") in ("project", "evidence")]
    evidence_edges = [e for e in all_edges if e.get("layer") in ("project", "evidence")]

    _write_jsonl(output_dir / "semantic_map_03_semantic_nodes.jsonl", semantic_nodes)
    _write_jsonl(output_dir / "semantic_map_04_semantic_edges.jsonl", semantic_edges)
    _write_jsonl(output_dir / "semantic_map_05_evidence_nodes.jsonl", evidence_nodes)
    _write_jsonl(output_dir / "semantic_map_06_evidence_edges.jsonl", evidence_edges)
    _write_jsonl(output_dir / "semantic_map_nodes_full.jsonl", all_nodes)
    _write_jsonl(output_dir / "semantic_map_edges_full.jsonl", all_edges)
    _write_jsonl(output_dir / "semantic_map_nodes_display.jsonl", display_nodes)
    _write_jsonl(output_dir / "semantic_map_edges_display.jsonl", display_edges)

    (output_dir / "semantic_map_14_full_graph.json").write_text(
        json.dumps({
            "nodes": all_nodes, "edges": all_edges,
            "metadata": {
                "project_name": project_name, "project_id": project_id,
                "node_count": len(all_nodes), "edge_count": len(all_edges),
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "semantic_map_15_display_graph.json").write_text(
        json.dumps({
            "nodes": display_nodes, "edges": display_edges,
            "metadata": {
                "project_name": project_name, "project_id": project_id,
                "node_count": len(display_nodes), "edge_count": len(display_edges),
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── Phase 9: Preflight check ──────────────────────────────────────────────
    logger.info("Phase 9: Running preflight check...")
    preflight_report, has_p0 = run_preflight_check(
        all_nodes, all_edges, display_nodes, display_edges,
        project_id, project_name, inventory,
    )
    (output_dir / "semantic_map_preflight_check.md").write_text(preflight_report, encoding="utf-8")

    if has_p0:
        logger.error("❌ P0 issues found — auto-fixing dangling edges before Cypher generation")
        node_ids = {n["id"] for n in all_nodes}
        all_edges = [
            e for e in all_edges
            if e.get("start_id") in node_ids and e.get("end_id") in node_ids
        ]
        display_node_ids = {n["id"] for n in display_nodes}
        display_edges = [
            e for e in display_edges
            if e.get("start_id") in display_node_ids and e.get("end_id") in display_node_ids
        ]
        preflight_report, has_p0 = run_preflight_check(
            all_nodes, all_edges, display_nodes, display_edges,
            project_id, project_name, inventory,
        )
        (output_dir / "semantic_map_preflight_check.md").write_text(preflight_report, encoding="utf-8")

    if has_p0:
        result.validation_errors = ["P0 issues remain after auto-fix — inspect preflight_check.md"]
    result.has_p0 = has_p0

    # ── Phase 10: Cypher generation ───────────────────────────────────────────
    logger.info("Phase 10: Generating Neptune openCypher scripts...")
    write_cypher_file(display_nodes, display_edges,
                      output_dir / "semantic_map_import_display.cypher", "display")
    write_cypher_file(all_nodes, all_edges,
                      output_dir / "semantic_map_import_full.cypher", "full")

    # Also write the named Cypher files used by run_load via generate_cypher
    nodes_cypher, edges_cypher = generate_cypher(all_nodes, all_edges, output_dir, project_id)
    result_nodes_jsonl, result_edges_jsonl = generate_jsonl(all_nodes, all_edges, output_dir, project_id)

    # ── Phase 11: Graph Explore queries ──────────────────────────────────────
    logger.info("Phase 11: Generating Graph Explore queries...")
    generate_graph_explore_queries(
        project_id, project_name,
        output_dir / "semantic_map_graph_explore_queries.cypher",
    )

    # ── Phase 12: Extraction report ───────────────────────────────────────────
    logger.info("Phase 12: Generating extraction report...")
    report = generate_extraction_report(
        project_id=project_id,
        project_name=project_name,
        input_dirs=input_dirs,
        output_dir=str(output_dir),
        neptune_endpoint=cfg.neptune_graph_id or "",
        inventory=inventory,
        evidence_units=evidence_units,
        nodes=all_nodes,
        edges=all_edges,
        display_nodes=display_nodes,
        display_edges=display_edges,
        candidate_links=candidate_links,
        review_tasks=review_tasks,
    )
    (output_dir / "semantic_map_extraction_report.md").write_text(report, encoding="utf-8")

    # ── Phase 13: Neptune load ────────────────────────────────────────────────
    skip = cfg.dry_run or cfg.skip_load
    logger.info("Phase 13: Loading into Neptune%s", " [DRY RUN]" if skip else "")

    # Convert dicts to PipelineNode/PipelineEdge for the typed loader
    pipeline_nodes = [_as_pipeline_node(n) for n in all_nodes]
    pipeline_edges = [_as_pipeline_edge(e) for e in all_edges]

    load_stats = run_load(
        nodes=pipeline_nodes,
        edges=pipeline_edges,
        neptune_graph_id=cfg.neptune_graph_id,
        aws_region=cfg.aws_region,
        delay_seconds=0.1,
        dry_run=skip,
    )
    result.load_stats = load_stats

    if not skip and not load_stats.get("error"):
        logger.info("Post-load verification")
        client = NeptuneClient(graph_id=cfg.neptune_graph_id, region=cfg.aws_region)
        verify_stats = post_load_verify(
            client=client,
            project_id=project_id,
            expected_nodes=len(all_nodes),
            expected_edges=len(all_edges),
        )
        result.load_stats["verification"] = verify_stats

    # ── Populate result ───────────────────────────────────────────────────────
    result.nodes = pipeline_nodes
    result.edges = pipeline_edges
    result.files_processed = len(processable)
    result.display_nodes_count = len(display_nodes)
    result.display_edges_count = len(display_edges)
    result.candidate_links_count = len(candidate_links)
    result.review_tasks_count = len(review_tasks)

    # Save pipeline summary
    summary_path = output_dir / f"{project_id}_pipeline_summary.json"
    summary_path.write_text(
        json.dumps(result.summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info("═══ Pipeline Complete ═══")
    logger.info(
        "  Files: %d | Nodes: %d | Edges: %d | Display: %d/%d",
        len(processable), len(all_nodes), len(all_edges),
        len(display_nodes), len(display_edges),
    )
    logger.info("  Output dir: %s", output_dir)

    return result
