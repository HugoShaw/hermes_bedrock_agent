"""
Excel business evidence selector — select business-graph-relevant evidence
chunks from X1 reviewed outputs.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Sheet types that produce business graph nodes
BUSINESS_SHEET_TYPES = {
    "business_process_sheet",
    "business_rule_sheet",
    "test_case_sheet",
    "screen_definition_sheet",
    "code_master_sheet",
    "operation_sheet",
}

# Sheets to exclude
EXCLUDE_SHEETS = {
    "概要",
    "変更履歴",
    "DataSpider開発仕様",
    "補足事項(DataSpider)",
}

# Chunk types useful for business graph
BUSINESS_CHUNK_TYPES = {"table", "section", "summary"}


@dataclass
class BusinessSelectionResult:
    """Stats from business evidence selection."""
    total_chunks: int = 0
    selected_chunks: int = 0
    excluded_chunks: int = 0
    selected_sheets: list[str] = field(default_factory=list)
    excluded_sheets: list[str] = field(default_factory=list)
    manual_review_excluded: list[str] = field(default_factory=list)
    by_sheet_type: dict[str, int] = field(default_factory=dict)
    by_chunk_type: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_chunks": self.total_chunks,
            "selected_chunks": self.selected_chunks,
            "excluded_chunks": self.excluded_chunks,
            "selected_sheets": self.selected_sheets,
            "excluded_sheets": self.excluded_sheets,
            "manual_review_excluded": self.manual_review_excluded,
            "by_sheet_type": self.by_sheet_type,
            "by_chunk_type": self.by_chunk_type,
        }


class ExcelBusinessEvidenceSelector:
    """Select business-relevant evidence from reviewed chunks."""

    def __init__(self, output_dir: str | Path = "data/outputs/sample_20260519_excel_v1") -> None:
        self.output_dir = Path(output_dir)
        self.chunks: list[dict] = []
        self.quality_records: list[dict] = []
        self.readiness_records: list[dict] = []

    def load_data(self) -> None:
        """Load reviewed chunks and readiness data."""
        # Try reviewed first, fallback to original
        reviewed_path = self.output_dir / "evidence_chunks_reviewed.jsonl"
        original_path = self.output_dir / "evidence_chunks.jsonl"
        chunks_path = reviewed_path if reviewed_path.exists() else original_path

        self.chunks = [json.loads(l) for l in open(chunks_path)]

        quality_path = self.output_dir / "excel_evidence_quality.jsonl"
        if quality_path.exists():
            self.quality_records = [json.loads(l) for l in open(quality_path)]

        readiness_path = self.output_dir / "excel_sheet_readiness.jsonl"
        if readiness_path.exists():
            self.readiness_records = [json.loads(l) for l in open(readiness_path)]

        logger.info(
            f"Loaded {len(self.chunks)} chunks, "
            f"{len(self.quality_records)} quality records, "
            f"{len(self.readiness_records)} readiness records"
        )

    def select(self) -> tuple[list[dict], BusinessSelectionResult]:
        """Select business-relevant evidence chunks."""
        result = BusinessSelectionResult(total_chunks=len(self.chunks))

        # Build quality lookup
        quality_by_id = {q["chunk_id"]: q for q in self.quality_records}

        # Build readiness lookup
        biz_candidate_sheets = set()
        for r in self.readiness_records:
            if r.get("business_graph_candidate"):
                biz_candidate_sheets.add(r["sheet_name"])

        selected = []
        seen_sheets = set()
        excluded_sheets = set()

        for chunk in self.chunks:
            meta = chunk.get("metadata", {})
            sheet_name = meta.get("sheet_name", "")
            sheet_type = meta.get("guessed_sheet_type", "")
            chunk_type = chunk.get("chunk_type", "")
            chunk_id = chunk.get("chunk_id", "")

            # Exclude known non-business sheets
            if sheet_name in EXCLUDE_SHEETS:
                excluded_sheets.add(sheet_name)
                continue

            # Check quality
            q = quality_by_id.get(chunk_id, {})
            quality_score = q.get("quality_score", 0.8)
            if quality_score < 0.6:
                excluded_sheets.add(sheet_name)
                continue

            # Select business candidates
            is_business = (
                sheet_name in biz_candidate_sheets
                or sheet_type in BUSINESS_SHEET_TYPES
                or "business" in str(meta.get("recommended_usage", []))
            )

            if not is_business:
                excluded_sheets.add(sheet_name)
                continue

            # Prefer relevant chunk types
            if chunk_type not in BUSINESS_CHUNK_TYPES:
                continue

            selected.append(chunk)
            seen_sheets.add(sheet_name)

            # Track stats
            result.by_sheet_type[sheet_type] = result.by_sheet_type.get(sheet_type, 0) + 1
            result.by_chunk_type[chunk_type] = result.by_chunk_type.get(chunk_type, 0) + 1

        # Manual review exclusions
        for sheet_name in EXCLUDE_SHEETS:
            if sheet_name in excluded_sheets:
                result.manual_review_excluded.append(sheet_name)

        result.selected_chunks = len(selected)
        result.excluded_chunks = result.total_chunks - len(selected)
        result.selected_sheets = sorted(seen_sheets)
        result.excluded_sheets = sorted(excluded_sheets - seen_sheets)

        logger.info(f"Selected {len(selected)}/{len(self.chunks)} chunks for business graph")
        return selected, result

    def write_results(self, selected: list[dict] | None = None) -> None:
        """Write candidate evidence to file."""
        if selected is None:
            selected, _ = self.select()

        out_path = self.output_dir / "excel_business_candidate_evidence.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for chunk in selected:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        logger.info(f"Wrote {len(selected)} candidates to {out_path}")
