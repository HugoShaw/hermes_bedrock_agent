"""
Excel API sequence extractor — extract API/system interaction nodes and edges
from API呼出順序 and DataSpider開発仕様 sheets.
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

# Patterns to identify API-related content
API_NAME_PATTERNS = [
    re.compile(r"API[：:]?\s*(.+?)(?:\s*$|\s*[（(])", re.MULTILINE),
    re.compile(r"IF[-_]?ID[：:]?\s*(\w+)", re.IGNORECASE),
    re.compile(r"SAP_EDI_(\d+)"),
]

# System references in API chunks
SYSTEM_REFS = {
    "SAP": re.compile(r"\bSAP\b"),
    "Andpad": re.compile(r"\bANDPAD\b|\bAndpad\b"),
    "DataSpider": re.compile(r"\bDataSpider\b|\bD/S\b|\bDS\b"),
    "HULFT": re.compile(r"\bHULFT\b"),
    "中間F": re.compile(r"中間F|中間フォーマット"),
}

# File-related patterns
FILE_PATTERNS = [
    re.compile(r"ファイル名[：:]?\s*(.+?)(?:\n|$)"),
    re.compile(r"[A-Z_]+\.\w{2,4}"),  # e.g., TEMP_AF_1.DAT
    re.compile(r"IF[-_]?ID\s*＋.*?\"\.DAT\""),
]

# Process step patterns
STEP_PATTERNS = [
    re.compile(r"(\d+)\.\s*(.+?)(?:\n|$)"),
    re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩](.+?)(?:\n|$)"),
]


class ExcelAPISequenceExtractor:
    """Extract API/system interaction graph from api_interface_sheet evidence.

    Targets:
    - API呼出順序 sheet: system interaction flow, requirements
    - DataSpider開発仕様 sheet: processing steps, file handling
    - Any api-type chunks
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
        raw = f"{self.dataset}:{label}:{name}:{context}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _make_edge_id(self, src: str, tgt: str, rel: str) -> str:
        raw = f"{self.dataset}:{src}:{tgt}:{rel}"
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
        """Get or create a node, deduplicating by label:name:context."""
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
            "layer": "implementation",
            "aliases": [],
            "description": description,
            "properties": properties or {},
            "source_ids": [],
            "evidence_chunk_ids": list(evidence_chunk_ids),
            "confidence": confidence,
            "run_id": self.run_id,
            "dataset": self.dataset,
        }
        node["properties"]["extraction_method"] = "excel_api_heuristic"
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
        """Create a graph edge with deduplication."""
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

    def extract_from_chunks(self, chunks: list[dict]) -> None:
        """Extract API/system interaction graph from api-type chunks."""
        api_chunks = [
            c for c in chunks
            if c["chunk_type"] == "api"
            or c.get("metadata", {}).get("guessed_sheet_type") == "api_interface_sheet"
        ]

        if not api_chunks:
            logger.warning("No API chunks found for extraction")
            return

        logger.info(f"Processing {len(api_chunks)} API-related chunks")

        # Group by sheet
        by_sheet: dict[str, list[dict]] = {}
        for chunk in api_chunks:
            sheet_name = chunk.get("metadata", {}).get("sheet_name", "unknown")
            by_sheet.setdefault(sheet_name, []).append(chunk)

        for sheet_name, sheet_chunks in by_sheet.items():
            self._process_api_sheet(sheet_name, sheet_chunks)

    def _process_api_sheet(self, sheet_name: str, chunks: list[dict]) -> None:
        """Process API-related sheet chunks."""
        chunk_ids = [c["chunk_id"] for c in chunks]
        all_text = "\n".join(c.get("text", "") for c in chunks)

        # Detect systems mentioned
        systems_found: dict[str, dict] = {}
        for sys_name, pattern in SYSTEM_REFS.items():
            if pattern.search(all_text):
                node = self._get_or_create_node(
                    "System", sys_name, sys_name,
                    f"System {sys_name} (referenced in {sheet_name})",
                    chunk_ids[:2], 0.85,
                    {"source_sheet": sheet_name},
                )
                systems_found[sys_name] = node

        # Extract interface IDs (SAP_EDI_XXXX patterns)
        if_ids: set[str] = set()
        for pattern in API_NAME_PATTERNS:
            for match in pattern.finditer(all_text):
                if_id = match.group(0) if match.lastindex is None else match.group(0)
                # Only keep SAP_EDI_XXXX style
                sap_match = re.search(r"SAP_EDI_\d+", if_id)
                if sap_match:
                    if_ids.add(sap_match.group(0))

        # Create API nodes for interface IDs
        for if_id in if_ids:
            api_node = self._get_or_create_node(
                "API", if_id, if_id,
                f"Interface: {if_id} (from {sheet_name})",
                chunk_ids[:2], 0.75,
                {"source_sheet": sheet_name, "interface_type": "file_based"},
            )
            # Link to SAP system
            if "SAP" in systems_found:
                self._create_edge(
                    systems_found["SAP"]["node_id"], api_node["node_id"],
                    "HAS_API", f"SAP has interface {if_id}",
                    chunk_ids[:1], 0.8,
                    {"source_sheet": sheet_name}
                )

        # Extract file patterns
        files_found: set[str] = set()
        for pattern in FILE_PATTERNS:
            for match in pattern.finditer(all_text):
                file_text = match.group(0).strip()
                # Only keep actual file names
                file_match = re.search(r"[A-Z_]+\w*\.\w{2,4}", file_text)
                if file_match:
                    fname = file_match.group(0)
                    if len(fname) > 4 and fname not in files_found:
                        files_found.add(fname)

        for fname in files_found:
            file_node = self._get_or_create_node(
                "File", fname, fname,
                f"Interface file: {fname}",
                chunk_ids[:1], 0.7,
                {"source_sheet": sheet_name, "file_type": "interface_data"},
            )
            # Link file to DataSpider if present
            if "DataSpider" in systems_found:
                self._create_edge(
                    systems_found["DataSpider"]["node_id"], file_node["node_id"],
                    "USES", f"DataSpider uses file {fname}",
                    chunk_ids[:1], 0.65,
                    {"source_sheet": sheet_name}
                )

        # Extract processing steps as Module-level concepts
        steps = self._extract_process_steps(all_text)
        if steps and "DataSpider" in systems_found:
            for step_num, step_desc in steps[:10]:  # Cap at 10
                if len(step_desc) < 5:
                    continue
                # Create a Module node for significant processing steps
                step_name = f"Step_{step_num}_{step_desc[:20]}"
                module_node = self._get_or_create_node(
                    "Module", step_name, step_desc[:50],
                    f"Processing step {step_num}: {step_desc}",
                    chunk_ids[:1], 0.6,
                    {"source_sheet": sheet_name, "step_number": step_num},
                    context=sheet_name,
                )
                self._create_edge(
                    systems_found["DataSpider"]["node_id"], module_node["node_id"],
                    "CONTAINS", f"DataSpider contains step {step_num}",
                    chunk_ids[:1], 0.6,
                    {"source_sheet": sheet_name, "step_number": step_num}
                )

        # Create inter-system edges
        if "SAP" in systems_found and "DataSpider" in systems_found:
            self._create_edge(
                systems_found["SAP"]["node_id"],
                systems_found["DataSpider"]["node_id"],
                "DEPENDS_ON",
                "SAP sends data to DataSpider for processing",
                chunk_ids[:1], 0.8,
                {"source_sheet": sheet_name, "interaction_type": "file_transfer"}
            )
        if "DataSpider" in systems_found and "Andpad" in systems_found:
            self._create_edge(
                systems_found["DataSpider"]["node_id"],
                systems_found["Andpad"]["node_id"],
                "DEPENDS_ON",
                "DataSpider sends processed data to Andpad via API",
                chunk_ids[:1], 0.8,
                {"source_sheet": sheet_name, "interaction_type": "api_call"}
            )

    def _extract_process_steps(self, text: str) -> list[tuple[str, str]]:
        """Extract numbered processing steps."""
        steps = []
        for pattern in STEP_PATTERNS:
            for match in pattern.finditer(text):
                if match.lastindex and match.lastindex >= 2:
                    step_num = match.group(1)
                    step_desc = match.group(2).strip()
                    if step_desc and len(step_desc) > 3:
                        steps.append((step_num, step_desc))
                elif match.lastindex == 1:
                    step_desc = match.group(1).strip()
                    if step_desc and len(step_desc) > 3:
                        steps.append((str(len(steps) + 1), step_desc))
        return steps
