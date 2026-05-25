"""
Excel mapping extractor — extract field mapping nodes and edges from
field_mapping_sheet evidence (SAP ↔ 中間F ↔ Andpad).

Heuristics:
- Mapping sheets have dual-column structure: source fields (left) and target fields (right)
- Row 21-like rows define header columns (No, 項目名称, 変数, Type, 長さ, etc.)
- Subsequent rows contain actual field data
- Sheet name encodes direction: SAP→中間F, 中間F→Andpad, etc.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Patterns to detect source/target systems from sheet names
SYSTEM_PATTERNS = {
    "SAP": re.compile(r"SAP", re.IGNORECASE),
    "中間F": re.compile(r"中間F|中間フォーマット"),
    "Andpad": re.compile(r"Andpad|ANDPAD"),
    "DataSpider": re.compile(r"DataSpider|D/S|DS"),
}

# Direction patterns in sheet names
DIRECTION_PATTERN = re.compile(r"[（(](.+?)→(.+?)[）)]")

# Known SAP-side header keywords
SAP_HEADER_KEYS = {"No", "項目名称", "変数", "Type", "長さ", "長さ(Byte)", "マイナス値有無", "データ例", "備考"}

# Known target-side header keywords
TARGET_HEADER_KEYS = {"No", "項目名称", "変数", "Type", "必須", "長さ(文字数)", "備考"}

# Generic/rejected field names
GENERIC_FIELD_NAMES = {"", "ー", "-", "—", "※", "N/A", "なし", "None", "null"}


@dataclass
class MappingField:
    """A single field in a mapping."""
    field_no: str = ""
    field_name: str = ""
    variable: str = ""
    data_type: str = ""
    length: str = ""
    required: str = ""
    description: str = ""
    system: str = ""
    source_cell_refs: dict[str, str] = field(default_factory=dict)


@dataclass
class FieldMapping:
    """A source→target field mapping."""
    source_field: MappingField
    target_field: MappingField
    sheet_name: str = ""
    row_number: int = 0
    confidence: float = 0.7
    evidence_chunk_ids: list[str] = field(default_factory=list)


class ExcelMappingExtractor:
    """Extract field mapping graph nodes and edges from Excel evidence.

    Processes field_mapping_sheet chunks to identify:
    - Systems (SAP, 中間F, Andpad, DataSpider)
    - Messages/Files (interface files, intermediate formats)
    - Columns/Fields (individual data items)
    - MAPS_TO relationships between source and target fields
    """

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id
        self.nodes: list[dict] = []
        self.edges: list[dict] = []
        self.rejected: list[dict] = []
        self.low_confidence: list[dict] = []
        self._system_nodes: dict[str, dict] = {}
        self._message_nodes: dict[str, dict] = {}
        self._column_nodes: dict[str, dict] = {}

    def _make_node_id(self, label: str, name: str, context: str = "") -> str:
        """Generate deterministic node_id."""
        raw = f"{self.dataset}:{label}:{name}:{context}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _make_edge_id(self, src: str, tgt: str, rel: str) -> str:
        """Generate deterministic edge_id."""
        raw = f"{self.dataset}:{src}:{tgt}:{rel}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _detect_direction(self, sheet_name: str) -> tuple[str, str]:
        """Detect source and target system from sheet name."""
        match = DIRECTION_PATTERN.search(sheet_name)
        if match:
            src_sys = match.group(1).strip()
            tgt_sys = match.group(2).strip()
            # Normalize
            for canonical, pattern in SYSTEM_PATTERNS.items():
                if pattern.search(src_sys):
                    src_sys = canonical
                if pattern.search(tgt_sys):
                    tgt_sys = canonical
            return src_sys, tgt_sys
        # Fallback: try detecting systems mentioned
        systems_found = []
        for canonical, pattern in SYSTEM_PATTERNS.items():
            if pattern.search(sheet_name):
                systems_found.append(canonical)
        if len(systems_found) >= 2:
            return systems_found[0], systems_found[1]
        return "Unknown", "Unknown"

    def _detect_operation(self, sheet_name: str) -> str:
        """Detect operation type from sheet name."""
        ops = {
            "登録": "register",
            "変更": "update",
            "取消": "cancel",
            "キャンセル": "cancel",
            "削除": "delete",
            "取得": "get",
            "編集": "edit",
            "ステータス変更": "status_change",
        }
        for jp, en in ops.items():
            if jp in sheet_name:
                return en
        return "unknown"

    def _get_or_create_system(
        self, name: str, evidence_chunk_ids: list[str]
    ) -> dict:
        """Get or create a System node."""
        if name in self._system_nodes:
            # Merge evidence
            existing = self._system_nodes[name]
            for eid in evidence_chunk_ids:
                if eid not in existing["evidence_chunk_ids"]:
                    existing["evidence_chunk_ids"].append(eid)
            return existing

        node_id = self._make_node_id("System", name)
        node = {
            "node_id": node_id,
            "label": "System",
            "name": name.lower().replace(" ", "_").replace("／", "_"),
            "display_name": name,
            "layer": "implementation",
            "aliases": [],
            "description": f"System: {name}",
            "properties": {
                "extraction_method": "excel_sheet_name_heuristic",
            },
            "source_ids": [],
            "evidence_chunk_ids": list(evidence_chunk_ids),
            "confidence": 0.9,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }
        self._system_nodes[name] = node
        self.nodes.append(node)
        return node

    def _get_or_create_message(
        self,
        name: str,
        system: str,
        sheet_name: str,
        operation: str,
        evidence_chunk_ids: list[str],
    ) -> dict:
        """Get or create a Message node (interface file/format)."""
        key = f"{system}:{name}:{operation}"
        if key in self._message_nodes:
            existing = self._message_nodes[key]
            for eid in evidence_chunk_ids:
                if eid not in existing["evidence_chunk_ids"]:
                    existing["evidence_chunk_ids"].append(eid)
            return existing

        node_id = self._make_node_id("Message", name, f"{system}:{operation}")
        node = {
            "node_id": node_id,
            "label": "Message",
            "name": name.lower().replace(" ", "_").replace("／", "_"),
            "display_name": name,
            "layer": "implementation",
            "aliases": [],
            "description": f"Interface message/file: {name} ({system}, {operation})",
            "properties": {
                "system": system,
                "operation": operation,
                "sheet_name": sheet_name,
                "extraction_method": "excel_mapping_heuristic",
            },
            "source_ids": [],
            "evidence_chunk_ids": list(evidence_chunk_ids),
            "confidence": 0.75,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }
        self._message_nodes[key] = node
        self.nodes.append(node)
        return node

    def _create_column_node(
        self,
        field: MappingField,
        parent_message: str,
        sheet_name: str,
        evidence_chunk_ids: list[str],
    ) -> dict | None:
        """Create a Column node for a field."""
        if not field.field_name or field.field_name in GENERIC_FIELD_NAMES:
            return None

        # Dedup key
        key = f"{parent_message}:{field.system}:{field.field_name}"
        if key in self._column_nodes:
            existing = self._column_nodes[key]
            for eid in evidence_chunk_ids:
                if eid not in existing["evidence_chunk_ids"]:
                    existing["evidence_chunk_ids"].append(eid)
            return existing

        node_id = self._make_node_id("Column", field.field_name, f"{parent_message}:{field.system}")
        node = {
            "node_id": node_id,
            "label": "Column",
            "name": field.field_name,
            "display_name": field.field_name,
            "layer": "implementation",
            "aliases": [field.variable] if field.variable and field.variable not in GENERIC_FIELD_NAMES else [],
            "description": f"Field: {field.field_name} (system={field.system}, type={field.data_type})",
            "properties": {
                "system": field.system,
                "parent_message": parent_message,
                "field_no": field.field_no,
                "data_type": field.data_type,
                "length": field.length,
                "required": field.required,
                "variable": field.variable,
                "description": field.description,
                "sheet_name": sheet_name,
                "source_cell_refs": field.source_cell_refs,
                "extraction_method": "excel_field_mapping_row",
            },
            "source_ids": [],
            "evidence_chunk_ids": list(evidence_chunk_ids),
            "confidence": 0.8,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }
        self._column_nodes[key] = node
        self.nodes.append(node)
        return node

    def extract_from_chunks(self, chunks: list[dict]) -> None:
        """Extract implementation graph from field mapping chunks."""
        # Group chunks by sheet
        chunks_by_sheet: dict[str, list[dict]] = {}
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            sheet_type = meta.get("guessed_sheet_type", "")
            if sheet_type == "field_mapping_sheet":
                sheet_name = meta.get("sheet_name", "")
                chunks_by_sheet.setdefault(sheet_name, []).append(chunk)

        logger.info(f"Processing {len(chunks_by_sheet)} field mapping sheets")

        for sheet_name, sheet_chunks in chunks_by_sheet.items():
            self._process_mapping_sheet(sheet_name, sheet_chunks)

    def _process_mapping_sheet(
        self, sheet_name: str, chunks: list[dict]
    ) -> None:
        """Process a single mapping sheet."""
        source_sys, target_sys = self._detect_direction(sheet_name)
        operation = self._detect_operation(sheet_name)

        # Collect chunk IDs for evidence
        chunk_ids = [c["chunk_id"] for c in chunks]

        # Create system nodes
        if source_sys != "Unknown":
            self._get_or_create_system(source_sys, chunk_ids[:2])
        if target_sys != "Unknown":
            self._get_or_create_system(target_sys, chunk_ids[:2])

        # Create message nodes for source and target
        src_msg_name = f"{source_sys}_IF" if source_sys != "Unknown" else sheet_name
        tgt_msg_name = f"{target_sys}_IF" if target_sys != "Unknown" else sheet_name

        src_msg = self._get_or_create_message(
            src_msg_name, source_sys, sheet_name, operation, chunk_ids[:1]
        )
        tgt_msg = self._get_or_create_message(
            tgt_msg_name, target_sys, sheet_name, operation, chunk_ids[:1]
        )

        # Create System CONTAINS Message edges
        if source_sys != "Unknown":
            sys_node = self._system_nodes[source_sys]
            self._create_edge(
                sys_node["node_id"], src_msg["node_id"],
                "CONTAINS", f"{source_sys} contains {src_msg_name}",
                chunk_ids[:1], 0.85,
                {"mapping_type": "system_message", "source_sheet": sheet_name}
            )
        if target_sys != "Unknown":
            sys_node = self._system_nodes[target_sys]
            self._create_edge(
                sys_node["node_id"], tgt_msg["node_id"],
                "CONTAINS", f"{target_sys} contains {tgt_msg_name}",
                chunk_ids[:1], 0.85,
                {"mapping_type": "system_message", "source_sheet": sheet_name}
            )

        # Parse field rows from chunks
        mappings = self._extract_field_mappings_from_chunks(
            chunks, source_sys, target_sys, sheet_name
        )

        for mapping in mappings:
            # Create source column
            src_col = self._create_column_node(
                mapping.source_field, src_msg_name, sheet_name,
                mapping.evidence_chunk_ids
            )
            # Create target column
            tgt_col = self._create_column_node(
                mapping.target_field, tgt_msg_name, sheet_name,
                mapping.evidence_chunk_ids
            )

            # Create HAS_FIELD edges
            if src_col:
                self._create_edge(
                    src_msg["node_id"], src_col["node_id"],
                    "HAS_FIELD",
                    f"{src_msg_name} has field {mapping.source_field.field_name}",
                    mapping.evidence_chunk_ids, 0.8,
                    {"source_sheet": sheet_name, "field_no": mapping.source_field.field_no}
                )
            if tgt_col:
                self._create_edge(
                    tgt_msg["node_id"], tgt_col["node_id"],
                    "HAS_FIELD",
                    f"{tgt_msg_name} has field {mapping.target_field.field_name}",
                    mapping.evidence_chunk_ids, 0.8,
                    {"source_sheet": sheet_name, "field_no": mapping.target_field.field_no}
                )

            # Create MAPS_TO edge between source and target columns
            if src_col and tgt_col:
                self._create_edge(
                    src_col["node_id"], tgt_col["node_id"],
                    "MAPS_TO",
                    f"{mapping.source_field.field_name} ({source_sys}) maps to "
                    f"{mapping.target_field.field_name} ({target_sys})",
                    mapping.evidence_chunk_ids, mapping.confidence,
                    {
                        "mapping_type": "field_mapping",
                        "source_system": source_sys,
                        "target_system": target_sys,
                        "operation": operation,
                        "source_sheet": sheet_name,
                        "row_number": mapping.row_number,
                        "extraction_method": "excel_row_pair_heuristic",
                    }
                )

    def _extract_field_mappings_from_chunks(
        self,
        chunks: list[dict],
        source_sys: str,
        target_sys: str,
        sheet_name: str,
    ) -> list[FieldMapping]:
        """Parse field mappings from chunk text.

        Mapping sheets have rows like:
        Row 22: IF-ID: 1 | C: 処理フラグ | X: CHAR | AE: 1 | ... | BK: No | BM: 項目名称 | ...
        Row 23: IF-ID: 2 | C: 購買発注番号 | X: CHAR | AE: 10 | BK: 1 | BM: レコード区分 | ...

        Left side = source system fields, Right side = target system fields
        The boundary is typically around column BK.
        """
        mappings = []
        row_pattern = re.compile(r"^Row\s+(\d+):\s*(.+)$", re.MULTILINE)

        for chunk in chunks:
            text = chunk.get("text", "")
            chunk_id = chunk["chunk_id"]

            for match in row_pattern.finditer(text):
                row_num = int(match.group(1))
                row_content = match.group(2)

                # Parse cell values from "KEY: value | KEY: value" format
                cells = self._parse_row_cells(row_content)

                # Skip header rows and metadata rows
                if_id = cells.get("IF-ID", "").strip()
                if not if_id or not if_id.replace(".", "").isdigit():
                    continue

                # Extract source field (left side)
                src_field = MappingField(
                    field_no=if_id,
                    field_name=cells.get("C", "").strip(),
                    variable=cells.get("M", "").strip(),
                    data_type=cells.get("X", "").strip(),
                    length=str(cells.get("AE", cells.get("AC", ""))).strip(),
                    required="",
                    description=cells.get("AU", "").strip(),
                    system=source_sys,
                    source_cell_refs={"IF-ID": if_id, "C": cells.get("C", "")},
                )

                # Extract target field (right side, columns BK+)
                tgt_no = str(cells.get("BK", "")).strip()
                tgt_name = cells.get("BM", "").strip()
                tgt_field = MappingField(
                    field_no=tgt_no,
                    field_name=tgt_name,
                    variable=cells.get("BX", "").strip(),
                    data_type=cells.get("CJ", "").strip(),
                    length=str(cells.get("CQ", "")).strip(),
                    required=cells.get("CO", "").strip(),
                    description=cells.get("CV", "").strip(),
                    system=target_sys,
                    source_cell_refs={"BK": tgt_no, "BM": tgt_name},
                )

                # Quality check
                if src_field.field_name in GENERIC_FIELD_NAMES and tgt_field.field_name in GENERIC_FIELD_NAMES:
                    continue

                # Calculate confidence
                confidence = 0.8
                if not src_field.field_name or src_field.field_name in GENERIC_FIELD_NAMES:
                    confidence -= 0.2
                if not tgt_field.field_name or tgt_field.field_name in GENERIC_FIELD_NAMES:
                    confidence -= 0.2
                if src_field.data_type:
                    confidence += 0.05
                if tgt_field.data_type:
                    confidence += 0.05

                mapping = FieldMapping(
                    source_field=src_field,
                    target_field=tgt_field,
                    sheet_name=sheet_name,
                    row_number=row_num,
                    confidence=min(confidence, 1.0),
                    evidence_chunk_ids=[chunk_id],
                )

                if confidence < 0.5:
                    self.low_confidence.append({
                        "type": "field_mapping",
                        "sheet_name": sheet_name,
                        "row_number": row_num,
                        "source_field": src_field.field_name,
                        "target_field": tgt_field.field_name,
                        "confidence": confidence,
                        "reason": "low_field_quality",
                    })
                else:
                    mappings.append(mapping)

        return mappings

    def _parse_row_cells(self, row_content: str) -> dict[str, str]:
        """Parse 'KEY: value | KEY: value' format into dict."""
        cells: dict[str, str] = {}
        # Split by " | " but handle values that contain pipe
        parts = re.split(r"\s*\|\s*", row_content)
        for part in parts:
            # Split on first ": "
            colon_idx = part.find(": ")
            if colon_idx > 0:
                key = part[:colon_idx].strip()
                value = part[colon_idx + 2:].strip()
                cells[key] = value
            elif part.strip():
                # Value continuation or standalone
                cells[part.strip()] = ""
        return cells

    def _create_edge(
        self,
        source_node_id: str,
        target_node_id: str,
        relation_type: str,
        description: str,
        evidence_chunk_ids: list[str],
        confidence: float,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create a graph edge, deduplicating by source+target+relation."""
        edge_id = self._make_edge_id(source_node_id, target_node_id, relation_type)

        # Check for duplicate
        for existing in self.edges:
            if existing["edge_id"] == edge_id:
                # Merge evidence
                for eid in evidence_chunk_ids:
                    if eid not in existing["evidence_chunk_ids"]:
                        existing["evidence_chunk_ids"].append(eid)
                return

        edge = {
            "edge_id": edge_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "layer": "implementation",
            "description": description,
            "properties": properties or {},
            "source_ids": [],
            "evidence_chunk_ids": list(evidence_chunk_ids),
            "confidence": confidence,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }
        self.edges.append(edge)
