"""Phase 6: Build display graph (filtered subset for Graph Explore) and review tasks."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DISPLAY_TYPES = {
    # Project structure
    "Project", "Workbook",
    # System / Interface
    "System", "ExternalSystem", "InternalSystem", "Middleware", "IntegrationTool",
    "Interface", "APIOperation", "APICallSequence", "APIEndpoint",
    # Business / Process
    "BusinessProcess", "BusinessObject", "BusinessStep", "FunctionModule",
    "FlowNode", "DecisionPoint", "BranchCondition",
    # Data / Fields
    "DataEntity", "RecordType", "Field", "FieldDefinition",
    "Parameter", "EnumValue", "StatusValue",
    # Mapping / Rules
    "MappingDefinition", "BusinessRule", "TransformationRule", "ConversionRule",
    "DefaultValueRule", "FixedValueRule", "LookupRule", "CalculationRule",
    "FilterCondition", "DataRetrievalCondition", "Constraint",
    # Implementation
    "ImplementationSpec", "Script", "ScriptStep", "FileObject", "FileOperation",
    "APICallStep", "ResultReturn", "ErrorHandlingStep",
    # Review
    "Issue", "ReviewTask", "Requirement",
}


def build_display_graph(
    nodes: list[dict], edges: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Filter to core semantic entities and verified relationships only."""
    display_node_ids: set[str] = set()
    display_nodes: list[dict] = []

    for node in nodes:
        if (
            node.get("entity_type", "") in _DISPLAY_TYPES
            and node.get("view_scope", "core") in ("core", "detail")
        ):
            display_nodes.append(node)
            display_node_ids.add(node["id"])

    display_edges = [
        e for e in edges
        if (
            e.get("start_id") in display_node_ids
            and e.get("end_id") in display_node_ids
            and e.get("review_status", "verified") != "rejected"
        )
    ]

    return display_nodes, display_edges


def generate_review_tasks(
    nodes: list[dict],
    edges: list[dict],
    inventory: list[dict],
    project_id: str,
    project_name: str,
) -> list[dict]:
    """Generate review task items for quality issues."""
    tasks: list[dict] = []
    counter = 0

    def _task(target_id: str, target_name: str, reason: str, fix: str, severity: str,
               source: str, evidence: str) -> dict:
        nonlocal counter
        counter += 1
        return {
            "project_name": project_name,
            "project_id": project_id,
            "id": f"review:{project_id}:{counter:04d}",
            "entity_type": "ReviewTask",
            "target_node_id": target_id,
            "target_name": target_name,
            "reason": reason,
            "expected_fix": fix,
            "severity": severity,
            "source_file": source,
            "evidence_text": evidence[:200],
        }

    function_ids = {n["id"] for n in nodes if n.get("entity_type") == "FunctionModule"}
    has_internal = {
        e["start_id"] for e in edges
        if e.get("type") == "CONTAINS_STEP" and e.get("start_id") in function_ids
    }
    for node in nodes:
        if node.get("entity_type") == "FunctionModule" and node["id"] not in has_internal:
            tasks.append(_task(
                node["id"], node.get("display_name", node.get("name", "")),
                "FunctionModule has no extracted internal flow nodes (CONTAINS_STEP)",
                "Extract internal nodes from function blocks and connect with CONTAINS_STEP/NEXT_STEP",
                "P2", node.get("source_file", ""), node.get("evidence_text", ""),
            ))

    api_ids = {n["id"] for n in nodes if n.get("entity_type") == "APIOperation"}
    called_apis = {
        e["end_id"] for e in edges
        if e.get("type") in ("CALLS_API", "HAS_API_OPERATION") and e.get("end_id") in api_ids
    }
    for node in nodes:
        if node.get("entity_type") == "APIOperation" and node["id"] not in called_apis:
            tasks.append(_task(
                node["id"], node.get("display_name", node.get("name", "")),
                "APIOperation has no caller (CALLS_API) or owning interface (HAS_API_OPERATION)",
                "Link API to calling FunctionModule or owning Interface",
                "P2", node.get("source_file", ""), node.get("evidence_text", ""),
            ))

    for node in nodes:
        if node.get("review_status") == "pending" and node.get("confidence", 1.0) < 0.70:
            tasks.append(_task(
                node["id"], node.get("display_name", node.get("name", "")),
                f"Low confidence entity ({node.get('confidence', 0):.2f})",
                "Verify entity against source document",
                "P3", node.get("source_file", ""), node.get("evidence_text", ""),
            ))

    return tasks
