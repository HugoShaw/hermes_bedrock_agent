"""Flow specification models for semantic Excel flowchart parsing.

These models represent the SEMANTIC understanding of a flowchart,
not the raw OOXML structure. The key insight is:
- Shape != Node (many shapes are edge labels, containers, or decorations)
- Connector != Edge (direction must be validated, labels must be attached)
- Spatial layout encodes semantics (reading direction, branching structure)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class NodeType(str, Enum):
    START = "start"
    END = "end"
    PROCESS = "process"
    DECISION = "decision"
    INPUT_OUTPUT = "input_output"
    DATA = "data"
    DOCUMENT = "document"
    SYSTEM = "system"
    DB = "db"
    NOTE = "note"
    CONTAINER = "container"
    LOOP = "loop"
    UNKNOWN = "unknown"


class NodeRole(str, Enum):
    BUSINESS_STEP = "business_step"
    CONDITION = "condition"
    SYSTEM_ACTION = "system_action"
    MANUAL_ACTION = "manual_action"
    DATA_OBJECT = "data_object"
    ANNOTATION = "annotation"
    EDGE_LABEL = "edge_label"
    CONTAINER = "container"
    LOOP_MARKER = "loop_marker"
    IGNORED = "ignored"


class EdgeType(str, Enum):
    NORMAL = "normal"
    YES_BRANCH = "yes_branch"
    NO_BRANCH = "no_branch"
    OK_BRANCH = "ok_branch"
    NG_BRANCH = "ng_branch"
    ERROR_BRANCH = "error_branch"
    FALLBACK = "fallback"
    INFERRED = "inferred"
    CONDITION = "condition"


class ReviewStatus(str, Enum):
    OK = "ok"
    UNCERTAIN = "uncertain"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    EXCLUDE = "exclude_from_flow"


@dataclass
class Evidence:
    """Evidence backing a flow_spec element."""
    shape_ids: list[str] = field(default_factory=list)
    connector_ids: list[str] = field(default_factory=list)
    text_source: str = ""
    geometry: str = ""
    position: str = ""
    visual_reason: str = ""
    ooxml_reason: str = ""


@dataclass
class FlowNode:
    """A semantic node in the flow specification."""
    node_id: str
    original_shape_id: str
    text: str
    normalized_text: str = ""
    node_type: NodeType = NodeType.PROCESS
    role: NodeRole = NodeRole.BUSINESS_STEP
    lane_id: str = ""
    region_id: str = ""
    bbox: dict = field(default_factory=dict)
    evidence: Evidence = field(default_factory=Evidence)
    confidence: float = 0.8
    review_status: ReviewStatus = ReviewStatus.OK
    reason: str = ""


@dataclass
class FlowEdge:
    """A semantic edge in the flow specification."""
    edge_id: str
    from_node_id: str
    to_node_id: str
    label: str = ""
    condition: str = ""
    edge_type: EdgeType = EdgeType.NORMAL
    evidence: Evidence = field(default_factory=Evidence)
    confidence: float = 0.8
    review_status: ReviewStatus = ReviewStatus.OK
    reason: str = ""


@dataclass
class FlowLane:
    """A swim lane or functional region."""
    lane_id: str
    title: str
    bbox: dict = field(default_factory=dict)
    evidence_shape_ids: list[str] = field(default_factory=list)


@dataclass
class ExcludedObject:
    """An object excluded from the flow with reason."""
    object_id: str
    object_type: str
    text: str = ""
    exclude_reason: str = ""


@dataclass
class FlowWarning:
    """A warning about uncertain flow interpretation."""
    warning_id: str
    message: str
    severity: str = "medium"
    related_objects: list[str] = field(default_factory=list)


@dataclass
class RegionSpec:
    """Specification for a detected region/container."""
    region_id: str
    sheet_name: str
    title: str
    container_shape_id: str = ""
    bbox: dict = field(default_factory=dict)
    shape_ids: list[str] = field(default_factory=list)
    connector_ids: list[str] = field(default_factory=list)
    region_type: str = "function_module"
    confidence: float = 0.8
    reason: str = ""


@dataclass
class FlowSpec:
    """Complete flow specification for a region or sheet."""
    source_excel: str = ""
    sheet_name: str = ""
    region_id: str = ""
    region_title: str = ""
    confidence: float = 0.8
    
    lanes: list[FlowLane] = field(default_factory=list)
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    excluded_objects: list[ExcludedObject] = field(default_factory=list)
    warnings: list[FlowWarning] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Convert to serializable dict."""
        import dataclasses
        return dataclasses.asdict(self)
