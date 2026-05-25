"""
Excel GraphRAG readiness evaluator — determine which sheets/evidence are suitable
for Business Graph, Implementation Graph, or Vector Evidence only.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Sheet type → graph layer recommendations
BUSINESS_GRAPH_SHEET_TYPES = {
    "business_process_sheet",
    "business_rule_sheet",
    "test_case_sheet",
    "screen_definition_sheet",
    "code_master_sheet",
    "operation_sheet",
}

IMPLEMENTATION_GRAPH_SHEET_TYPES = {
    "field_mapping_sheet",
    "api_interface_sheet",
    "data_dictionary_sheet",
    "system_config_sheet",
    "screen_definition_sheet",
    "code_master_sheet",
}

VECTOR_ONLY_SHEET_TYPES = {
    "unknown_sheet",
}

# Possible business graph entities from sheet types
BUSINESS_ENTITIES_BY_SHEET_TYPE = {
    "business_process_sheet": ["BusinessProcess", "BusinessStep", "BusinessRule", "Function"],
    "business_rule_sheet": ["BusinessRule", "BusinessTerm", "BusinessStep"],
    "test_case_sheet": ["BusinessRule", "Function", "Screen"],
    "screen_definition_sheet": ["Screen", "Function", "Role"],
    "code_master_sheet": ["BusinessTerm", "BusinessRule"],
    "operation_sheet": ["BusinessProcess", "BusinessStep", "Role"],
}

# Possible implementation graph entities from sheet types
IMPLEMENTATION_ENTITIES_BY_SHEET_TYPE = {
    "field_mapping_sheet": ["Table", "Column", "API", "Message", "File", "System", "ExternalSystem"],
    "api_interface_sheet": ["API", "Message", "System", "Module", "ErrorCode"],
    "data_dictionary_sheet": ["Table", "Column", "System"],
    "system_config_sheet": ["Config", "System", "Module"],
    "screen_definition_sheet": ["API", "Screen", "Module"],
    "code_master_sheet": ["Table", "Column", "ErrorCode"],
}


@dataclass
class SheetReadinessRecord:
    """GraphRAG readiness assessment for a single sheet."""
    sheet_id: str
    sheet_name: str
    workbook_name: str = ""
    guessed_sheet_type: str = "unknown_sheet"
    business_graph_candidate: bool = False
    implementation_graph_candidate: bool = False
    vector_evidence_candidate: bool = True
    recommended_usage: list[str] = field(default_factory=list)
    possible_business_entities: list[str] = field(default_factory=list)
    possible_implementation_entities: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""
    risks: list[str] = field(default_factory=list)
    evidence_chunk_count: int = 0
    table_region_count: int = 0
    normalized_row_count: int = 0
    merged_cell_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class ExcelGraphRAGReadiness:
    """Evaluate sheet-level GraphRAG readiness.

    Parameters
    ----------
    sheets_path : Path
        Path to excel_sheets.jsonl.
    regions_path : Path
        Path to excel_table_regions.jsonl.
    chunks_path : Path
        Path to evidence_chunks.jsonl.
    rows_path : Path
        Path to excel_rows_normalized.jsonl.
    """

    def __init__(
        self,
        sheets_path: Path,
        regions_path: Path,
        chunks_path: Path,
        rows_path: Path,
    ) -> None:
        self.sheets_path = Path(sheets_path)
        self.regions_path = Path(regions_path)
        self.chunks_path = Path(chunks_path)
        self.rows_path = Path(rows_path)
        self._sheets: list[dict] = []
        self._regions: list[dict] = []
        self._chunks: list[dict] = []
        self._readiness_records: list[SheetReadinessRecord] = []

    def load_data(self) -> None:
        """Load all input data."""
        self._sheets = [
            json.loads(line) for line in self.sheets_path.read_text().strip().split("\n") if line.strip()
        ]
        self._regions = [
            json.loads(line) for line in self.regions_path.read_text().strip().split("\n") if line.strip()
        ]
        self._chunks = [
            json.loads(line) for line in self.chunks_path.read_text().strip().split("\n") if line.strip()
        ]
        # Count rows per sheet (don't load all into memory)
        self._row_counts: dict[str, int] = {}
        with open(self.rows_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    sid = row.get("sheet_id", "")
                    self._row_counts[sid] = self._row_counts.get(sid, 0) + 1

        logger.info(
            f"Loaded {len(self._sheets)} sheets, {len(self._regions)} regions, "
            f"{len(self._chunks)} chunks for readiness evaluation"
        )

    def evaluate_all(self) -> list[SheetReadinessRecord]:
        """Evaluate readiness for all sheets."""
        if not self._sheets:
            self.load_data()

        # Build lookups
        chunks_by_sheet: dict[str, list[dict]] = {}
        for c in self._chunks:
            sid = c.get("metadata", {}).get("sheet_id", "")
            if sid:
                chunks_by_sheet.setdefault(sid, []).append(c)

        regions_by_sheet: dict[str, list[dict]] = {}
        for r in self._regions:
            sid = r.get("sheet_id", "")
            regions_by_sheet.setdefault(sid, []).append(r)

        self._readiness_records = []
        for sheet in self._sheets:
            record = self._evaluate_sheet(sheet, chunks_by_sheet, regions_by_sheet)
            self._readiness_records.append(record)

        logger.info(f"Evaluated {len(self._readiness_records)} sheets for GraphRAG readiness")
        return self._readiness_records

    def _evaluate_sheet(
        self,
        sheet: dict,
        chunks_by_sheet: dict[str, list[dict]],
        regions_by_sheet: dict[str, list[dict]],
    ) -> SheetReadinessRecord:
        """Evaluate a single sheet."""
        sheet_id = sheet.get("sheet_id", "")
        sheet_name = sheet.get("sheet_name", "")
        sheet_type = sheet.get("guessed_sheet_type", "unknown_sheet")
        workbook_name = sheet.get("workbook_id", "")  # May be workbook_id
        confidence = sheet.get("confidence", 0.0)
        merged_count = len(sheet.get("merged_cell_ranges", []))

        chunks = chunks_by_sheet.get(sheet_id, [])
        regions = regions_by_sheet.get(sheet_id, [])
        row_count = self._row_counts.get(sheet_id, 0)

        record = SheetReadinessRecord(
            sheet_id=sheet_id,
            sheet_name=sheet_name,
            workbook_name=workbook_name,
            guessed_sheet_type=sheet_type,
            confidence=confidence,
            evidence_chunk_count=len(chunks),
            table_region_count=len(regions),
            normalized_row_count=row_count,
            merged_cell_count=merged_count,
        )

        # Determine graph candidacy
        is_business = sheet_type in BUSINESS_GRAPH_SHEET_TYPES
        is_implementation = sheet_type in IMPLEMENTATION_GRAPH_SHEET_TYPES
        is_vector_only = sheet_type in VECTOR_ONLY_SHEET_TYPES

        record.business_graph_candidate = is_business
        record.implementation_graph_candidate = is_implementation
        record.vector_evidence_candidate = True  # Always usable as evidence

        # Build recommended usage
        usage = []
        if is_business:
            usage.append("business_graph")
        if is_implementation:
            usage.append("implementation_graph")
        usage.append("vector_evidence")
        record.recommended_usage = usage

        # Possible entities
        if is_business:
            record.possible_business_entities = BUSINESS_ENTITIES_BY_SHEET_TYPE.get(sheet_type, [])
        if is_implementation:
            record.possible_implementation_entities = IMPLEMENTATION_ENTITIES_BY_SHEET_TYPE.get(sheet_type, [])

        # Risks
        risks = []
        if confidence < 0.5:
            risks.append("low_type_confidence")
        if merged_count > 500:
            risks.append("merged_cell_heavy")
        if merged_count > 200:
            risks.append("multirow_header_complex")
        if row_count == 0 and sheet_type != "unknown_sheet":
            risks.append("no_normalized_rows")
        if len(chunks) == 0:
            risks.append("no_evidence_chunks")
        if sheet.get("non_empty_cell_count", 0) < 10:
            risks.append("sparse_content")
        record.risks = risks

        # Build reason
        reasons = []
        if is_business:
            reasons.append(f"Business graph candidate (type={sheet_type})")
        if is_implementation:
            reasons.append(f"Implementation graph candidate (type={sheet_type})")
        if is_vector_only:
            reasons.append(f"Vector evidence only (type={sheet_type})")
        if risks:
            reasons.append(f"Risks: {', '.join(risks)}")
        record.reason = "; ".join(reasons) if reasons else "Standard evidence sheet"

        return record

    def get_readiness_summary(self) -> dict[str, Any]:
        """Get aggregate readiness metrics."""
        if not self._readiness_records:
            return {}

        business_count = sum(1 for r in self._readiness_records if r.business_graph_candidate)
        impl_count = sum(1 for r in self._readiness_records if r.implementation_graph_candidate)
        vector_count = sum(1 for r in self._readiness_records if r.vector_evidence_candidate)
        low_conf = sum(1 for r in self._readiness_records if r.confidence < 0.5)

        type_counts: dict[str, int] = {}
        for r in self._readiness_records:
            type_counts[r.guessed_sheet_type] = type_counts.get(r.guessed_sheet_type, 0) + 1

        return {
            "total_sheets": len(self._readiness_records),
            "business_graph_candidates": business_count,
            "implementation_graph_candidates": impl_count,
            "vector_evidence_candidates": vector_count,
            "low_confidence_sheets": low_conf,
            "by_sheet_type": dict(sorted(type_counts.items(), key=lambda x: -x[1])),
            "top_business_candidates": [
                {"sheet_name": r.sheet_name, "type": r.guessed_sheet_type, "entities": r.possible_business_entities}
                for r in self._readiness_records if r.business_graph_candidate
            ],
            "top_implementation_candidates": [
                {"sheet_name": r.sheet_name, "type": r.guessed_sheet_type, "entities": r.possible_implementation_entities}
                for r in self._readiness_records if r.implementation_graph_candidate
            ],
            "manual_review_required": [
                {"sheet_name": r.sheet_name, "type": r.guessed_sheet_type, "risks": r.risks}
                for r in self._readiness_records if r.confidence < 0.5 or "no_evidence_chunks" in r.risks
            ],
        }

    def write_results(self, output_dir: Path) -> None:
        """Write readiness results to output directory."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        readiness_path = output_dir / "excel_sheet_readiness.jsonl"
        with open(readiness_path, "w", encoding="utf-8") as f:
            for record in self._readiness_records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"Wrote {len(self._readiness_records)} readiness records to {readiness_path}")

    @property
    def readiness_records(self) -> list[SheetReadinessRecord]:
        return self._readiness_records
