"""Import experiment chunking/graph outputs into LanceDB and Neptune.

Reads completed experiment outputs from chunk_graph_eval runs and:
  - Embeds chunks via Bedrock Titan Embed V2 → LanceDB table (experiment-isolated)
  - Imports graph nodes/edges → Neptune Analytics (prefixed IDs for isolation)
  - Validates counts and isolation after import
  - Generates structured import reports
"""

from __future__ import annotations

import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import boto3
import pyarrow as pa

import lancedb

from ..clients.neptune import NeptuneClient, NeptuneClientError
from ..config import Config, config as _default_config

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1024
EXPERIMENT_TABLE = "dualrag_experiment_eval_chunks"


def _experiment_lancedb_schema() -> pa.Schema:
    return pa.schema([
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("embedding", pa.list_(pa.float32(), EMBEDDING_DIM)),
        pa.field("chunk_type", pa.string()),
        pa.field("source_file", pa.string()),
        pa.field("source_type", pa.string()),
        pa.field("parser_type", pa.string()),
        pa.field("document_role", pa.string()),
        pa.field("sheet_index", pa.int32()),
        pa.field("sheet_name", pa.string()),
        pa.field("workbook_name", pa.string()),
        pa.field("project_id", pa.string()),
        pa.field("experiment_project_id", pa.string()),
        pa.field("source_project_id", pa.string()),
        pa.field("source_project_key", pa.string()),
        pa.field("chunk_run_id", pa.string()),
        pa.field("graph_run_id", pa.string()),
        pa.field("chunking_strategy", pa.string()),
        pa.field("graph_prompt_version", pa.string()),
        pa.field("chunk_index", pa.int32()),
        pa.field("section_title", pa.string()),
        pa.field("page_index", pa.int32()),
        pa.field("evidence_paths", pa.string()),
        pa.field("parsed_markdown_path", pa.string()),
        pa.field("created_at", pa.string()),
    ])


@dataclass
class ImportConfig:
    experiment_dir: Path = field(default_factory=lambda: Path("outputs/experiments/chunk_graph_eval"))
    target: str = "all"
    lancedb_write: bool = True
    neptune_import: bool = True
    replace_experiment: bool = False
    validate_only: bool = False
    delay_seconds: float = 0.05
    batch_size: int = 25
    lancedb_path: str = ""
    neptune_graph_id: str = ""
    aws_region: str = "ap-northeast-1"
    embed_model_id: str = "amazon.titan-embed-text-v2:0"


@dataclass
class ImportReport:
    experiment_project_id: str = ""
    source_project_key: str = ""
    chunking_strategy: str = ""
    graph_prompt_version: str = ""
    lancedb_table: str = EXPERIMENT_TABLE
    neptune_graph_id: str = ""
    chunks_imported: int = 0
    embeddings_generated: int = 0
    embedding_errors: int = 0
    nodes_imported: int = 0
    edges_imported: int = 0
    node_errors: int = 0
    edge_errors: int = 0
    import_mode: str = "fail-if-exists"
    started_at: str = ""
    completed_at: str = ""
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@dataclass
class ValidationReport:
    experiment_project_id: str = ""
    lancedb_count_match: bool = False
    lancedb_expected: int = 0
    lancedb_actual: int = 0
    neptune_node_count_match: bool = False
    neptune_node_expected: int = 0
    neptune_node_actual: int = 0
    neptune_edge_count_match: bool = False
    neptune_edge_expected: int = 0
    neptune_edge_actual: int = 0
    neptune_cross_boundary_edges: int = -1
    retrieval_isolation_verified: bool = False
    validated_at: str = ""


def _embed_text(client, model_id: str, text: str) -> list[float]:
    body = json.dumps({"inputText": text, "dimensions": EMBEDDING_DIM, "normalize": True})
    response = client.invoke_model(
        modelId=model_id, body=body,
        contentType="application/json", accept="application/json",
    )
    return json.loads(response["body"].read())["embedding"]


def _escape_cypher_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _load_manifest(experiment_dir: Path) -> dict:
    manifest_path = experiment_dir / "experiment_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _check_lancedb_exists(db_path: str, table_name: str, experiment_project_id: str) -> int:
    db = lancedb.connect(db_path)
    if table_name not in db.table_names():
        return 0
    table = db.open_table(table_name)
    return table.count_rows(f"project_id = '{experiment_project_id}'")


def _check_neptune_exists(neptune: NeptuneClient, experiment_project_id: str) -> int:
    try:
        result = neptune.execute_query(
            "MATCH (n {project_id: $pid}) RETURN count(n) AS cnt",
            parameters={"pid": experiment_project_id},
        )
        results = result.get("results", [])
        if results:
            return results[0].get("cnt", 0)
        return 0
    except NeptuneClientError:
        return 0


def _delete_lancedb_experiment(db_path: str, table_name: str, experiment_project_id: str) -> None:
    db = lancedb.connect(db_path)
    if table_name in db.table_names():
        table = db.open_table(table_name)
        table.delete(f"project_id = '{experiment_project_id}'")
        logger.info("Deleted LanceDB rows for %s", experiment_project_id)


def _delete_neptune_experiment(neptune: NeptuneClient, experiment_project_id: str) -> None:
    try:
        neptune.execute_query(
            "MATCH (n {project_id: $pid}) DETACH DELETE n",
            parameters={"pid": experiment_project_id},
        )
        logger.info("Deleted Neptune nodes/edges for %s", experiment_project_id)
    except NeptuneClientError as e:
        logger.warning("Failed to delete Neptune data for %s: %s", experiment_project_id, e)


def import_lancedb(
    experiment: dict,
    chunks: list[dict],
    manifest: dict,
    icfg: ImportConfig,
) -> ImportReport:
    """Import chunks into LanceDB experiment table."""
    exp_id = experiment["experiment_project_id"]
    source_display = manifest["source_projects"][experiment["source_project_key"]]["display_name"]

    report = ImportReport(
        experiment_project_id=exp_id,
        source_project_key=experiment["source_project_key"],
        chunking_strategy=experiment["chunking_strategy"],
        graph_prompt_version=experiment["graph_prompt_version"],
        lancedb_table=EXPERIMENT_TABLE,
        import_mode="replace" if icfg.replace_experiment else "fail-if-exists",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    db_path = icfg.lancedb_path or _default_config.lancedb_path
    db = lancedb.connect(db_path)

    if EXPERIMENT_TABLE in db.table_names():
        table = db.open_table(EXPERIMENT_TABLE)
    else:
        table = db.create_table(EXPERIMENT_TABLE, schema=_experiment_lancedb_schema())

    bedrock = boto3.client("bedrock-runtime", region_name=icfg.aws_region)
    rows: list[dict] = []
    errors = 0

    for i, chunk in enumerate(chunks):
        text = chunk.get("content", "")
        if not text.strip():
            report.warnings.append(f"Empty content for chunk {chunk.get('chunk_id', i)}")
            errors += 1
            continue

        try:
            embedding = _embed_text(bedrock, icfg.embed_model_id, text)
        except Exception as exc:
            errors += 1
            report.warnings.append(f"Embedding failed for chunk {chunk.get('chunk_id', '')}: {exc}")
            logger.warning("Embedding failed for chunk %d: %s", i, exc)
            if errors > len(chunks) * 0.1:
                report.errors.append("Aborted: >10% embedding failures")
                report.completed_at = datetime.now(timezone.utc).isoformat()
                return report
            continue

        chunk_id = chunk.get("chunk_id", f"chunk_{i}")
        row = {
            "id": f"{exp_id}::{chunk_id}",
            "text": text,
            "embedding": embedding,
            "chunk_type": chunk.get("chunking_strategy", "text"),
            "source_file": chunk.get("source_file", ""),
            "source_type": chunk.get("source_type", ""),
            "parser_type": chunk.get("parser_type", ""),
            "document_role": chunk.get("document_role", ""),
            "sheet_index": chunk.get("sheet_index", 0),
            "sheet_name": chunk.get("sheet_name", ""),
            "workbook_name": chunk.get("workbook_name", ""),
            "project_id": exp_id,
            "experiment_project_id": exp_id,
            "source_project_id": source_display,
            "source_project_key": chunk.get("source_project_key", ""),
            "chunk_run_id": chunk.get("chunk_run_id", ""),
            "graph_run_id": chunk.get("graph_run_id", ""),
            "chunking_strategy": chunk.get("chunking_strategy", ""),
            "graph_prompt_version": chunk.get("graph_prompt_version", ""),
            "chunk_index": chunk.get("chunk_index", 0),
            "section_title": chunk.get("section_title", ""),
            "page_index": chunk.get("page_index", 0),
            "evidence_paths": json.dumps(chunk.get("evidence_paths", []), ensure_ascii=False),
            "parsed_markdown_path": chunk.get("parsed_markdown_path", ""),
            "created_at": chunk.get("created_at", ""),
        }
        rows.append(row)
        report.embeddings_generated += 1

        if len(rows) >= icfg.batch_size:
            table.add(rows)
            logger.info(
                "[%s] LanceDB batch %d/%d (errors: %d)",
                exp_id, i + 1, len(chunks), errors,
            )
            rows = []

        if icfg.delay_seconds > 0:
            time.sleep(icfg.delay_seconds)

    if rows:
        table.add(rows)

    report.chunks_imported = report.embeddings_generated
    report.embedding_errors = errors
    report.completed_at = datetime.now(timezone.utc).isoformat()
    logger.info(
        "[%s] LanceDB import complete: %d chunks, %d errors",
        exp_id, report.chunks_imported, errors,
    )
    return report


def import_neptune(
    experiment: dict,
    nodes: list[dict],
    edges: list[dict],
    icfg: ImportConfig,
) -> ImportReport:
    """Import graph nodes/edges into Neptune with prefixed IDs."""
    exp_id = experiment["experiment_project_id"]
    graph_id = icfg.neptune_graph_id or _default_config.neptune_graph_id

    report = ImportReport(
        experiment_project_id=exp_id,
        source_project_key=experiment["source_project_key"],
        chunking_strategy=experiment["chunking_strategy"],
        graph_prompt_version=experiment["graph_prompt_version"],
        neptune_graph_id=graph_id,
        import_mode="replace" if icfg.replace_experiment else "fail-if-exists",
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    neptune = NeptuneClient(graph_id=graph_id, region=icfg.aws_region)
    if not neptune.ping():
        report.errors.append("Neptune not reachable")
        report.completed_at = datetime.now(timezone.utc).isoformat()
        return report

    node_errors = 0
    for i, node in enumerate(nodes):
        original_id = node.get("id", "")
        prefixed_id = f"{exp_id}::{original_id}"
        label = node.get("entity_type", "Entity")
        # Sanitize label for Cypher (remove spaces, special chars)
        label = label.replace(" ", "_").replace("-", "_")

        props = {
            "name": node.get("name", ""),
            "display_name": node.get("display_name", ""),
            "description": node.get("description", ""),
            "project_id": exp_id,
            "experiment_project_id": exp_id,
            "source_project_key": node.get("source_project_key", ""),
            "chunk_run_id": node.get("chunk_run_id", ""),
            "graph_run_id": node.get("graph_run_id", ""),
            "chunking_strategy": node.get("chunking_strategy", ""),
            "graph_prompt_version": node.get("graph_prompt_version", ""),
            "source_chunk_ids": node.get("source_chunk_ids", ""),
            "source_file": node.get("source_file", ""),
            "layer": node.get("layer", ""),
            "category": node.get("category", ""),
        }

        # Build SET clause with parameterized values where possible
        # Neptune openCypher doesn't support dynamic labels in MERGE, so label is interpolated
        set_parts = []
        for k, v in props.items():
            escaped = _escape_cypher_string(str(v)) if v else ""
            set_parts.append(f"n.{k} = '{escaped}'")
        set_clause = ", ".join(set_parts)

        node_id_esc = _escape_cypher_string(prefixed_id)
        pid_esc = _escape_cypher_string(exp_id)

        cypher = (
            f"MERGE (n:{label} {{node_id: '{node_id_esc}', project_id: '{pid_esc}'}}) "
            f"ON CREATE SET {set_clause} "
            f"ON MATCH SET {set_clause}"
        )

        try:
            neptune.execute_query(cypher)
        except NeptuneClientError as exc:
            node_errors += 1
            if node_errors <= 10:
                report.warnings.append(f"Node MERGE failed [{original_id}]: {exc}")
            logger.warning("Node MERGE failed [%s]: %s", original_id, exc)
            if node_errors > len(nodes) * 0.1:
                report.errors.append("Aborted: >10% node MERGE failures")
                report.node_errors = node_errors
                report.completed_at = datetime.now(timezone.utc).isoformat()
                return report

        if (i + 1) % 100 == 0:
            logger.info("[%s] Neptune nodes: %d/%d (errors: %d)", exp_id, i + 1, len(nodes), node_errors)

        if icfg.delay_seconds > 0 and icfg.delay_seconds >= 0.01:
            time.sleep(0.01)

    report.nodes_imported = len(nodes) - node_errors
    report.node_errors = node_errors
    logger.info("[%s] Neptune nodes complete: %d imported, %d errors", exp_id, report.nodes_imported, node_errors)

    # Import edges
    edge_errors = 0
    for i, edge in enumerate(edges):
        from_id = f"{exp_id}::{edge.get('from_id', '')}"
        to_id = f"{exp_id}::{edge.get('to_id', '')}"
        rel_type = edge.get("type", "RELATED_TO").replace(" ", "_").replace("-", "_")

        props = {
            "project_id": exp_id,
            "experiment_project_id": exp_id,
            "source_project_key": edge.get("source_project_key", ""),
            "chunk_run_id": edge.get("chunk_run_id", ""),
            "graph_run_id": edge.get("graph_run_id", ""),
            "chunking_strategy": edge.get("chunking_strategy", ""),
            "graph_prompt_version": edge.get("graph_prompt_version", ""),
            "source_chunk_ids": edge.get("source_chunk_ids", ""),
            "evidence_text": edge.get("evidence_text", ""),
            "confidence": str(edge.get("confidence", "")),
            "review_status": edge.get("review_status", ""),
            "view_scope": edge.get("view_scope", ""),
            "normalization_applied": str(edge.get("normalization_applied", False)).lower(),
        }

        set_parts = []
        for k, v in props.items():
            escaped = _escape_cypher_string(str(v)) if v else ""
            set_parts.append(f"r.{k} = '{escaped}'")
        set_clause = ", ".join(set_parts)

        from_esc = _escape_cypher_string(from_id)
        to_esc = _escape_cypher_string(to_id)
        pid_esc = _escape_cypher_string(exp_id)

        cypher = (
            f"MATCH (a {{node_id: '{from_esc}', project_id: '{pid_esc}'}}), "
            f"(b {{node_id: '{to_esc}', project_id: '{pid_esc}'}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"SET {set_clause}"
        )

        try:
            neptune.execute_query(cypher)
        except NeptuneClientError as exc:
            edge_errors += 1
            if edge_errors <= 10:
                report.warnings.append(f"Edge MERGE failed [{from_id}→{to_id}]: {exc}")
            logger.warning("Edge MERGE failed [%s→%s]: %s", from_id, to_id, exc)
            if edge_errors > len(edges) * 0.1:
                report.errors.append("Aborted: >10% edge MERGE failures")
                report.edge_errors = edge_errors
                report.completed_at = datetime.now(timezone.utc).isoformat()
                return report

        if (i + 1) % 100 == 0:
            logger.info("[%s] Neptune edges: %d/%d (errors: %d)", exp_id, i + 1, len(edges), edge_errors)

        if icfg.delay_seconds > 0 and icfg.delay_seconds >= 0.01:
            time.sleep(0.01)

    report.edges_imported = len(edges) - edge_errors
    report.edge_errors = edge_errors
    report.completed_at = datetime.now(timezone.utc).isoformat()
    logger.info(
        "[%s] Neptune import complete: %d nodes, %d edges (errors: %d/%d)",
        exp_id, report.nodes_imported, report.edges_imported, node_errors, edge_errors,
    )
    return report


def validate_experiment(
    experiment: dict,
    expected_chunks: int,
    expected_nodes: int,
    expected_edges: int,
    icfg: ImportConfig,
) -> ValidationReport:
    """Validate import counts and isolation for an experiment."""
    exp_id = experiment["experiment_project_id"]
    db_path = icfg.lancedb_path or _default_config.lancedb_path
    graph_id = icfg.neptune_graph_id or _default_config.neptune_graph_id

    report = ValidationReport(
        experiment_project_id=exp_id,
        lancedb_expected=expected_chunks,
        neptune_node_expected=expected_nodes,
        neptune_edge_expected=expected_edges,
    )

    # LanceDB validation
    if icfg.lancedb_write:
        actual_chunks = _check_lancedb_exists(db_path, EXPERIMENT_TABLE, exp_id)
        report.lancedb_actual = actual_chunks
        report.lancedb_count_match = (actual_chunks == expected_chunks)
        if not report.lancedb_count_match:
            logger.warning(
                "[%s] LanceDB count mismatch: expected %d, got %d",
                exp_id, expected_chunks, actual_chunks,
            )

    # Neptune validation
    if icfg.neptune_import:
        neptune = NeptuneClient(graph_id=graph_id, region=icfg.aws_region)
        if neptune.ping():
            # Node count
            result = neptune.execute_query(
                "MATCH (n {project_id: $pid}) RETURN count(n) AS cnt",
                parameters={"pid": exp_id},
            )
            actual_nodes = result.get("results", [{}])[0].get("cnt", 0)
            report.neptune_node_actual = actual_nodes
            report.neptune_node_count_match = (actual_nodes == expected_nodes)

            # Edge count
            result = neptune.execute_query(
                "MATCH ()-[r {project_id: $pid}]->() RETURN count(r) AS cnt",
                parameters={"pid": exp_id},
            )
            actual_edges = result.get("results", [{}])[0].get("cnt", 0)
            report.neptune_edge_actual = actual_edges
            report.neptune_edge_count_match = (actual_edges == expected_edges)

            # Cross-boundary check
            result = neptune.execute_query(
                "MATCH (a {project_id: $pid})-[r]->(b) WHERE b.project_id <> $pid RETURN count(r) AS cnt",
                parameters={"pid": exp_id},
            )
            report.neptune_cross_boundary_edges = result.get("results", [{}])[0].get("cnt", 0)
        else:
            logger.warning("[%s] Neptune not reachable for validation", exp_id)

    report.validated_at = datetime.now(timezone.utc).isoformat()
    return report


def verify_retrieval_isolation(
    experiment_a_id: str,
    experiment_b_id: str,
    icfg: ImportConfig,
) -> bool:
    """Verify that vector search with project_id prefilter doesn't leak across experiments."""
    from ..knowledge_base.vector_store import query_vector_store

    db_path = icfg.lancedb_path or _default_config.lancedb_path
    db = lancedb.connect(db_path)
    if EXPERIMENT_TABLE not in db.table_names():
        logger.warning("Experiment table not found for isolation check")
        return False

    table = db.open_table(EXPERIMENT_TABLE)
    # Pick a random chunk from experiment A
    rows_a = table.search().where(f"project_id = '{experiment_a_id}'", prefilter=True).limit(5).to_list()
    if not rows_a:
        logger.warning("No rows found for %s", experiment_a_id)
        return False

    sample = rows_a[0]
    sample_text = sample.get("text", "")[:200]

    # Search with experiment_a filter — should find results
    results_a = query_vector_store(
        query_text=sample_text,
        top_k=5,
        store_path=db_path,
        collection=EXPERIMENT_TABLE,
        project_id=experiment_a_id,
    )
    if not results_a:
        logger.warning("No results returned for experiment A search")
        return False

    # All results must belong to experiment A
    for r in results_a:
        if r.get("project_id") != experiment_a_id:
            logger.error("Isolation violation: result has project_id=%s (expected %s)", r.get("project_id"), experiment_a_id)
            return False

    # Search with experiment_b filter — sample from A should NOT appear
    results_b = query_vector_store(
        query_text=sample_text,
        top_k=5,
        store_path=db_path,
        collection=EXPERIMENT_TABLE,
        project_id=experiment_b_id,
    )
    for r in results_b:
        if r.get("project_id") != experiment_b_id:
            logger.error("Isolation violation in B results: project_id=%s", r.get("project_id"))
            return False

    # Check that sample chunk from A is not in B's results
    sample_id = sample.get("id", "")
    b_ids = [r.get("id", "") for r in results_b]
    if sample_id in b_ids:
        logger.error("Isolation violation: chunk %s from A found in B results", sample_id)
        return False

    logger.info("Retrieval isolation verified between %s and %s", experiment_a_id, experiment_b_id)
    return True


def _write_reports(
    experiment: dict,
    lancedb_report: Optional[ImportReport],
    neptune_report: Optional[ImportReport],
    validation: Optional[ValidationReport],
    icfg: ImportConfig,
) -> Path:
    """Write import reports to disk."""
    exp_id = experiment["experiment_project_id"]
    out_dir = icfg.experiment_dir / "imports" / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if lancedb_report:
        (out_dir / "lancedb_import_report.json").write_text(
            json.dumps({
                "experiment_project_id": lancedb_report.experiment_project_id,
                "source_project_key": lancedb_report.source_project_key,
                "chunking_strategy": lancedb_report.chunking_strategy,
                "graph_prompt_version": lancedb_report.graph_prompt_version,
                "lancedb_table": lancedb_report.lancedb_table,
                "chunks_imported": lancedb_report.chunks_imported,
                "embeddings_generated": lancedb_report.embeddings_generated,
                "embedding_errors": lancedb_report.embedding_errors,
                "import_mode": lancedb_report.import_mode,
                "started_at": lancedb_report.started_at,
                "completed_at": lancedb_report.completed_at,
                "errors": lancedb_report.errors,
                "warnings": lancedb_report.warnings[:50],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if neptune_report:
        (out_dir / "neptune_import_report.json").write_text(
            json.dumps({
                "experiment_project_id": neptune_report.experiment_project_id,
                "source_project_key": neptune_report.source_project_key,
                "chunking_strategy": neptune_report.chunking_strategy,
                "graph_prompt_version": neptune_report.graph_prompt_version,
                "neptune_graph_id": neptune_report.neptune_graph_id,
                "nodes_imported": neptune_report.nodes_imported,
                "edges_imported": neptune_report.edges_imported,
                "node_errors": neptune_report.node_errors,
                "edge_errors": neptune_report.edge_errors,
                "import_mode": neptune_report.import_mode,
                "started_at": neptune_report.started_at,
                "completed_at": neptune_report.completed_at,
                "errors": neptune_report.errors,
                "warnings": neptune_report.warnings[:50],
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if validation:
        (out_dir / "validation_report.json").write_text(
            json.dumps({
                "experiment_project_id": validation.experiment_project_id,
                "lancedb_count_match": validation.lancedb_count_match,
                "lancedb_expected": validation.lancedb_expected,
                "lancedb_actual": validation.lancedb_actual,
                "neptune_node_count_match": validation.neptune_node_count_match,
                "neptune_node_expected": validation.neptune_node_expected,
                "neptune_node_actual": validation.neptune_node_actual,
                "neptune_edge_count_match": validation.neptune_edge_count_match,
                "neptune_edge_expected": validation.neptune_edge_expected,
                "neptune_edge_actual": validation.neptune_edge_actual,
                "neptune_cross_boundary_edges": validation.neptune_cross_boundary_edges,
                "retrieval_isolation_verified": validation.retrieval_isolation_verified,
                "validated_at": validation.validated_at,
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # QA runtime config
    (out_dir / "qa_runtime_config.json").write_text(
        json.dumps({
            "experiment_project_id": exp_id,
            "qa_command": f"dualrag qa --project-id {exp_id} --collection {EXPERIMENT_TABLE}",
            "lancedb_collection": EXPERIMENT_TABLE,
            "neptune_graph_id": icfg.neptune_graph_id or _default_config.neptune_graph_id,
            "source_project_key": experiment["source_project_key"],
            "chunking_strategy": experiment["chunking_strategy"],
            "graph_prompt_version": experiment["graph_prompt_version"],
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Human-readable summary
    lines = [
        f"# Import Summary: {exp_id}",
        "",
        f"- Source: {experiment['source_project_key']} ({experiment.get('source_project_display', '')})",
        f"- Chunking: {experiment['chunking_strategy']}",
        f"- Graph prompt: {experiment['graph_prompt_version']}",
        "",
    ]
    if lancedb_report:
        lines.extend([
            "## LanceDB",
            f"- Table: {lancedb_report.lancedb_table}",
            f"- Chunks imported: {lancedb_report.chunks_imported}",
            f"- Embedding errors: {lancedb_report.embedding_errors}",
            f"- Mode: {lancedb_report.import_mode}",
            "",
        ])
    if neptune_report:
        lines.extend([
            "## Neptune",
            f"- Graph ID: {neptune_report.neptune_graph_id}",
            f"- Nodes imported: {neptune_report.nodes_imported}",
            f"- Edges imported: {neptune_report.edges_imported}",
            f"- Node errors: {neptune_report.node_errors}",
            f"- Edge errors: {neptune_report.edge_errors}",
            "",
        ])
    if validation:
        lines.extend([
            "## Validation",
            f"- LanceDB count match: {validation.lancedb_count_match}",
            f"- Neptune node match: {validation.neptune_node_count_match}",
            f"- Neptune edge match: {validation.neptune_edge_count_match}",
            f"- Cross-boundary edges: {validation.neptune_cross_boundary_edges}",
            f"- Retrieval isolation: {validation.retrieval_isolation_verified}",
            "",
        ])
    lines.extend([
        "## QA Command",
        f"```",
        f"dualrag qa --project-id {exp_id} --collection {EXPERIMENT_TABLE}",
        f"```",
    ])
    (out_dir / "import_summary.md").write_text("\n".join(lines), encoding="utf-8")

    return out_dir


def import_experiment(
    experiment: dict,
    manifest: dict,
    icfg: ImportConfig,
) -> dict[str, Any]:
    """Import a single experiment into LanceDB and/or Neptune.

    Returns a summary dict with import results.
    """
    exp_id = experiment["experiment_project_id"]
    run_dir = icfg.experiment_dir / "runs" / exp_id
    db_path = icfg.lancedb_path or _default_config.lancedb_path

    logger.info("=" * 60)
    logger.info("Importing experiment: %s", exp_id)
    logger.info("=" * 60)

    # Load data files
    chunks_path = run_dir / "chunks" / "chunks.jsonl"
    nodes_path = run_dir / "graph_output" / "nodes.jsonl"
    edges_path = run_dir / "graph_output" / "edges.jsonl"

    if not chunks_path.exists():
        logger.error("Chunks file not found: %s", chunks_path)
        return {"experiment_project_id": exp_id, "status": "error", "error": "chunks.jsonl not found"}

    chunks = _read_jsonl(chunks_path)
    nodes = _read_jsonl(nodes_path) if nodes_path.exists() else []
    edges = _read_jsonl(edges_path) if edges_path.exists() else []

    logger.info("[%s] Loaded: %d chunks, %d nodes, %d edges", exp_id, len(chunks), len(nodes), len(edges))

    lancedb_report: Optional[ImportReport] = None
    neptune_report: Optional[ImportReport] = None

    if not icfg.validate_only:
        # Check existence and handle modes
        if icfg.lancedb_write:
            existing_count = _check_lancedb_exists(db_path, EXPERIMENT_TABLE, exp_id)
            if existing_count > 0:
                if icfg.replace_experiment:
                    logger.info("[%s] Replacing %d existing LanceDB rows", exp_id, existing_count)
                    _delete_lancedb_experiment(db_path, EXPERIMENT_TABLE, exp_id)
                else:
                    logger.warning("[%s] SKIP LanceDB: %d rows already exist (use --replace-experiment to overwrite)", exp_id, existing_count)
                    lancedb_report = ImportReport(
                        experiment_project_id=exp_id,
                        import_mode="skipped",
                        warnings=[f"Already exists with {existing_count} rows"],
                    )

            if lancedb_report is None or lancedb_report.import_mode != "skipped":
                lancedb_report = import_lancedb(experiment, chunks, manifest, icfg)

        if icfg.neptune_import:
            graph_id = icfg.neptune_graph_id or _default_config.neptune_graph_id
            neptune = NeptuneClient(graph_id=graph_id, region=icfg.aws_region)
            if neptune.ping():
                existing_nodes = _check_neptune_exists(neptune, exp_id)
                if existing_nodes > 0:
                    if icfg.replace_experiment:
                        logger.info("[%s] Replacing %d existing Neptune nodes", exp_id, existing_nodes)
                        _delete_neptune_experiment(neptune, exp_id)
                    else:
                        logger.warning("[%s] SKIP Neptune: %d nodes already exist (use --replace-experiment to overwrite)", exp_id, existing_nodes)
                        neptune_report = ImportReport(
                            experiment_project_id=exp_id,
                            neptune_graph_id=graph_id,
                            import_mode="skipped",
                            warnings=[f"Already exists with {existing_nodes} nodes"],
                        )

                if neptune_report is None or neptune_report.import_mode != "skipped":
                    neptune_report = import_neptune(experiment, nodes, edges, icfg)
            else:
                logger.warning("[%s] Neptune not reachable — skipping graph import", exp_id)
                neptune_report = ImportReport(
                    experiment_project_id=exp_id,
                    neptune_graph_id=graph_id,
                    errors=["Neptune not reachable"],
                )

    # Validation
    validation = validate_experiment(
        experiment,
        expected_chunks=len(chunks),
        expected_nodes=len(nodes),
        expected_edges=len(edges),
        icfg=icfg,
    )

    # Write reports
    report_dir = _write_reports(experiment, lancedb_report, neptune_report, validation, icfg)
    logger.info("[%s] Reports written to: %s", exp_id, report_dir)

    return {
        "experiment_project_id": exp_id,
        "status": "completed",
        "chunks_count": len(chunks),
        "nodes_count": len(nodes),
        "edges_count": len(edges),
        "lancedb_imported": lancedb_report.chunks_imported if lancedb_report else 0,
        "neptune_nodes_imported": neptune_report.nodes_imported if neptune_report else 0,
        "neptune_edges_imported": neptune_report.edges_imported if neptune_report else 0,
        "validation": {
            "lancedb_match": validation.lancedb_count_match,
            "neptune_node_match": validation.neptune_node_count_match,
            "neptune_edge_match": validation.neptune_edge_count_match,
            "cross_boundary": validation.neptune_cross_boundary_edges,
        },
        "report_dir": str(report_dir),
    }


def run_import(icfg: ImportConfig) -> list[dict]:
    """Run import for all targeted experiments."""
    manifest = _load_manifest(icfg.experiment_dir)
    experiments = manifest["experiments"]

    if icfg.target != "all":
        experiments = [e for e in experiments if e["experiment_project_id"] == icfg.target]
        if not experiments:
            raise ValueError(f"Experiment not found: {icfg.target}")

    # Filter to completed experiments only
    experiments = [e for e in experiments if e.get("status") == "completed"]
    logger.info("Found %d completed experiments to import", len(experiments))

    results = []
    for experiment in experiments:
        result = import_experiment(experiment, manifest, icfg)
        results.append(result)

    # Retrieval isolation verification (if at least 2 experiments imported to LanceDB)
    if icfg.lancedb_write and len(experiments) >= 2:
        exp_ids = [e["experiment_project_id"] for e in experiments]
        isolated = verify_retrieval_isolation(exp_ids[0], exp_ids[1], icfg)
        logger.info("Retrieval isolation check: %s", "PASS" if isolated else "FAIL")
        # Update validation reports with isolation result
        for exp_id in exp_ids[:2]:
            val_path = icfg.experiment_dir / "imports" / exp_id / "validation_report.json"
            if val_path.exists():
                val_data = json.loads(val_path.read_text())
                val_data["retrieval_isolation_verified"] = isolated
                val_path.write_text(json.dumps(val_data, indent=2, ensure_ascii=False))

    return results
