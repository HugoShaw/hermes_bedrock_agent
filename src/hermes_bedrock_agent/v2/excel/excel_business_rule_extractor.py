"""
Excel business rule extractor — extract BusinessRule, BusinessTerm, Function
nodes from data acquisition condition sheets (データ取得条件).
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

# Condition keywords that indicate business rules
RULE_KEYWORDS = [
    "条件", "フィルタ", "検索", "取得", "対象", "除外", "必須",
    "処理", "エラー", "登録", "更新", "取消", "ステータス", "日付",
    "フラグ", "Default", "複数", "一致", "部分一致", "完全一致",
]

# Business term extraction patterns
TERM_PATTERNS = [
    # Status values (e.g., 410：納品待ち)
    re.compile(r"(\d{3})[：:](.+?)(?:\n|$)"),
    # ANDPAD system ID format
    re.compile(r"ANDPAD-SYSTEMID-\{(.+?)\}"),
    # Query parameter names
    re.compile(r"\?(\w+)="),
]

# Known business terms to always extract if mentioned
KNOWN_TERMS = {
    "発注": "発注",
    "発注情報": "発注情報",
    "発注一覧": "発注一覧",
    "発注明細": "発注明細",
    "発注状況": "発注状況",
    "納品": "納品",
    "納品一覧": "納品一覧",
    "納品明細": "納品明細",
    "納品状況": "納品状況",
    "請求": "請求",
    "請求管理ID": "請求管理ID",
    "案件": "案件",
    "案件管理ID": "案件管理ID",
    "現場監督": "現場監督",
    "メンバー管理ID": "メンバー管理ID",
    "ページ": "ページ",
    "検収": "検収",
    "承認": "承認",
    "差戻": "差戻",
    "取下": "取下",
    "編集中": "編集中",
    "請負": "請負",
}

# Function name patterns from sheet names
FUNCTION_PATTERN = re.compile(r"データ取得条件[（(](.+?)[）)]")


class ExcelBusinessRuleExtractor:
    """Extract business rules and terms from data acquisition condition sheets."""

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
        self._extracted_terms: set[str] = set()

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
        """Get or create node with dedup."""
        key = f"{label}:{name}"
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
        node["properties"]["extraction_method"] = "excel_business_rule_heuristic"
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
        """Create edge with dedup."""
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
        """Extract business rules and terms from condition sheets.

        Parameters
        ----------
        chunks : business_rule_sheet chunks
        rows : normalized rows from these sheets
        """
        # Group chunks by sheet
        by_sheet: dict[str, list[dict]] = {}
        for chunk in chunks:
            meta = chunk.get("metadata", {})
            sheet_name = meta.get("sheet_name", "unknown")
            sheet_type = meta.get("guessed_sheet_type", "")
            if sheet_type == "business_rule_sheet" or "データ取得条件" in sheet_name:
                by_sheet.setdefault(sheet_name, []).append(chunk)

        # Group rows by sheet
        rows_by_sheet: dict[str, list[dict]] = {}
        if rows:
            for row in rows:
                sn = row.get("sheet_name", "")
                if "データ取得条件" in sn:
                    rows_by_sheet.setdefault(sn, []).append(row)

        logger.info(f"Processing {len(by_sheet)} business rule sheets")

        for sheet_name, sheet_chunks in by_sheet.items():
            sheet_rows = rows_by_sheet.get(sheet_name, [])
            self._process_condition_sheet(sheet_name, sheet_chunks, sheet_rows)

    def _process_condition_sheet(
        self,
        sheet_name: str,
        chunks: list[dict],
        rows: list[dict],
    ) -> None:
        """Process a data acquisition condition sheet."""
        chunk_ids = [c["chunk_id"] for c in chunks]

        # Extract function name from sheet name
        fn_match = FUNCTION_PATTERN.search(sheet_name)
        function_name = fn_match.group(1) if fn_match else sheet_name

        # Create Function node
        function_node = self._get_or_create_node(
            "Function",
            function_name,
            function_name,
            f"Data acquisition function: {function_name}",
            chunk_ids,
            0.85,
            {"sheet_name": sheet_name, "function_type": "data_acquisition"},
        )

        # Process rows to extract rules
        if rows:
            self._extract_rules_from_rows(
                function_node, rows, sheet_name, chunk_ids
            )
        else:
            # Extract from chunk text
            self._extract_rules_from_text(
                function_node, chunks, sheet_name
            )

        # Extract terms from all chunk text
        all_text = "\n".join(c.get("text", "") for c in chunks)
        self._extract_terms_from_text(
            function_node, all_text, sheet_name, chunk_ids
        )

    def _extract_rules_from_rows(
        self,
        function_node: dict,
        rows: list[dict],
        sheet_name: str,
        chunk_ids: list[str],
    ) -> None:
        """Extract business rules from normalized rows."""
        for row in sorted(rows, key=lambda r: r.get("row_number", 0)):
            vals = row.get("values", {})

            # Find the item name column
            item_name = None
            item_type = None
            remarks = None

            for key, val in vals.items():
                val_str = str(val).strip() if val else ""
                if not val_str:
                    continue
                # Detect item name column
                if "項目名" in key:
                    item_name = val_str
                elif "型" == key or key == "型":
                    item_type = val_str
                elif "備考" in key or "Default" in key:
                    remarks = val_str

            if not item_name:
                # Skip rows without item names
                continue

            # Skip if too short/generic
            if len(item_name) < 3:
                self.rejected.append({
                    "type": "rule_too_short",
                    "item_name": item_name,
                    "sheet_name": sheet_name,
                    "row_number": row.get("row_number", 0),
                })
                continue

            # Create BusinessRule node
            rule_desc = f"{item_name}"
            if item_type:
                rule_desc += f" (型: {item_type})"
            if remarks:
                rule_desc += f" — {remarks[:100]}"

            rule_node = self._get_or_create_node(
                "BusinessRule",
                f"{function_node['display_name']}_{item_name}",
                f"{function_node['display_name']}: {item_name}",
                rule_desc,
                chunk_ids[:1],
                0.8,
                {
                    "sheet_name": sheet_name,
                    "row_number": row.get("row_number", 0),
                    "item_type": item_type or "",
                    "remarks_preview": (remarks or "")[:200],
                    "source": "condition_row",
                },
                context=sheet_name,
            )

            # Function HAS_RULE BusinessRule
            self._create_edge(
                function_node["node_id"], rule_node["node_id"],
                "HAS_RULE",
                f"{function_node['display_name']} has rule for {item_name}",
                chunk_ids[:1], 0.8,
                {"sheet_name": sheet_name}
            )

            # Extract terms from remarks if rich
            if remarks and len(remarks) > 20:
                terms = self._extract_terms_from_rule(remarks, item_name)
                for term_name in terms:
                    term_node = self._get_or_create_node(
                        "BusinessTerm",
                        term_name,
                        term_name,
                        f"Business term: {term_name}",
                        chunk_ids[:1],
                        0.7,
                        {"source_rule": item_name, "sheet_name": sheet_name},
                    )

                    # BusinessRule HAS_TERM BusinessTerm
                    self._create_edge(
                        rule_node["node_id"], term_node["node_id"],
                        "HAS_TERM",
                        f"Rule for {item_name} references term {term_name}",
                        chunk_ids[:1], 0.65,
                        {"sheet_name": sheet_name}
                    )

    def _extract_rules_from_text(
        self,
        function_node: dict,
        chunks: list[dict],
        sheet_name: str,
    ) -> None:
        """Fallback: extract rules from chunk text."""
        for chunk in chunks:
            text = chunk.get("text", "")
            chunk_id = chunk.get("chunk_id", "")

            # Find item lines in the text
            lines = text.split("\n")
            for line in lines:
                line = line.strip()
                # Look for "項目名" pattern in evidence text
                if "項目名" in line and ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2 and len(parts[1].strip()) > 2:
                        item_name = parts[1].strip()[:60]
                        rule_node = self._get_or_create_node(
                            "BusinessRule",
                            f"{function_node['display_name']}_{item_name}",
                            f"{function_node['display_name']}: {item_name}",
                            f"Data condition rule: {item_name}",
                            [chunk_id],
                            0.6,
                            {"sheet_name": sheet_name, "source": "text_parse"},
                            context=sheet_name,
                        )
                        self._create_edge(
                            function_node["node_id"], rule_node["node_id"],
                            "HAS_RULE",
                            f"{function_node['display_name']} has rule {item_name}",
                            [chunk_id], 0.6,
                            {"sheet_name": sheet_name}
                        )

    def _extract_terms_from_rule(
        self,
        remarks: str,
        item_name: str,
    ) -> list[str]:
        """Extract business terms from rule remarks."""
        terms: list[str] = []

        # Status codes (e.g., 410：納品待ち, 301：発注前)
        for m in TERM_PATTERNS[0].finditer(remarks):
            status_text = m.group(2).strip()
            if len(status_text) >= 2 and status_text not in self._extracted_terms:
                terms.append(status_text)
                self._extracted_terms.add(status_text)

        return terms[:5]  # Cap per rule

    def _extract_terms_from_text(
        self,
        function_node: dict,
        text: str,
        sheet_name: str,
        chunk_ids: list[str],
    ) -> None:
        """Extract known business terms from text."""
        for term_key, term_display in KNOWN_TERMS.items():
            if term_key in text and term_display not in self._extracted_terms:
                # Check it appears meaningfully (not just in a URL)
                count = text.count(term_key)
                if count >= 2 or term_key in sheet_name:
                    term_node = self._get_or_create_node(
                        "BusinessTerm",
                        term_display,
                        term_display,
                        f"Business term: {term_display}",
                        chunk_ids[:1],
                        0.75,
                        {"sheet_name": sheet_name, "occurrence_count": count},
                    )
                    self._extracted_terms.add(term_display)

                    # Function HAS_TERM BusinessTerm
                    self._create_edge(
                        function_node["node_id"], term_node["node_id"],
                        "HAS_TERM",
                        f"{function_node['display_name']} uses term {term_display}",
                        chunk_ids[:1], 0.7,
                        {"sheet_name": sheet_name}
                    )
