"""Graph schema definition and validation."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NodeSchema:
    """Schema for a node label."""
    label: str
    required_properties: list[str] = field(default_factory=list)
    optional_properties: list[str] = field(default_factory=list)


@dataclass
class EdgeSchema:
    """Schema for an edge type."""
    type: str
    from_labels: list[str] = field(default_factory=list)  # allowed source labels
    to_labels: list[str] = field(default_factory=list)    # allowed target labels


# Default graph schema for Semantic Map
DEFAULT_NODE_SCHEMAS = [
    NodeSchema("Document", ["name"], ["source_uri", "text"]),
    NodeSchema("Section", ["name"], ["text", "source_uri"]),
    NodeSchema("Table", ["name"], ["source_uri", "text"]),
    NodeSchema("Column", ["name"], ["data_type", "table_name"]),
    NodeSchema("API", ["name"], ["endpoint", "method"]),
    NodeSchema("Process", ["name"], ["description"]),
    NodeSchema("Rule", ["name"], ["description"]),
    NodeSchema("Service", ["name"], ["description"]),
    NodeSchema("Module", ["name"], ["description"]),
    NodeSchema("Entity", ["name"], ["description"]),
]

DEFAULT_EDGE_SCHEMAS = [
    EdgeSchema("CONTAINS", ["Document", "Section", "Module"], ["Section", "Table", "Column"]),
    EdgeSchema("REFERENCES", [], []),
    EdgeSchema("USES_TABLE", ["Process", "API", "Module"], ["Table"]),
    EdgeSchema("USES_COLUMN", ["Process", "API"], ["Column"]),
    EdgeSchema("CALLS_API", ["Service", "Module", "Process"], ["API"]),
    EdgeSchema("IMPLEMENTS_PROCESS", ["Module", "Service"], ["Process"]),
    EdgeSchema("DESCRIBES_RULE", ["Section", "Document"], ["Rule"]),
    EdgeSchema("DEPENDS_ON", [], []),
    EdgeSchema("SAME_AS", [], []),
    EdgeSchema("RELATED_TO", [], []),
    EdgeSchema("FLOWS_TO", ["Process", "Service"], ["Process", "Service"]),
]

VALID_RELATION_TYPES = {schema.type for schema in DEFAULT_EDGE_SCHEMAS}
VALID_NODE_LABELS = {schema.label for schema in DEFAULT_NODE_SCHEMAS}
