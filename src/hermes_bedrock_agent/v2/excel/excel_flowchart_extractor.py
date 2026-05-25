"""
Excel flowchart extractor — extract BusinessProcess, BusinessStep, Function
nodes from business_process_sheet evidence (フローチャート).
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

# Process-related keywords
PROCESS_KEYWORDS = [
    "処理", "取得", "登録", "更新", "削除", "取消", "送信", "受信",
    "変換", "検証", "判定", "分岐", "確認", "チェック", "呼出",
    "開始", "終了", "エラー", "リトライ", "通知",
]

# Step ordering patterns
STEP_NUMBER_PATTERN = re.compile(r"^(\d+)[\.．)\s]")
CIRCLED_NUMBER_PATTERN = re.compile(r"^([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])")


class ExcelFlowchartExtractor:
    """Extract business process and step nodes from flowchart/process sheets.

    Handles:
    - フローチャート sheet (process flow)
    - Sections describing processing sequence
    - Row-based step sequences
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
        self._node_registry: dict[str, dict] = {}

    def _make_node_id(self, label: str, name: str, context: str = "") -> str:
        raw = f"{self.dataset}:biz:{label}:{name}:{context}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _make_edge_id(self, src: str, tgt: str, rel: str) -> str:
        raw = f"{self.dataset}:biz:{src}:{tgt}:{rel}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _get_or_create_node(
        self,
        label: str,
        name: str,
        display_name: str,
        description: str,
        evidence_chunk_ids: list[str],
        confidence: float = 0.7,
        properties: dict | None = None,
        context: str = "",
    ) -> dict:
        """Get or create a node with deduplication."""
        key = f"{label}:{name}:{context}"
        if key in self._node_registry:
            existing = self._node_registry[key]
            for eid in evidence_chunk_ids:
                if eid not in existing["evidence_chunk_ids"]:
                    existing["evidence_chunk_ids"].append(eid)
            return existing

        node_id = self._make_node_id(label, name, context)
        node = {
            "node_id": node_id,
            "label": label,
            "name": name.lower().replace(" ", "_").replace("／", "_"),
            "display_name": display_name,
            "layer": "business",
            "aliases": [],
            "description": description,
            "properties": properties or {},
            "source_ids": [],
            "evidence_chunk_ids": list(evidence_chunk_ids),
            "confidence": confidence,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }
        node["properties"]["extraction_method"] = "excel_flowchart_heuristic"
        self._node_registry[key] = node
        self.nodes.append(node)
        return node

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
        """Create edge with deduplication."""
        edge_id = self._make_edge_id(source_node_id, target_node_id, relation_type)
        for existing in self.edges:
            if existing["edge_id"] == edge_id:
                for eid in evidence_chunk_ids:
                    if eid not in existing["evidence_chunk_ids"]:
                        existing["evidence_chunk_ids"].append(eid)
                return

        edge = {
            "edge_id": edge_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_type": relation_type,
            "layer": "business",
            "description": description,
            "properties": properties or {},
            "source_ids": [],
            "evidence_chunk_ids": list(evidence_chunk_ids),
            "confidence": confidence,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }
        self.edges.append(edge)

    def extract_from_chunks(
        self,
        chunks: list[dict],
        rows: list[dict] | None = None,
    ) -> None:
        """Extract process/step graph from flowchart/process chunks.

        Parameters
        ----------
        chunks : business_process_sheet chunks
        rows : normalized rows from the same sheets (may be empty for sparse sheets)
        """
        # Group by sheet
        by_sheet: dict[str, list[dict]] = {}
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            sheet_name = meta.get("sheet_name", "unknown")
            sheet_type = meta.get("guessed_sheet_type", "")
            if sheet_type == "business_process_sheet":
                by_sheet.setdefault(sheet_name, []).append(chunk)

        # Group rows by sheet
        rows_by_sheet: dict[str, list[dict]] = {}
        if rows:
            for row in rows:
                sn = row.get("sheet_name", "")
                rows_by_sheet.setdefault(sn, []).append(row)

        logger.info(f"Processing {len(by_sheet)} flowchart/process sheets")

        for sheet_name, sheet_chunks in by_sheet.items():
            sheet_rows = rows_by_sheet.get(sheet_name, [])
            self._process_flowchart_sheet(sheet_name, sheet_chunks, sheet_rows)

    def _process_flowchart_sheet(
        self,
        sheet_name: str,
        chunks: list[dict],
        rows: list[dict],
    ) -> None:
        """Process a single flowchart sheet."""
        chunk_ids = [c["chunk_id"] for c in chunks]

        # For sparse sheets (like フローチャート with 3 non-empty cells),
        # create a minimal process node from the sheet name
        all_text = "\n".join(c.get("text", "") for c in chunks)

        # Extract process name from sheet context
        # The sheet name itself tells us this is a flowchart
        process_name = self._infer_process_name(sheet_name, all_text)

        if process_name:
            process_node = self._get_or_create_node(
                "BusinessProcess",
                process_name,
                process_name,
                f"Business process: {process_name} (from {sheet_name})",
                chunk_ids,
                0.6,
                {"sheet_name": sheet_name, "source": "flowchart_sheet"},
            )

            # If we have rows, try to extract steps
            if rows:
                self._extract_steps_from_rows(
                    process_node, rows, sheet_name, chunk_ids
                )
            else:
                # Try extracting steps from chunk text
                self._extract_steps_from_text(
                    process_node, all_text, sheet_name, chunk_ids
                )

    def _infer_process_name(self, sheet_name: str, text: str) -> str:
        """Infer a process name from sheet/text context."""
        # Try to find broader context
        if "フローチャート" in sheet_name:
            # The overall process is the integration flow
            return "SAP_Andpad連携フロー"
        if "処理" in sheet_name:
            return sheet_name
        # Generic fallback
        return sheet_name

    def _extract_steps_from_rows(
        self,
        process_node: dict,
        rows: list[dict],
        sheet_name: str,
        chunk_ids: list[str],
    ) -> None:
        """Extract steps from normalized rows."""
        prev_step = None
        for row in sorted(rows, key=lambda r: r.get("row_number", 0)):
            vals = row.get("values", {})
            # Find step-like content
            step_text = self._find_step_text(vals)
            if not step_text:
                continue

            step_node = self._get_or_create_node(
                "BusinessStep",
                step_text,
                step_text,
                f"Process step: {step_text}",
                chunk_ids[:1],
                0.65,
                {
                    "sheet_name": sheet_name,
                    "row_number": row.get("row_number", 0),
                    "source": "flowchart_row",
                },
                context=sheet_name,
            )

            # HAS_STEP
            self._create_edge(
                process_node["node_id"], step_node["node_id"],
                "HAS_STEP", f"{process_node['display_name']} has step {step_text}",
                chunk_ids[:1], 0.65,
                {"sheet_name": sheet_name}
            )

            # NEXT_STEP from previous
            if prev_step:
                self._create_edge(
                    prev_step["node_id"], step_node["node_id"],
                    "NEXT_STEP", f"{prev_step['display_name']} -> {step_text}",
                    chunk_ids[:1], 0.55,
                    {"sheet_name": sheet_name, "order": "row_sequence"}
                )

            prev_step = step_node

    def _extract_steps_from_text(
        self,
        process_node: dict,
        text: str,
        sheet_name: str,
        chunk_ids: list[str],
    ) -> None:
        """Extract steps from chunk text (fallback for sparse sheets)."""
        # Look for numbered steps or process keywords in text
        lines = text.split("\n")
        steps_found = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Check for step-like patterns
            m = STEP_NUMBER_PATTERN.match(line)
            if m:
                step_text = line[m.end():].strip()
                if step_text and len(step_text) > 2:
                    steps_found.append(step_text)
                continue
            m = CIRCLED_NUMBER_PATTERN.match(line)
            if m:
                step_text = line[m.end():].strip()
                if step_text and len(step_text) > 2:
                    steps_found.append(step_text)

        # Create step nodes
        prev_step = None
        for step_text in steps_found[:20]:  # Cap
            step_node = self._get_or_create_node(
                "BusinessStep",
                step_text[:50],
                step_text,
                f"Process step: {step_text}",
                chunk_ids[:1],
                0.5,
                {"sheet_name": sheet_name, "source": "text_parse"},
                context=sheet_name,
            )

            self._create_edge(
                process_node["node_id"], step_node["node_id"],
                "HAS_STEP", f"{process_node['display_name']} has step {step_text[:30]}",
                chunk_ids[:1], 0.5,
                {"sheet_name": sheet_name}
            )

            if prev_step:
                self._create_edge(
                    prev_step["node_id"], step_node["node_id"],
                    "NEXT_STEP", f"next step",
                    chunk_ids[:1], 0.45,
                    {"sheet_name": sheet_name, "order": "text_sequence"}
                )

            prev_step = step_node

    def _find_step_text(self, vals: dict[str, Any]) -> str | None:
        """Find step-like content in a row's values."""
        for key, val in vals.items():
            val_str = str(val).strip()
            if not val_str or len(val_str) < 3:
                continue
            # Check if it looks like a process step
            for kw in PROCESS_KEYWORDS:
                if kw in val_str:
                    return val_str[:80]
        return None
