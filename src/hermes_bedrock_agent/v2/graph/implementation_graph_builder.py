"""
Implementation Graph Builder for Stage 06.

Builds the Implementation Graph from selected evidence chunks using
a deterministic heuristic approach (with optional LLM upgrade path).

Heuristic strategy:
  1. Create System node for Murata MDW
  2. Create Module nodes from Java package structure
  3. Create File nodes from source_path
  4. Create Class nodes from Java class declarations
  5. Create Method nodes from method signatures
  6. Create Service nodes from *Service* files
  7. Create Table nodes from DDL (CREATE TABLE)
  8. Create Column nodes from DDL column definitions
  9. Create SQL nodes from SQL files
  10. Create Config nodes from config files
  11. Create edges following implementation relationships
  12. Validate all with schema_registry
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.schemas.graph_schema import GraphEdge, GraphNode
from hermes_bedrock_agent.v2.graph.schema_registry import (
    IMPLEMENTATION_LABELS,
    IMPLEMENTATION_LAYER,
    IMPLEMENTATION_RELATION_TYPES,
    is_valid_label,
    is_valid_relation,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class ImplGraphConfig:
    """Configuration for implementation graph building."""
    run_id: str = "murata_semantic_v2"
    dataset: str = "murata"
    layer: str = IMPLEMENTATION_LAYER
    system_name: str = "Murata MDW支払システム"
    max_candidates: int = 5000
    max_nodes: int = 2000
    max_edges: int = 5000
    max_columns_per_table: int = 50
    max_methods_per_class: int = 30


# ============================================================================
# Internal State
# ============================================================================

@dataclass
class BuildState:
    """Mutable state during graph building."""
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, dict[str, Any]] = field(default_factory=dict)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    # Track counts for limits
    columns_per_table: Counter = field(default_factory=Counter)
    methods_per_class: Counter = field(default_factory=Counter)


# ============================================================================
# Helper Functions
# ============================================================================

def _create_node(
    label: str,
    name: str,
    display_name: str = "",
    description: str = "",
    aliases: list[str] | None = None,
    properties: dict[str, Any] | None = None,
    source_ids: list[str] | None = None,
    evidence_chunk_ids: list[str] | None = None,
    confidence: float = 0.8,
    config: ImplGraphConfig | None = None,
) -> dict[str, Any]:
    """Create a valid GraphNode dict."""
    cfg = config or ImplGraphConfig()
    node_id = GraphNode.generate_id(cfg.layer, label, name.lower().strip())
    return {
        "node_id": node_id,
        "label": label,
        "name": name.lower().strip(),
        "display_name": display_name or name,
        "layer": cfg.layer,
        "aliases": aliases or [],
        "description": description,
        "properties": properties or {},
        "source_ids": source_ids or [],
        "evidence_chunk_ids": evidence_chunk_ids or [],
        "confidence": confidence,
        "run_id": cfg.run_id,
        "dataset": cfg.dataset,
    }


def _create_edge(
    source_node_id: str,
    target_node_id: str,
    relation_type: str,
    description: str = "",
    properties: dict[str, Any] | None = None,
    source_ids: list[str] | None = None,
    evidence_chunk_ids: list[str] | None = None,
    confidence: float = 0.8,
    config: ImplGraphConfig | None = None,
) -> dict[str, Any]:
    """Create a valid GraphEdge dict."""
    cfg = config or ImplGraphConfig()
    edge_id = GraphEdge.generate_id(source_node_id, relation_type, target_node_id)
    return {
        "edge_id": edge_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "relation_type": relation_type,
        "layer": cfg.layer,
        "description": description,
        "properties": properties or {},
        "source_ids": source_ids or [],
        "evidence_chunk_ids": evidence_chunk_ids or [],
        "confidence": confidence,
        "run_id": cfg.run_id,
        "dataset": cfg.dataset,
    }


def _add_node(state: BuildState, node: dict[str, Any], config: ImplGraphConfig) -> None:
    """Add or merge a node into the state."""
    if len(state.nodes) >= config.max_nodes:
        return
    nid = node["node_id"]
    if nid in state.nodes:
        # Merge evidence
        existing = state.nodes[nid]
        for eid in node.get("evidence_chunk_ids", []):
            if eid not in existing["evidence_chunk_ids"]:
                existing["evidence_chunk_ids"].append(eid)
        for sid in node.get("source_ids", []):
            if sid not in existing["source_ids"]:
                existing["source_ids"].append(sid)
        # Update confidence (take max)
        existing["confidence"] = max(existing["confidence"], node["confidence"])
        # Merge aliases
        for alias in node.get("aliases", []):
            if alias not in existing["aliases"]:
                existing["aliases"].append(alias)
    else:
        state.nodes[nid] = node


def _add_edge(state: BuildState, edge: dict[str, Any], config: ImplGraphConfig) -> None:
    """Add or merge an edge into the state."""
    if len(state.edges) >= config.max_edges:
        return
    eid = edge["edge_id"]
    # Verify both endpoints exist
    if edge["source_node_id"] not in state.nodes:
        return
    if edge["target_node_id"] not in state.nodes:
        return
    if eid in state.edges:
        existing = state.edges[eid]
        for evid in edge.get("evidence_chunk_ids", []):
            if evid not in existing["evidence_chunk_ids"]:
                existing["evidence_chunk_ids"].append(evid)
        for sid in edge.get("source_ids", []):
            if sid not in existing["source_ids"]:
                existing["source_ids"].append(sid)
        existing["confidence"] = max(existing["confidence"], edge["confidence"])
    else:
        state.edges[eid] = edge


# ============================================================================
# DDL Parsing Patterns
# ============================================================================

# Match CREATE TABLE "SCHEMA"."TABLE_NAME" or CREATE TABLE TABLE_NAME
CREATE_TABLE_PATTERN = re.compile(
    r'CREATE\s+TABLE\s+(?:"[^"]*"\s*\.\s*)?"?([A-Za-z_][A-Za-z0-9_]*)"?\s*\(',
    re.IGNORECASE,
)

# Match column definitions: "COL_NAME" TYPE or COL_NAME TYPE
COLUMN_DEF_PATTERN = re.compile(
    r'^\s*"?([A-Za-z_][A-Za-z0-9_]*)"?\s+(VARCHAR2?|NUMBER|DATE|TIMESTAMP|CHAR|CLOB|BLOB|INT|INTEGER|FLOAT|DECIMAL|NVARCHAR)',
    re.IGNORECASE | re.MULTILINE,
)

# Match Java class declarations
JAVA_CLASS_PATTERN = re.compile(
    r'(?:public|private|protected)?\s*(?:abstract\s+)?class\s+([A-Z][A-Za-z0-9_]+)',
)

# Match Java method declarations
JAVA_METHOD_PATTERN = re.compile(
    r'(?:public|private|protected)\s+(?:static\s+)?(?:synchronized\s+)?'
    r'(?:[\w<>\[\], ]+)\s+([a-z][A-Za-z0-9_]*)\s*\(',
)

# Match Java package declaration
JAVA_PACKAGE_PATTERN = re.compile(r'package\s+([\w.]+)\s*;')

# Match Java imports for detecting dependencies
JAVA_IMPORT_PATTERN = re.compile(r'import\s+([\w.]+)\s*;')

# Match table references in SQL statements (FROM, JOIN, INTO, UPDATE)
SQL_TABLE_REF_PATTERN = re.compile(
    r'(?:FROM|JOIN|INTO|UPDATE|DELETE\s+FROM)\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
    re.IGNORECASE,
)


# ============================================================================
# Heuristic Extraction: System & Module
# ============================================================================

def _extract_system_node(
    config: ImplGraphConfig,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create the top-level System node for Murata MDW."""
    evidence_ids = []
    source_ids = set()
    for chunk in candidates[:10]:
        evidence_ids.append(chunk["chunk_id"])
        source_ids.add(chunk.get("document_id", ""))
        if len(evidence_ids) >= 5:
            break

    return _create_node(
        label="System",
        name="murata mdw",
        display_name=config.system_name,
        description="村田MDW支払依頼/付款申请 — Enterprise Payment Processing System",
        aliases=["Murata MDW", "muratapr", "MDW Payment System", "村田MDW支付系统"],
        source_ids=list(source_ids)[:5],
        evidence_chunk_ids=evidence_ids[:5],
        confidence=1.0,
        config=config,
    )


def _extract_modules(
    candidates: list[dict[str, Any]],
    config: ImplGraphConfig,
) -> list[dict[str, Any]]:
    """Extract Module nodes from Java package structure."""
    # Identify modules from package paths
    module_evidence: dict[str, list[str]] = defaultdict(list)
    module_sources: dict[str, set] = defaultdict(set)

    # Known modules from Java package structure
    known_modules = {
        "payment": ("支払管理モジュール", "Payment Module"),
        "receiging": ("入金管理モジュール", "Receiving Module"),
        "system": ("システム管理モジュール", "System Administration Module"),
        "common": ("共通モジュール", "Common Module"),
        "base": ("基盤モジュール", "Base Framework Module"),
    }

    for chunk in candidates:
        source_path = chunk.get("source_path", "")
        text = chunk.get("text", "")

        # Detect module from path patterns
        if "/com/hulftchina/" in source_path:
            # Extract module from path: com/hulftchina/{layer}/{module}/
            parts = source_path.split("/com/hulftchina/")
            if len(parts) > 1:
                sub_parts = parts[1].split("/")
                if len(sub_parts) >= 2:
                    # layer = sub_parts[0]  # action, service, model, dao, util
                    module_name = sub_parts[1] if sub_parts[0] in ("action", "service", "model", "dao") else sub_parts[0]
                    if module_name in known_modules:
                        module_evidence[module_name].append(chunk["chunk_id"])
                        module_sources[module_name].add(chunk.get("document_id", ""))

        # Also detect from package declarations
        pkg_match = JAVA_PACKAGE_PATTERN.search(text)
        if pkg_match:
            pkg = pkg_match.group(1)
            for mod_name in known_modules:
                if f".{mod_name}" in pkg or pkg.endswith(f".{mod_name}"):
                    module_evidence[mod_name].append(chunk["chunk_id"])
                    module_sources[mod_name].add(chunk.get("document_id", ""))

    nodes = []
    for mod_name, (jp_name, en_name) in known_modules.items():
        if mod_name in module_evidence:
            ev_ids = list(dict.fromkeys(module_evidence[mod_name]))[:10]
            src_ids = list(module_sources[mod_name])[:5]
            nodes.append(_create_node(
                label="Module",
                name=mod_name,
                display_name=jp_name,
                description=f"{jp_name} ({en_name})",
                aliases=[en_name, mod_name],
                source_ids=src_ids,
                evidence_chunk_ids=ev_ids,
                confidence=0.9,
                config=config,
            ))

    return nodes


# ============================================================================
# Heuristic Extraction: Tables & Columns
# ============================================================================

def _extract_tables_and_columns(
    candidates: list[dict[str, Any]],
    config: ImplGraphConfig,
    state: BuildState,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract Table and Column nodes from DDL chunks."""
    table_nodes: list[dict[str, Any]] = []
    column_nodes: list[dict[str, Any]] = []

    # Track tables we've already created
    seen_tables: set[str] = set()

    for chunk in candidates:
        text = chunk.get("text", "")
        chunk_id = chunk.get("chunk_id", "")
        doc_id = chunk.get("document_id", "")

        # Find CREATE TABLE statements
        for match in CREATE_TABLE_PATTERN.finditer(text):
            table_name = match.group(1).upper()

            if table_name in seen_tables:
                # Just add evidence to existing
                node_id = GraphNode.generate_id(config.layer, "Table", table_name.lower())
                if node_id in state.nodes:
                    if chunk_id not in state.nodes[node_id]["evidence_chunk_ids"]:
                        state.nodes[node_id]["evidence_chunk_ids"].append(chunk_id)
                continue

            seen_tables.add(table_name)

            table_node = _create_node(
                label="Table",
                name=table_name.lower(),
                display_name=table_name,
                description=f"Database table: {table_name}",
                confidence=0.95,
                source_ids=[doc_id],
                evidence_chunk_ids=[chunk_id],
                config=config,
            )
            table_nodes.append(table_node)

            # Extract columns from the CREATE TABLE block
            # Find the block after this CREATE TABLE
            start_pos = match.start()
            # Find matching closing paren (rough)
            paren_depth = 0
            block_end = start_pos
            for i in range(match.end(), min(len(text), match.end() + 3000)):
                if text[i] == '(':
                    paren_depth += 1
                elif text[i] == ')':
                    if paren_depth == 0:
                        block_end = i
                        break
                    paren_depth -= 1

            if block_end > start_pos:
                block = text[match.end():block_end]
                col_count = 0
                for col_match in COLUMN_DEF_PATTERN.finditer(block):
                    if col_count >= config.max_columns_per_table:
                        break
                    col_name = col_match.group(1).upper()
                    col_type = col_match.group(2).upper()

                    # Skip common Oracle storage keywords that get misdetected
                    if col_name in ("TABLESPACE", "LOGGING", "NOCOMPRESS", "STORAGE",
                                    "INITIAL", "NEXT", "PCTFREE", "INITRANS",
                                    "BUFFER_POOL", "PARALLEL", "NOCACHE"):
                        continue

                    col_node = _create_node(
                        label="Column",
                        name=f"{table_name.lower()}.{col_name.lower()}",
                        display_name=f"{table_name}.{col_name}",
                        description=f"Column {col_name} ({col_type}) in table {table_name}",
                        properties={"data_type": col_type, "table": table_name},
                        source_ids=[doc_id],
                        evidence_chunk_ids=[chunk_id],
                        confidence=0.9,
                        config=config,
                    )
                    column_nodes.append(col_node)
                    col_count += 1
                    state.columns_per_table[table_name] += 1

    return table_nodes, column_nodes


# ============================================================================
# Heuristic Extraction: Files, Classes, Methods
# ============================================================================

def _extract_code_entities(
    candidates: list[dict[str, Any]],
    config: ImplGraphConfig,
    state: BuildState,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract File, Class, Method, and Service nodes from source code."""
    file_nodes: list[dict[str, Any]] = []
    class_nodes: list[dict[str, Any]] = []
    method_nodes: list[dict[str, Any]] = []
    service_nodes: list[dict[str, Any]] = []

    seen_files: set[str] = set()
    seen_classes: set[str] = set()
    seen_methods: set[str] = set()

    for chunk in candidates:
        source_path = chunk.get("source_path", "")
        text = chunk.get("text", "")
        chunk_id = chunk.get("chunk_id", "")
        doc_id = chunk.get("document_id", "")
        doc_type = chunk.get("doc_type", "")

        if doc_type != "source_code":
            continue

        # Extract File node
        if source_path and source_path not in seen_files:
            seen_files.add(source_path)
            filename = source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path
            file_node = _create_node(
                label="File",
                name=source_path.lower(),
                display_name=filename,
                description=f"Source file: {source_path}",
                properties={"path": source_path, "language": "java"},
                source_ids=[doc_id],
                evidence_chunk_ids=[chunk_id],
                confidence=0.95,
                config=config,
            )
            file_nodes.append(file_node)

        # Extract Class nodes
        for class_match in JAVA_CLASS_PATTERN.finditer(text):
            class_name = class_match.group(1)
            if class_name in seen_classes:
                # Merge evidence
                node_id = GraphNode.generate_id(config.layer, "Class", class_name.lower())
                if node_id in state.nodes:
                    if chunk_id not in state.nodes[node_id]["evidence_chunk_ids"]:
                        state.nodes[node_id]["evidence_chunk_ids"].append(chunk_id)
                continue

            seen_classes.add(class_name)

            # Determine if it's a Service
            is_service = (
                class_name.endswith("ServiceImpl")
                or class_name.endswith("Service")
                or "Service" in class_name
            )

            if is_service:
                svc_node = _create_node(
                    label="Service",
                    name=class_name.lower(),
                    display_name=class_name,
                    description=f"Service: {class_name}",
                    properties={"source_file": source_path},
                    source_ids=[doc_id],
                    evidence_chunk_ids=[chunk_id],
                    confidence=0.9,
                    config=config,
                )
                service_nodes.append(svc_node)
            else:
                cls_node = _create_node(
                    label="Class",
                    name=class_name.lower(),
                    display_name=class_name,
                    description=f"Java class: {class_name}",
                    properties={"source_file": source_path},
                    source_ids=[doc_id],
                    evidence_chunk_ids=[chunk_id],
                    confidence=0.9,
                    config=config,
                )
                class_nodes.append(cls_node)

        # Extract Method nodes (only named methods, skip constructors/getters/setters)
        for method_match in JAVA_METHOD_PATTERN.finditer(text):
            method_name = method_match.group(1)

            # Skip trivial methods
            if method_name.startswith(("get", "set", "is", "toString", "hashCode", "equals")):
                continue
            if method_name in ("main", "init", "destroy"):
                continue

            # Scope method to its class context
            class_context = ""
            for cls in seen_classes:
                if cls.lower() in source_path.lower():
                    class_context = cls
                    break

            method_key = f"{class_context}.{method_name}" if class_context else method_name
            if method_key in seen_methods:
                continue
            seen_methods.add(method_key)

            if class_context:
                state.methods_per_class[class_context] += 1
                if state.methods_per_class[class_context] > config.max_methods_per_class:
                    continue

            meth_node = _create_node(
                label="Method",
                name=method_key.lower(),
                display_name=f"{class_context}.{method_name}()" if class_context else f"{method_name}()",
                description=f"Method: {method_name} in {class_context or 'unknown class'}",
                properties={"class": class_context, "source_file": source_path},
                source_ids=[doc_id],
                evidence_chunk_ids=[chunk_id],
                confidence=0.85,
                config=config,
            )
            method_nodes.append(meth_node)

    return file_nodes, class_nodes, method_nodes, service_nodes


# ============================================================================
# Heuristic Extraction: SQL File Nodes
# ============================================================================

def _extract_sql_nodes(
    candidates: list[dict[str, Any]],
    config: ImplGraphConfig,
) -> list[dict[str, Any]]:
    """Extract SQL file/script nodes from SQL source files."""
    sql_nodes: list[dict[str, Any]] = []
    seen_sql_files: set[str] = set()

    for chunk in candidates:
        source_path = chunk.get("source_path", "")
        doc_type = chunk.get("doc_type", "")
        chunk_id = chunk.get("chunk_id", "")
        doc_id = chunk.get("document_id", "")

        if doc_type != "database_doc":
            continue

        # Create a SQL node for each unique SQL file
        filename = source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path
        if not filename.lower().endswith((".sql", ".txt")):
            continue
        if filename in seen_sql_files:
            continue
        seen_sql_files.add(filename)

        sql_node = _create_node(
            label="SQL",
            name=filename.lower(),
            display_name=filename,
            description=f"SQL script: {filename}",
            properties={"path": source_path},
            source_ids=[doc_id],
            evidence_chunk_ids=[chunk_id],
            confidence=0.85,
            config=config,
        )
        sql_nodes.append(sql_node)

    return sql_nodes


# ============================================================================
# Heuristic Extraction: Config Nodes
# ============================================================================

def _extract_config_nodes(
    candidates: list[dict[str, Any]],
    config: ImplGraphConfig,
) -> list[dict[str, Any]]:
    """Extract Config nodes from configuration files."""
    config_nodes: list[dict[str, Any]] = []
    seen_configs: set[str] = set()

    for chunk in candidates:
        doc_type = chunk.get("doc_type", "")
        chunk_type = chunk.get("chunk_type", "")
        source_path = chunk.get("source_path", "")
        chunk_id = chunk.get("chunk_id", "")
        doc_id = chunk.get("document_id", "")

        if doc_type != "config" and chunk_type != "config":
            continue

        filename = source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path
        if filename in seen_configs:
            continue
        seen_configs.add(filename)

        cfg_node = _create_node(
            label="Config",
            name=filename.lower(),
            display_name=filename,
            description=f"Configuration file: {filename}",
            properties={"path": source_path},
            source_ids=[doc_id],
            evidence_chunk_ids=[chunk_id],
            confidence=0.85,
            config=config,
        )
        config_nodes.append(cfg_node)

    return config_nodes


# ============================================================================
# Edge Building
# ============================================================================

def _build_edges(
    state: BuildState,
    config: ImplGraphConfig,
    candidates: list[dict[str, Any]],
) -> None:
    """Build edges between nodes based on structural relationships."""

    # Precompute node lookups
    system_node_id = GraphNode.generate_id(config.layer, "System", "murata mdw")
    nodes_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in state.nodes.values():
        nodes_by_label[node["label"]].append(node)

    # 1. System CONTAINS Module
    for mod_node in nodes_by_label.get("Module", []):
        edge = _create_edge(
            source_node_id=system_node_id,
            target_node_id=mod_node["node_id"],
            relation_type="CONTAINS",
            description=f"System contains module: {mod_node['display_name']}",
            source_ids=mod_node["source_ids"][:2],
            evidence_chunk_ids=mod_node["evidence_chunk_ids"][:2],
            confidence=0.95,
            config=config,
        )
        _add_edge(state, edge, config)

    # 2. Module CONTAINS File (based on path structure)
    module_node_map = {}
    for mod_node in nodes_by_label.get("Module", []):
        module_node_map[mod_node["name"]] = mod_node["node_id"]

    for file_node in nodes_by_label.get("File", []):
        file_path = file_node.get("properties", {}).get("path", "")
        # Determine which module this file belongs to
        assigned_module = None
        for mod_name in module_node_map:
            if f"/{mod_name}/" in file_path.lower() or file_path.lower().endswith(f"/{mod_name}"):
                assigned_module = mod_name
                break

        if assigned_module and assigned_module in module_node_map:
            edge = _create_edge(
                source_node_id=module_node_map[assigned_module],
                target_node_id=file_node["node_id"],
                relation_type="CONTAINS",
                description=f"Module {assigned_module} contains {file_node['display_name']}",
                source_ids=file_node["source_ids"][:1],
                evidence_chunk_ids=file_node["evidence_chunk_ids"][:1],
                confidence=0.85,
                config=config,
            )
            _add_edge(state, edge, config)

    # 3. File CONTAINS Class/Service
    file_node_map = {}
    for file_node in nodes_by_label.get("File", []):
        path = file_node.get("properties", {}).get("path", "")
        file_node_map[path.lower()] = file_node["node_id"]

    for cls_node in nodes_by_label.get("Class", []) + nodes_by_label.get("Service", []):
        src_file = cls_node.get("properties", {}).get("source_file", "").lower()
        if src_file in file_node_map:
            edge = _create_edge(
                source_node_id=file_node_map[src_file],
                target_node_id=cls_node["node_id"],
                relation_type="CONTAINS",
                description=f"File contains {cls_node['display_name']}",
                source_ids=cls_node["source_ids"][:1],
                evidence_chunk_ids=cls_node["evidence_chunk_ids"][:1],
                confidence=0.9,
                config=config,
            )
            _add_edge(state, edge, config)

    # 4. Class/Service HAS_METHOD Method
    for meth_node in nodes_by_label.get("Method", []):
        class_name = meth_node.get("properties", {}).get("class", "")
        if class_name:
            # Find the class or service node
            class_node_id = GraphNode.generate_id(config.layer, "Class", class_name.lower())
            service_node_id = GraphNode.generate_id(config.layer, "Service", class_name.lower())
            target_id = None
            if class_node_id in state.nodes:
                target_id = class_node_id
            elif service_node_id in state.nodes:
                target_id = service_node_id

            if target_id:
                edge = _create_edge(
                    source_node_id=target_id,
                    target_node_id=meth_node["node_id"],
                    relation_type="HAS_METHOD",
                    description=f"{class_name} has method {meth_node['display_name']}",
                    source_ids=meth_node["source_ids"][:1],
                    evidence_chunk_ids=meth_node["evidence_chunk_ids"][:1],
                    confidence=0.85,
                    config=config,
                )
                _add_edge(state, edge, config)

    # 5. Table HAS_COLUMN Column
    for col_node in nodes_by_label.get("Column", []):
        table_name = col_node.get("properties", {}).get("table", "")
        if table_name:
            table_node_id = GraphNode.generate_id(config.layer, "Table", table_name.lower())
            if table_node_id in state.nodes:
                edge = _create_edge(
                    source_node_id=table_node_id,
                    target_node_id=col_node["node_id"],
                    relation_type="HAS_COLUMN",
                    description=f"{table_name} has column {col_node['display_name']}",
                    source_ids=col_node["source_ids"][:1],
                    evidence_chunk_ids=col_node["evidence_chunk_ids"][:1],
                    confidence=0.9,
                    config=config,
                )
                _add_edge(state, edge, config)

    # 6. SQL READS/WRITES Table (detect from SQL text)
    for chunk in candidates:
        text = chunk.get("text", "")
        doc_type = chunk.get("doc_type", "")
        source_path = chunk.get("source_path", "")
        chunk_id = chunk.get("chunk_id", "")

        if doc_type != "database_doc":
            continue

        filename = source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path
        sql_node_id = GraphNode.generate_id(config.layer, "SQL", filename.lower())
        if sql_node_id not in state.nodes:
            continue

        # Find table references
        for ref_match in SQL_TABLE_REF_PATTERN.finditer(text):
            ref_table = ref_match.group(1).upper()
            table_node_id = GraphNode.generate_id(config.layer, "Table", ref_table.lower())
            if table_node_id not in state.nodes:
                continue

            # Determine READS or WRITES
            prefix = text[max(0, ref_match.start()-20):ref_match.start()].upper()
            if "INSERT" in prefix or "UPDATE" in prefix or "DELETE" in prefix:
                rel = "WRITES"
            else:
                rel = "READS"

            edge = _create_edge(
                source_node_id=sql_node_id,
                target_node_id=table_node_id,
                relation_type=rel,
                description=f"SQL {filename} {rel.lower()} {ref_table}",
                source_ids=[chunk.get("document_id", "")],
                evidence_chunk_ids=[chunk_id],
                confidence=0.8,
                config=config,
            )
            _add_edge(state, edge, config)

    # 7. Module HAS_TABLE (assign tables to modules based on naming conventions)
    payment_tables = {"PAYMENT_REQ", "PAYMENT_RECEIVING", "V_PAYMENT_REQ_FILE", "V_PAYMENT_RECEIVING"}
    receiving_tables = {"RECEIVING_JOURNAL", "RECEIVING_LIST", "JOURNAL_BASE", "V_BASE_LIST_JOURNAL"}
    system_tables = {"HULFTRESOURCE", "HULFTUSER", "HULFTROLE", "HULFTROLERES", "HULFTCITY"}

    table_to_module = {}
    for t in payment_tables:
        table_to_module[t.lower()] = "payment"
    for t in receiving_tables:
        table_to_module[t.lower()] = "receiging"
    for t in system_tables:
        table_to_module[t.lower()] = "system"

    for table_node in nodes_by_label.get("Table", []):
        table_name_lower = table_node["name"]
        mod_name = table_to_module.get(table_name_lower)
        if mod_name and mod_name in module_node_map:
            edge = _create_edge(
                source_node_id=module_node_map[mod_name],
                target_node_id=table_node["node_id"],
                relation_type="HAS_TABLE",
                description=f"Module {mod_name} has table {table_node['display_name']}",
                source_ids=table_node["source_ids"][:1],
                evidence_chunk_ids=table_node["evidence_chunk_ids"][:1],
                confidence=0.8,
                config=config,
            )
            _add_edge(state, edge, config)


# ============================================================================
# Main Build Function
# ============================================================================

def build_implementation_graph(
    candidates: list[dict[str, Any]],
    documents: list[dict[str, Any]] | None = None,
    sections: list[dict[str, Any]] | None = None,
    *,
    config: ImplGraphConfig | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the implementation graph from candidate evidence chunks.

    Returns:
        (nodes, edges, rejected_items)
    """
    cfg = config or ImplGraphConfig()
    state = BuildState()

    logger.info(f"Building implementation graph from {len(candidates)} candidate chunks")

    # 1. System node
    system_node = _extract_system_node(cfg, candidates)
    _add_node(state, system_node, cfg)

    # 2. Module nodes
    module_nodes = _extract_modules(candidates, cfg)
    for node in module_nodes:
        _add_node(state, node, cfg)
    logger.info(f"  Extracted {len(module_nodes)} module nodes")

    # 3. Tables & columns from DDL
    table_nodes, column_nodes = _extract_tables_and_columns(candidates, cfg, state)
    for node in table_nodes:
        _add_node(state, node, cfg)
    for node in column_nodes:
        _add_node(state, node, cfg)
    logger.info(f"  Extracted {len(table_nodes)} table nodes, {len(column_nodes)} column nodes")

    # 4. Code entities: Files, Classes, Methods, Services
    file_nodes, class_nodes, method_nodes, service_nodes = _extract_code_entities(
        candidates, cfg, state
    )
    for node in file_nodes:
        _add_node(state, node, cfg)
    for node in class_nodes:
        _add_node(state, node, cfg)
    for node in method_nodes:
        _add_node(state, node, cfg)
    for node in service_nodes:
        _add_node(state, node, cfg)
    logger.info(
        f"  Extracted {len(file_nodes)} file, {len(class_nodes)} class, "
        f"{len(method_nodes)} method, {len(service_nodes)} service nodes"
    )

    # 5. SQL file nodes
    sql_nodes = _extract_sql_nodes(candidates, cfg)
    for node in sql_nodes:
        _add_node(state, node, cfg)
    logger.info(f"  Extracted {len(sql_nodes)} SQL nodes")

    # 6. Config nodes
    config_nodes = _extract_config_nodes(candidates, cfg)
    for node in config_nodes:
        _add_node(state, node, cfg)
    logger.info(f"  Extracted {len(config_nodes)} config nodes")

    # 7. Build edges
    _build_edges(state, cfg, candidates)
    logger.info(f"  Built {len(state.edges)} edges")

    # Final results
    all_nodes = list(state.nodes.values())
    all_edges = list(state.edges.values())

    logger.info(
        f"Implementation graph complete: {len(all_nodes)} nodes, "
        f"{len(all_edges)} edges, {len(state.rejected)} rejected"
    )

    return all_nodes, all_edges, state.rejected


# ============================================================================
# Output Functions
# ============================================================================

def save_graph_outputs(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    output_dir: Path,
) -> None:
    """Save implementation graph outputs to JSONL files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = output_dir / "implementation_nodes.jsonl"
    edges_path = output_dir / "implementation_edges.jsonl"
    rejected_path = output_dir / "rejected_implementation_graph_items.jsonl"

    with open(nodes_path, "w", encoding="utf-8") as f:
        for node in nodes:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    with open(edges_path, "w", encoding="utf-8") as f:
        for edge in edges:
            f.write(json.dumps(edge, ensure_ascii=False) + "\n")

    with open(rejected_path, "w", encoding="utf-8") as f:
        for item in rejected:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    logger.info(
        f"Saved: {len(nodes)} nodes to {nodes_path}, "
        f"{len(edges)} edges to {edges_path}, "
        f"{len(rejected)} rejected to {rejected_path}"
    )
