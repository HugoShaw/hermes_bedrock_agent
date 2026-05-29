"""Phase 3: ID registry, entity deduplication, and edge normalization.

Converts raw LLM-extracted dicts into stable-ID plain dicts with canonical
IDs scoped to the project, deduplicating same-entity entries and remapping
edge endpoint IDs accordingly.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

from ._utils import normalize_id

logger = logging.getLogger(__name__)

# Entity types that are scoped globally (deduplicated across sheets)
_GLOBAL_TYPES = {"System", "Middleware", "Interface"}

# Entity types scoped to sheet (workbook + sheet key)
_SHEET_SCOPED_TYPES = {"Field", "FieldMapping", "FilterCondition"}

# Entity types scoped to workbook + sheet + parent function
_STEP_TYPES = {
    "FlowNode", "ScriptStep", "APICallStep", "FileOperation",
    "BusinessStep", "ErrorHandlingStep", "ResultReturn",
}

_TYPE_PREFIX: dict[str, str] = {
    "System": "system",
    "Middleware": "middleware",
    "Interface": "interface",
    "BusinessProcess": "process",
    "FunctionModule": "function",
    "FlowNode": "flow_node",
    "DecisionPoint": "decision",
    "BranchCondition": "condition",
    "APIOperation": "apiop",
    "APICallStep": "apistep",
    "APICallSequence": "apiseq",
    "MappingDefinition": "mappingdef",
    "FieldMapping": "mapping",
    "Field": "field",
    "DataEntity": "data",
    "FileObject": "file",
    "TransformationRule": "rule_transform",
    "ConversionRule": "rule_convert",
    "BusinessRule": "rule_business",
    "FilterCondition": "filter",
    "StatusValue": "status",
    "ScriptStep": "script_step",
    "FileOperation": "fileop",
    "ResultReturn": "result_return",
    "ErrorHandlingStep": "error_step",
    "Annotation": "annotation",
    "ImplementationSpec": "impl_spec",
    "DataRetrievalCondition": "retrieval_cond",
}


def _type_prefix(entity_type: str) -> str:
    return _TYPE_PREFIX.get(entity_type, entity_type.lower()[:20])


def _canonical_id(node: dict, project_id: str) -> str:
    entity_type = node.get("entity_type", node.get("labels", "Unknown")).split("|")[0]
    name = node.get("name", node.get("display_name", node.get("id", "")))
    workbook_key = normalize_id(node.get("workbook_name", ""))
    sheet_key = normalize_id(node.get("sheet_name", ""))
    prefix = _type_prefix(entity_type)
    name_key = normalize_id(name)[:50]

    if entity_type in _STEP_TYPES:
        parent = node.get("parent_function_id", "")
        parent_key = normalize_id(parent)[:30] if parent else sheet_key
        return f"{prefix}:{project_id}:{workbook_key}:{parent_key}:{name_key}"
    if entity_type in _SHEET_SCOPED_TYPES:
        return f"{prefix}:{project_id}:{workbook_key}:{sheet_key}:{name_key}"
    if entity_type in _GLOBAL_TYPES:
        return f"{prefix}:{project_id}:{name_key}"
    # default: workbook-scoped
    return f"{prefix}:{project_id}:{workbook_key}:{name_key}"


def _fuzzy_resolve(
    local_id: str,
    canonical_nodes: dict,
    name_map: dict,
    workbook_name: str,
    project_id: str,
) -> Optional[str]:
    if local_id in canonical_nodes:
        return local_id
    if local_id in name_map:
        return name_map[local_id]

    wb_key = normalize_id(workbook_name)
    for prefix in [
        "system", "middleware", "interface", "process", "function",
        "flow_node", "apiop", "mappingdef", "field", "decision",
    ]:
        candidate = f"{prefix}:{project_id}:{normalize_id(local_id)}"
        if candidate in canonical_nodes:
            return candidate
        candidate = f"{prefix}:{project_id}:{wb_key}:{normalize_id(local_id)}"
        if candidate in canonical_nodes:
            return candidate

    return None


def normalize_entities(
    all_nodes: list[dict],
    all_edges: list[dict],
    project_id: str,
    project_name: str,
) -> tuple[list[dict], list[dict], dict]:
    """Build global ID registry, normalize IDs, deduplicate nodes, remap edges.

    Returns (normalized_nodes, normalized_edges, registry_dict).
    The registry_dict is serializable and suitable for saving to JSON.
    """
    canonical_nodes: dict[str, dict] = {}
    name_map: dict[str, str] = {}
    type_map: dict[str, list[str]] = defaultdict(list)
    normalized_nodes: list[dict] = []
    id_remap: dict[str, str] = {}

    # ── Phase 1: build canonical node set ────────────────────────────────────
    for node in all_nodes:
        local_id = node.get("id", "")
        entity_type = node.get("entity_type", node.get("labels", "Unknown")).split("|")[0]
        name = node.get("name", node.get("display_name", local_id))

        cid = _canonical_id(node, project_id)

        if cid in canonical_nodes:
            existing = canonical_nodes[cid]
            if node.get("confidence", 0) > existing.get("confidence", 0):
                existing.update({k: v for k, v in node.items() if v and k != "id"})
            existing_aliases = existing.get("aliases_text", "")
            if name and name not in existing_aliases:
                existing["aliases_text"] = (
                    f"{existing_aliases}|{name}" if existing_aliases else name
                )
        else:
            node["id"] = cid
            canonical_nodes[cid] = node
            normalized_nodes.append(node)

        id_remap[local_id] = cid
        name_map[local_id] = cid
        type_map[entity_type].append(cid)

    # ── Phase 2: remap edge IDs ───────────────────────────────────────────────
    normalized_edges: list[dict] = []
    edge_counter = 0

    for edge in all_edges:
        from_id = edge.get("from_id", "")
        to_id = edge.get("to_id", "")

        canonical_from = id_remap.get(from_id, from_id)
        canonical_to = id_remap.get(to_id, to_id)

        if canonical_from not in canonical_nodes or canonical_to not in canonical_nodes:
            wb = edge.get("workbook_name", "")
            canonical_from = _fuzzy_resolve(from_id, canonical_nodes, name_map, wb, project_id) or canonical_from
            canonical_to = _fuzzy_resolve(to_id, canonical_nodes, name_map, wb, project_id) or canonical_to
            if canonical_from not in canonical_nodes or canonical_to not in canonical_nodes:
                continue

        edge_counter += 1
        edge["id"] = f"rel:{project_id}:{edge_counter:06d}"
        edge["start_id"] = canonical_from
        edge["end_id"] = canonical_to
        edge.pop("from_id", None)
        edge.pop("to_id", None)
        normalized_edges.append(edge)

    registry = {
        "project_id": project_id,
        "project_name": project_name,
        "canonical_ids": list(canonical_nodes.keys()),
        "name_map": dict(name_map),
        "type_counts": {k: len(v) for k, v in type_map.items()},
    }

    logger.info(
        "Normalized: %d nodes (%d raw), %d edges (%d raw)",
        len(normalized_nodes),
        len(all_nodes),
        len(normalized_edges),
        len(all_edges),
    )
    return normalized_nodes, normalized_edges, registry


def save_registry(registry: dict, path: Path) -> None:
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
