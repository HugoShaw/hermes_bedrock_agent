"""Phase 3: ID registry, entity deduplication, and edge normalization.

Converts raw LLM-extracted dicts into stable-ID plain dicts with canonical
IDs scoped to the project, deduplicating same-entity entries and remapping
edge endpoint IDs accordingly.

v2: Robust endpoint resolver — never silently drops verified edges.
    Accepts both 'from'/'to' and 'from_id'/'to_id' field names from cache.
    Tracks unresolved edges explicitly for downstream reporting.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from ._utils import normalize_id

logger = logging.getLogger(__name__)

# Entity types that are scoped globally (deduplicated across sheets)
_GLOBAL_TYPES = {"System", "Middleware", "Interface"}

# Entity types scoped to sheet (workbook + sheet key)
_SHEET_SCOPED_TYPES = {"Field", "FieldMapping", "FilterCondition", "FieldDefinition", "EnumValue", "Parameter"}

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
    "FieldDefinition": "fielddef",
    "Parameter": "param",
    "EnumValue": "enum",
    "BusinessStep": "bstep",
    "BusinessObject": "bobj",
    "Script": "script",
    "Requirement": "req",
    "RecordType": "rectype",
    "Issue": "issue",
    "Constraint": "constraint",
    "APIEndpoint": "endpoint",
    "Condition": "condition",
    "DefaultValueRule": "rule_default",
    "InternalSystem": "internal_sys",
    "IntegrationTool": "tool",
    "ExternalSystem": "ext_system",
    "ReviewTask": "review_task",
    "Loop": "loop",
    "StartEndNode": "startend",
    "ResponsePayload": "resp_payload",
    "RequestPayload": "req_payload",
    "QueryCondition": "query_cond",
    "BranchCondition": "branch_cond",
    "CalculationRule": "rule_calc",
    "LookupRule": "rule_lookup",
    "FixedValueRule": "rule_fixed",
    "Batch": "batch",
    "Job": "job",
}

# Reverse map: prefix -> entity_type (for resolver)
_PREFIX_TO_TYPE: dict[str, str] = {v: k for k, v in _TYPE_PREFIX.items()}


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


def _extract_edge_endpoints(edge: dict) -> tuple[str, str]:
    """Extract from/to endpoint IDs from an edge, tolerating both field name conventions.

    Cache/LLM outputs may use:
      - 'from' / 'to' (v4.5 prompt output)
      - 'from_id' / 'to_id' (v4.3 prompt output)
    """
    from_id = edge.get("from_id") or edge.get("from") or ""
    to_id = edge.get("to_id") or edge.get("to") or ""
    return from_id, to_id


class EndpointResolver:
    """Multi-strategy resolver for mapping raw/cache edge endpoints to canonical node IDs.

    Resolution order:
      1. exact final node id match (canonical_ids set)
      2. raw id match stored in id_remap (raw local id -> canonical)
      3. name_map lookup (aliases)
      4. label + normalized name match (parse raw endpoint as project_id:Label:Name)
      5. label_prefix + name_key match against canonical_ids
      6. workbook-scoped label + name match
      7. sheet-scoped label + name match
      8. name-only fuzzy match across all canonical nodes
    """

    def __init__(
        self,
        canonical_ids: set[str],
        id_remap: dict[str, str],
        name_map: dict[str, str],
        canonical_nodes: dict[str, dict],
        project_id: str,
    ):
        self._canonical_ids = canonical_ids
        self._id_remap = id_remap
        self._name_map = name_map
        self._canonical_nodes = canonical_nodes
        self._project_id = project_id

        # Build secondary lookup indices
        # label_name_key -> canonical_id (for label:project:name pattern)
        self._label_name_index: dict[str, str] = {}
        # normalized_name -> list of canonical_ids (for name-only fallback)
        self._name_index: dict[str, list[str]] = defaultdict(list)

        for cid, node in canonical_nodes.items():
            entity_type = node.get("entity_type", node.get("labels", "Unknown")).split("|")[0]
            name = node.get("name", node.get("display_name", ""))
            name_norm = normalize_id(name)[:50]
            # Build label:name key (how cache endpoints look: project_id:Label:Name)
            label_key = f"{project_id}:{entity_type}:{name}"
            self._label_name_index[label_key] = cid
            # Also normalized version
            label_key_norm = f"{project_id}:{entity_type}:{name_norm}"
            self._label_name_index[label_key_norm] = cid
            # Name-only index
            if name_norm:
                self._name_index[name_norm].append(cid)

        # Track resolution stats
        self.stats = Counter()

    def resolve(self, raw_endpoint: str, workbook_name: str = "", sheet_name: str = "") -> Optional[str]:
        """Resolve a raw edge endpoint to a canonical node ID.

        Returns the canonical ID if resolved, None otherwise.
        """
        if not raw_endpoint:
            self.stats["empty_endpoint"] += 1
            return None

        # Strategy 1: exact match in canonical_ids
        if raw_endpoint in self._canonical_ids:
            self.stats["exact_canonical"] += 1
            return raw_endpoint

        # Strategy 2: id_remap (raw local id -> canonical)
        if raw_endpoint in self._id_remap:
            resolved = self._id_remap[raw_endpoint]
            if resolved in self._canonical_ids:
                self.stats["id_remap"] += 1
                return resolved

        # Strategy 3: name_map lookup
        if raw_endpoint in self._name_map:
            resolved = self._name_map[raw_endpoint]
            if resolved in self._canonical_ids:
                self.stats["name_map"] += 1
                return resolved

        # Strategy 4: label + name match (parse project_id:Label:Name format)
        # Cache endpoints look like: sample_20260519:APIOperation:発注一覧取得
        if raw_endpoint in self._label_name_index:
            self.stats["label_name_exact"] += 1
            return self._label_name_index[raw_endpoint]

        # Strategy 5: label_prefix + normalized name against canonical_ids
        # Parse the raw endpoint to extract label and name components
        parts = raw_endpoint.split(":", 2)
        if len(parts) >= 3:
            _proj, label, name = parts[0], parts[1], parts[2]
            prefix = _TYPE_PREFIX.get(label, label.lower()[:20])
            name_key = normalize_id(name)[:50]

            # Try global scope
            candidate = f"{prefix}:{self._project_id}:{name_key}"
            if candidate in self._canonical_ids:
                self.stats["label_prefix_global"] += 1
                return candidate

            # Try workbook scope
            wb_key = normalize_id(workbook_name) if workbook_name else ""
            if wb_key:
                candidate = f"{prefix}:{self._project_id}:{wb_key}:{name_key}"
                if candidate in self._canonical_ids:
                    self.stats["label_prefix_workbook"] += 1
                    return candidate

            # Try sheet scope
            sheet_key = normalize_id(sheet_name) if sheet_name else ""
            if wb_key and sheet_key:
                candidate = f"{prefix}:{self._project_id}:{wb_key}:{sheet_key}:{name_key}"
                if candidate in self._canonical_ids:
                    self.stats["label_prefix_sheet"] += 1
                    return candidate

            # Try all workbook variants for this prefix+name
            for cid in self._canonical_ids:
                if cid.startswith(f"{prefix}:{self._project_id}:") and cid.endswith(f":{name_key}"):
                    self.stats["label_prefix_any_scope"] += 1
                    return cid

        # Strategy 6: fuzzy prefix probing (original _fuzzy_resolve logic)
        wb_key = normalize_id(workbook_name) if workbook_name else ""
        for prefix in _TYPE_PREFIX.values():
            candidate = f"{prefix}:{self._project_id}:{normalize_id(raw_endpoint)}"
            if candidate in self._canonical_ids:
                self.stats["fuzzy_global"] += 1
                return candidate
            if wb_key:
                candidate = f"{prefix}:{self._project_id}:{wb_key}:{normalize_id(raw_endpoint)}"
                if candidate in self._canonical_ids:
                    self.stats["fuzzy_workbook"] += 1
                    return candidate

        # Strategy 7: name-only match (last resort, must be unambiguous)
        name_part = raw_endpoint.rsplit(":", 1)[-1] if ":" in raw_endpoint else raw_endpoint
        name_norm = normalize_id(name_part)[:50]
        if name_norm and name_norm in self._name_index:
            candidates = self._name_index[name_norm]
            if len(candidates) == 1:
                self.stats["name_only_unambiguous"] += 1
                return candidates[0]
            # If multiple candidates but one matches expected label
            if len(parts) >= 3:
                label = parts[1]
                prefix = _TYPE_PREFIX.get(label, label.lower()[:20])
                matching = [c for c in candidates if c.startswith(f"{prefix}:")]
                if len(matching) == 1:
                    self.stats["name_only_label_filtered"] += 1
                    return matching[0]

        self.stats["unresolved"] += 1
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
    Edges whose endpoints cannot be resolved are tracked in registry['unresolved_edges'].
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

    # ── Phase 2: remap edge IDs with robust endpoint resolution ────────────────
    canonical_ids_set = set(canonical_nodes.keys())
    resolver = EndpointResolver(
        canonical_ids=canonical_ids_set,
        id_remap=id_remap,
        name_map=name_map,
        canonical_nodes=canonical_nodes,
        project_id=project_id,
    )

    normalized_edges: list[dict] = []
    unresolved_edges: list[dict] = []
    edge_counter = 0

    for edge in all_edges:
        from_id, to_id = _extract_edge_endpoints(edge)
        workbook_name = edge.get("workbook_name", "")
        sheet_name = edge.get("sheet_name", "")

        canonical_from = resolver.resolve(from_id, workbook_name, sheet_name)
        canonical_to = resolver.resolve(to_id, workbook_name, sheet_name)

        if canonical_from and canonical_to:
            edge_counter += 1
            edge["id"] = f"rel:{project_id}:{edge_counter:06d}"
            edge["start_id"] = canonical_from
            edge["end_id"] = canonical_to
            # Preserve raw endpoints for traceability
            edge["raw_from"] = from_id
            edge["raw_to"] = to_id
            # Clean up old field names
            edge.pop("from_id", None)
            edge.pop("to_id", None)
            edge.pop("from", None)
            edge.pop("to", None)
            normalized_edges.append(edge)
        else:
            # Track unresolved edge — never silently drop
            unresolved_entry = {
                "raw_from": from_id,
                "raw_to": to_id,
                "resolved_from": canonical_from,
                "resolved_to": canonical_to,
                "type": edge.get("type", "UNKNOWN"),
                "confidence": edge.get("confidence", 0),
                "review_status": edge.get("review_status", "pending"),
                "link_method": edge.get("link_method", ""),
                "source_file": edge.get("source_file", ""),
                "workbook_name": workbook_name,
                "sheet_name": sheet_name,
                "evidence_text": edge.get("evidence_text", ""),
                "evidence_id": edge.get("evidence_id", ""),
                "from_label": edge.get("from_label", ""),
                "to_label": edge.get("to_label", ""),
                "unresolved_reason": (
                    "from_unresolved" if not canonical_from else "to_unresolved"
                ) if canonical_from or canonical_to else "both_unresolved",
            }
            unresolved_edges.append(unresolved_entry)

    # Build diagnostics
    cache_edge_types = Counter(e.get("type", "UNKNOWN") for e in all_edges)
    promoted_edge_types = Counter(e.get("type", "UNKNOWN") for e in normalized_edges)
    unresolved_edge_types = Counter(e.get("type", "UNKNOWN") for e in unresolved_edges)
    cache_verified_types = Counter(
        e.get("type", "UNKNOWN") for e in all_edges
        if e.get("review_status") == "verified"
    )

    registry = {
        "project_id": project_id,
        "project_name": project_name,
        "canonical_ids": list(canonical_nodes.keys()),
        "name_map": dict(name_map),
        "type_counts": {k: len(v) for k, v in type_map.items()},
        "edge_resolution_stats": dict(resolver.stats),
        "unresolved_edges": unresolved_edges,
        "diagnostics": {
            "cache_edge_type_counts": dict(cache_edge_types),
            "cache_verified_edge_type_counts": dict(cache_verified_types),
            "promoted_edge_type_counts": dict(promoted_edge_types),
            "unresolved_endpoint_edge_type_counts": dict(unresolved_edge_types),
            "total_cache_edges": len(all_edges),
            "total_promoted_edges": len(normalized_edges),
            "total_unresolved_edges": len(unresolved_edges),
            "silently_dropped_edge_type_counts": {},  # Always empty now — nothing is silently dropped
        },
    }

    logger.info(
        "Normalized: %d nodes (%d raw), %d edges promoted (%d raw, %d unresolved)",
        len(normalized_nodes),
        len(all_nodes),
        len(normalized_edges),
        len(all_edges),
        len(unresolved_edges),
    )
    logger.info("  Resolution stats: %s", dict(resolver.stats))
    if unresolved_edges:
        logger.warning(
            "  Unresolved edge types: %s",
            dict(unresolved_edge_types.most_common(10)),
        )

    return normalized_nodes, normalized_edges, registry


def save_registry(registry: dict, path: Path) -> None:
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
