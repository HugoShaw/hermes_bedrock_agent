"""Extract graph entities from chunks and load into Neptune Analytics."""

from __future__ import annotations

import logging
import re
from typing import Optional

from ..config import Config, config as _default_config
from .schemas import Chunk, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

_KNOWN_SYSTEMS = {
    "SAP": "SAP S/4HANA", "S4/HANA": "SAP S/4HANA", "S4HANA": "SAP S/4HANA",
    "DataSpider": "DataSpider (NTT DATA)", "ANDPAD": "ANDPAD",
    "中間F": "中間ファイル (Intermediate File)", "中間ファイル": "中間ファイル (Intermediate File)",
}

_SYSTEM_CANONICAL = {
    "SAP": "SAP", "S4/HANA": "SAP", "S4HANA": "SAP",
    "DataSpider": "DataSpider", "ANDPAD": "ANDPAD",
    "中間F": "IntermediateFile", "中間ファイル": "IntermediateFile",
}


def _safe_node_id(label: str, name: str) -> str:
    clean = re.sub(r"[^\w]", "_", name)
    return f"{label}_{clean}"[:128]


def extract_entities(chunk: Chunk) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    pdf_path = chunk.source_pdf_s3_path

    sheet_node_id = _safe_node_id("Sheet", f"{chunk.sheet_index:02d}_{chunk.sheet_name}")
    nodes.append(GraphNode(
        node_id=sheet_node_id, label="Sheet", name=chunk.sheet_name,
        properties={"sheet_index": chunk.sheet_index, "workbook_name": chunk.workbook_name, "chunk_type": chunk.chunk_type},
        evidence_pdf_s3_path=pdf_path,
    ))

    system_node_ids: list[str] = []
    for sys_kw in chunk.systems:
        canonical = _SYSTEM_CANONICAL.get(sys_kw, sys_kw)
        sys_node_id = _safe_node_id("System", canonical)
        nodes.append(GraphNode(
            node_id=sys_node_id, label="System", name=canonical,
            properties={"display_name": _KNOWN_SYSTEMS.get(sys_kw, sys_kw)},
            evidence_pdf_s3_path=pdf_path,
        ))
        system_node_ids.append(sys_node_id)
        edges.append(GraphEdge(
            from_id=sheet_node_id, to_id=sys_node_id, relationship="DEFINED_IN",
            properties={"chunk_id": chunk.chunk_id}, evidence_pdf_s3_path=pdf_path,
        ))

    if chunk.chunk_type == "mapping_table" and len(system_node_ids) >= 2:
        for i in range(len(system_node_ids) - 1):
            flow_name = f"{system_node_ids[i]}_to_{system_node_ids[i+1]}"
            flow_node_id = _safe_node_id("DataFlow", flow_name)
            nodes.append(GraphNode(
                node_id=flow_node_id, label="DataFlow", name=flow_name,
                properties={"sheet_index": chunk.sheet_index, "chunk_id": chunk.chunk_id},
                evidence_pdf_s3_path=pdf_path,
            ))
            edges.append(GraphEdge(
                from_id=system_node_ids[i], to_id=system_node_ids[i + 1], relationship="FLOWS_TO",
                properties={"via": flow_node_id, "sheet_index": chunk.sheet_index},
                evidence_pdf_s3_path=pdf_path,
            ))

    for api_name in chunk.apis:
        api_node_id = _safe_node_id("API", api_name)
        nodes.append(GraphNode(
            node_id=api_node_id, label="API", name=api_name,
            properties={"sheet_index": chunk.sheet_index},
            evidence_pdf_s3_path=pdf_path,
        ))
        edges.append(GraphEdge(
            from_id=sheet_node_id, to_id=api_node_id, relationship="CALLS_API",
            properties={"chunk_id": chunk.chunk_id}, evidence_pdf_s3_path=pdf_path,
        ))

    for field_name in chunk.fields[:10]:
        field_node_id = _safe_node_id("Field", f"{chunk.sheet_index:02d}_{field_name}")
        nodes.append(GraphNode(
            node_id=field_node_id, label="Field", name=field_name,
            properties={"sheet_index": chunk.sheet_index, "sheet_name": chunk.sheet_name},
            evidence_pdf_s3_path=pdf_path,
        ))
        edges.append(GraphEdge(
            from_id=sheet_node_id, to_id=field_node_id, relationship="MAPS_TO",
            properties={"chunk_id": chunk.chunk_id}, evidence_pdf_s3_path=pdf_path,
        ))

    if chunk.chunk_type in ("mapping_table", "business_rule", "data_condition"):
        rule_label = "MappingRule" if chunk.chunk_type == "mapping_table" else "BusinessRule"
        rule_node_id = _safe_node_id(rule_label, chunk.chunk_id)
        nodes.append(GraphNode(
            node_id=rule_node_id, label=rule_label, name=chunk.chunk_id,
            properties={"content_preview": chunk.content[:200], "sheet_index": chunk.sheet_index},
            evidence_pdf_s3_path=pdf_path,
        ))
        rel = "TRANSFORMS" if chunk.chunk_type == "mapping_table" else "HAS_CONDITION"
        edges.append(GraphEdge(
            from_id=sheet_node_id, to_id=rule_node_id, relationship=rel,
            properties={"chunk_id": chunk.chunk_id}, evidence_pdf_s3_path=pdf_path,
        ))

    for related_idx in chunk.related_sheets[:5]:
        related_node_id = _safe_node_id("Sheet", f"{related_idx:02d}_")
        edges.append(GraphEdge(
            from_id=sheet_node_id, to_id=related_node_id, relationship="FLOWS_TO",
            properties={"source": "cross_sheet_summary"}, evidence_pdf_s3_path=pdf_path,
        ))

    return nodes, edges
