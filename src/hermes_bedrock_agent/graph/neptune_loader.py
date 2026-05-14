"""Neptune loader — parameterized openCypher for live loading + inline Cypher for export.

TWO MODES:
- LOAD MODE: uses parameterized queries + parameter dicts via neptune_client.
  No user/LLM-generated strings are ever interpolated into query text.
- EXPORT MODE (dry-run): generates escaped inline Cypher for human inspection,
  written to neptune_import.cypher artifact file.

Provides:
- entity_type_to_label(): map entity_type enum to PascalCase node label
- relation_type_to_cypher_type(): map relation_type enum to UPPER_SNAKE edge type
- serialize_property_value(): explicit list→string conversion (inline Cypher only)
- build_node_query_and_params(): parameterized MERGE + SET for Neptune
- build_edge_query_and_params(): parameterized MERGE + SET for Neptune
- build_node_cypher(): inline MERGE for export files
- build_edge_cypher(): inline MERGE for export files
- build_import_cypher(): full export script
- write_neptune_import_cypher(): write export file
- load_to_neptune(): execute parameterized queries via client

Neptune calls go through clients/neptune_client.py (dependency injection).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.graph import EvidenceRecord, GraphEntity, GraphRelation

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Label / type mapping
# ---------------------------------------------------------------------------


def entity_type_to_label(entity_type: str) -> str:
    """Map entity_type value to PascalCase node label for Neptune.

    Examples:
        module -> Module
        system -> System
        business_process -> BusinessProcess
        process_step -> ProcessStep
        unknown -> Unknown
    """
    parts = entity_type.lower().split("_")
    return "".join(part.capitalize() for part in parts) or "Unknown"


def relation_type_to_cypher_type(relation_type: str) -> str:
    """Map relation_type value to UPPER_SNAKE edge type for Neptune.

    Examples:
        belongs_to -> BELONGS_TO
        implemented_by -> IMPLEMENTED_BY
        reads_from -> READS_FROM
        related_to -> RELATED_TO
    """
    return relation_type.upper()


# ---------------------------------------------------------------------------
# Property serialization
# ---------------------------------------------------------------------------


def serialize_property_value(value: Any) -> Any:
    """Serialize a property value for Neptune parameterized queries.

    Neptune Analytics supports: str, int, float, bool.
    Lists are serialized as comma-separated strings (Neptune limitation).

    This function is the SINGLE place where list→string conversion happens,
    making it easy to update if Neptune adds array support.
    """
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    elif isinstance(value, bool):
        return value
    elif isinstance(value, (int, float)):
        return value
    elif isinstance(value, str):
        return value
    else:
        return str(value)


def _build_node_properties(entity: GraphEntity) -> dict[str, Any]:
    """Build the property dict for a node (used in both modes)."""
    props: dict[str, Any] = {
        "entity_id": entity.entity_id,
        "name": entity.name or entity.canonical_name,
        "canonical_name": entity.canonical_name,
        "entity_type": entity.entity_type.value,
        "description": entity.description,
        "aliases": serialize_property_value(entity.aliases),
        "source_chunk_ids": serialize_property_value(entity.source_chunk_ids),
        "confidence": entity.confidence,
        "extraction_count": entity.extraction_count,
    }
    if entity.acl:
        props["acl"] = serialize_property_value(entity.acl)
    return props


def _build_edge_properties(relation: GraphRelation) -> dict[str, Any]:
    """Build the property dict for an edge (used in both modes)."""
    props: dict[str, Any] = {
        "relation_id": relation.relation_id,
        "relation_type": relation.relation_type.value,
        "description": relation.description,
        "source_chunk_id": relation.source_chunk_id,
        "source_chunk_ids": serialize_property_value(relation.source_chunk_ids),
        "evidence_id": relation.evidence_id,
        "confidence": relation.confidence,
        "weight": relation.weight,
    }
    if relation.acl:
        props["acl"] = serialize_property_value(relation.acl)
    return props


# ---------------------------------------------------------------------------
# LOAD MODE: parameterized queries (safe — no string interpolation)
# ---------------------------------------------------------------------------


def build_node_query_and_params(entity: GraphEntity) -> tuple[str, dict[str, Any]]:
    """Build parameterized MERGE + SET query for a single entity.

    Returns (query_template, parameters_dict).
    The query uses $param references — NEVER interpolates entity values.

    The label is derived from entity_type via entity_type_to_label().
    Since openCypher does not support parameterized labels, the label
    is statically derived from the enum value (not from user input).
    """
    label = entity_type_to_label(entity.entity_type.value)
    props = _build_node_properties(entity)

    query = (
        f"MERGE (n:`{label}` {{entity_id: $entity_id}}) "
        f"SET n += $props "
        f"RETURN n.entity_id AS id"
    )

    params = {
        "entity_id": entity.entity_id,
        "props": props,
    }

    return query, params


def build_edge_query_and_params(relation: GraphRelation) -> tuple[str, dict[str, Any]]:
    """Build parameterized MERGE + SET query for a single relation.

    Returns (query_template, parameters_dict).
    The query uses $param references — NEVER interpolates relation values.

    The edge type is derived from relation_type via relation_type_to_cypher_type().
    Since openCypher does not support parameterized relationship types, the type
    is statically derived from the enum value (not from user input).
    """
    edge_type = relation_type_to_cypher_type(relation.relation_type.value)
    props = _build_edge_properties(relation)

    query = (
        f"MATCH (a {{entity_id: $from_id}}), (b {{entity_id: $to_id}}) "
        f"MERGE (a)-[r:`{edge_type}`]->(b) "
        f"SET r += $props "
        f"RETURN r.relation_id AS id"
    )

    params = {
        "from_id": relation.source_entity_id,
        "to_id": relation.target_entity_id,
        "props": props,
    }

    return query, params


# ---------------------------------------------------------------------------
# Neptune loading (parameterized path)
# ---------------------------------------------------------------------------


def load_nodes_to_neptune(
    neptune_client,
    entities: list[GraphEntity],
    *,
    batch_size: int = 50,
) -> tuple[int, int]:
    """Load entity nodes to Neptune using parameterized queries.

    Returns (loaded_count, error_count).
    """
    loaded = 0
    errors = 0

    for i in range(0, len(entities), batch_size):
        batch = entities[i : i + batch_size]
        for entity in batch:
            query, params = build_node_query_and_params(entity)
            try:
                neptune_client.execute_query(query, parameters=params)
                loaded += 1
            except Exception as e:
                logger.warning(f"Failed to load entity {entity.entity_id}: {e}")
                errors += 1

    return loaded, errors


def load_edges_to_neptune(
    neptune_client,
    relations: list[GraphRelation],
    *,
    batch_size: int = 50,
) -> tuple[int, int]:
    """Load relation edges to Neptune using parameterized queries.

    Returns (loaded_count, error_count).
    """
    loaded = 0
    errors = 0

    for i in range(0, len(relations), batch_size):
        batch = relations[i : i + batch_size]
        for relation in batch:
            query, params = build_edge_query_and_params(relation)
            try:
                neptune_client.execute_query(query, parameters=params)
                loaded += 1
            except Exception as e:
                logger.warning(f"Failed to load relation {relation.relation_id}: {e}")
                errors += 1

    return loaded, errors


def load_to_neptune(
    neptune_client,
    entities: list[GraphEntity],
    relations: list[GraphRelation],
    *,
    dry_run: bool = False,
    batch_size: int = 50,
) -> dict[str, Any]:
    """Execute import against Neptune Analytics using parameterized queries.

    Args:
        neptune_client: Neptune client (from clients/neptune_client.py).
        entities: Entities to load.
        relations: Relations to load.
        dry_run: If True, don't execute (return summary only).
        batch_size: Statements per batch.

    Returns:
        Summary dict: {nodes_loaded, edges_loaded, total_statements, errors, dry_run}.
    """
    if dry_run:
        total = len(entities) + len(relations)
        logger.info(f"[DRY RUN] Would load {len(entities)} nodes + {len(relations)} edges")
        return {
            "nodes_loaded": 0,
            "edges_loaded": 0,
            "total_statements": total,
            "errors": 0,
            "dry_run": True,
        }

    nodes_loaded, node_errors = load_nodes_to_neptune(
        neptune_client, entities, batch_size=batch_size
    )
    edges_loaded, edge_errors = load_edges_to_neptune(
        neptune_client, relations, batch_size=batch_size
    )

    total_errors = node_errors + edge_errors
    logger.info(
        f"Neptune load complete: {nodes_loaded} nodes, {edges_loaded} edges, "
        f"{total_errors} errors"
    )
    return {
        "nodes_loaded": nodes_loaded,
        "edges_loaded": edges_loaded,
        "total_statements": nodes_loaded + edges_loaded,
        "errors": total_errors,
        "dry_run": False,
    }


# ---------------------------------------------------------------------------
# EXPORT MODE: inline escaped Cypher for human review / dry-run artifacts
# ---------------------------------------------------------------------------

# String escaping (ONLY used in export mode, never in load mode)


def _escape_cypher_string(value: str) -> str:
    """Escape a string for safe inclusion in inline Cypher single-quoted literals.

    ONLY used for export/dry-run artifact files. Never used in load mode.
    """
    result = value.replace("\\", "\\\\")
    result = result.replace("'", "\\'")
    result = result.replace("\n", "\\n")
    result = result.replace("\r", "\\r")
    result = result.replace("\t", "\\t")
    return result


def _escape_label(label: str) -> str:
    """Sanitize a node label for inline Cypher (alphanumeric + underscore only)."""
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", label)
    if sanitized and not sanitized[0].isalpha():
        sanitized = "N_" + sanitized
    return sanitized or "Unknown"


def _format_inline_value(value: Any) -> str:
    """Format a property value for inline Cypher export. Lists become strings."""
    if isinstance(value, str):
        return f"'{_escape_cypher_string(value)}'"
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, list):
        joined = ", ".join(str(v) for v in value)
        return f"'{_escape_cypher_string(joined)}'"
    else:
        return f"'{_escape_cypher_string(str(value))}'"


def build_node_cypher(entity: GraphEntity) -> str:
    """Generate inline MERGE + SET Cypher for export files.

    WARNING: This produces inline Cypher for human inspection only.
    For live Neptune loading, use build_node_query_and_params() instead.
    """
    label = entity_type_to_label(entity.entity_type.value)
    eid = _escape_cypher_string(entity.entity_id)
    props = _build_node_properties(entity)

    prop_parts = []
    for k, v in props.items():
        prop_parts.append(f"{k}: {_format_inline_value(v)}")
    props_str = ", ".join(prop_parts)

    return f"MERGE (n:`{label}` {{entity_id: '{eid}'}})\nSET n += {{{props_str}}};"


def build_edge_cypher(relation: GraphRelation) -> str:
    """Generate inline MERGE + SET Cypher for export files.

    WARNING: This produces inline Cypher for human inspection only.
    For live Neptune loading, use build_edge_query_and_params() instead.
    """
    from_id = _escape_cypher_string(relation.source_entity_id)
    to_id = _escape_cypher_string(relation.target_entity_id)
    edge_type = relation_type_to_cypher_type(relation.relation_type.value)
    props = _build_edge_properties(relation)

    prop_parts = []
    for k, v in props.items():
        prop_parts.append(f"{k}: {_format_inline_value(v)}")
    props_str = ", ".join(prop_parts)

    return (
        f"MATCH (a {{entity_id: '{from_id}'}}), (b {{entity_id: '{to_id}'}})\n"
        f"MERGE (a)-[r:`{edge_type}`]->(b)\n"
        f"SET r += {{{props_str}}};"
    )


def build_import_cypher(
    entities: list[GraphEntity],
    relations: list[GraphRelation],
    *,
    header_comment: str = "",
) -> str:
    """Generate full inline import Cypher script for export/review.

    Returns a string with all MERGE statements — for human inspection only.
    """
    lines = []

    if header_comment:
        lines.append(f"// {header_comment}")
        lines.append("")

    lines.append(f"// === Nodes ({len(entities)}) ===")
    lines.append("")

    for entity in entities:
        lines.append(build_node_cypher(entity))
        lines.append("")

    lines.append(f"// === Edges ({len(relations)}) ===")
    lines.append("")

    for relation in relations:
        lines.append(build_edge_cypher(relation))
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File output (export mode)
# ---------------------------------------------------------------------------


def write_neptune_import_cypher(
    entities: list[GraphEntity],
    relations: list[GraphRelation],
    output_path: Path | str,
    *,
    dry_run: bool = False,
) -> int:
    """Write Neptune import Cypher file (inline escaped, for human review).

    Args:
        entities: Accepted entities to export.
        relations: Accepted relations to export.
        output_path: Target .cypher file path.
        dry_run: If True, don't actually write.

    Returns:
        Number of statements written (nodes + edges).
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    cypher = build_import_cypher(
        entities,
        relations,
        header_comment=f"Neptune import: {len(entities)} nodes, {len(relations)} edges",
    )

    total = len(entities) + len(relations)

    if dry_run:
        logger.info(f"[DRY RUN] Would write {total} Cypher statements to {path}")
        return total

    path.write_text(cypher, encoding="utf-8")
    logger.info(f"Wrote {total} Cypher statements to {path}")
    return total
