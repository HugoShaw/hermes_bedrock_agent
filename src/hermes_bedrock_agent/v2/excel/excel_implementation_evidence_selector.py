"""
Excel implementation evidence selector — select implementation-graph-relevant
evidence chunks from X1 reviewed outputs.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)

# Sheet types suitable for implementation graph
IMPL_SHEET_TYPES = {
    "field_mapping_sheet",
    "api_interface_sheet",
    "data_dictionary_sheet",
    "system_config_sheet",
    "screen_definition_sheet",
    "code_master_sheet",
}

# Chunk types suitable for implementation graph
IMPL_CHUNK_TYPES = {"table", "api", "section"}

# Minimum quality score to include
MIN_QUALITY_SCORE = 0.8


@dataclass
class EvidenceSelectionResult:
    """Result of evidence selection."""
    total_chunks: int = 0
    selected_chunks: int = 0
    excluded_chunks: int = 0
    selected_sheets: list[str] = field(default_factory=list)
    excluded_sheets: list[str] = field(default_factory=list)
    by_sheet_type: dict[str, int] = field(default_factory=dict)
    by_chunk_type: dict[str, int] = field(default_factory=dict)
    manual_review_excluded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ExcelImplementationEvidenceSelector:
    """Select implementation-graph-relevant evidence chunks.

    Uses X1 reviewed outputs (quality scores, readiness assessments)
    to filter chunks suitable for implementation graph extraction.
    """

    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self._chunks: list[dict] = []
        self._quality: list[dict] = []
        self._readiness: list[dict] = []
        self._selected: list[dict] = []

    def load_data(self) -> None:
        """Load reviewed evidence and quality data."""
        # Prefer reviewed files, fallback to originals
        chunks_path = self.output_dir / "evidence_chunks_reviewed.jsonl"
        if not chunks_path.exists():
            chunks_path = self.output_dir / "evidence_chunks.jsonl"

        self._chunks = [
            json.loads(line)
            for line in chunks_path.read_text().strip().split("\n")
            if line.strip()
        ]

        quality_path = self.output_dir / "excel_evidence_quality.jsonl"
        if quality_path.exists():
            self._quality = [
                json.loads(line)
                for line in quality_path.read_text().strip().split("\n")
                if line.strip()
            ]

        readiness_path = self.output_dir / "excel_sheet_readiness.jsonl"
        if readiness_path.exists():
            self._readiness = [
                json.loads(line)
                for line in readiness_path.read_text().strip().split("\n")
                if line.strip()
            ]

        logger.info(
            f"Loaded {len(self._chunks)} chunks, {len(self._quality)} quality records, "
            f"{len(self._readiness)} readiness records"
        )

    def select(self) -> tuple[list[dict], EvidenceSelectionResult]:
        """Select implementation-relevant evidence chunks.

        Returns
        -------
        tuple of (selected_chunks, selection_result)
        """
        if not self._chunks:
            self.load_data()

        # Build lookups
        quality_by_id = {q["chunk_id"]: q for q in self._quality}
        impl_sheet_ids = {
            r["sheet_id"]
            for r in self._readiness
            if r.get("implementation_graph_candidate")
        }

        selected = []
        excluded_sheets = set()
        selected_sheet_names = set()
        manual_review_excluded = []

        for chunk in self._chunks:
            meta = chunk.get("metadata", {})
            chunk_id = chunk["chunk_id"]
            chunk_type = chunk["chunk_type"]
            sheet_id = meta.get("sheet_id", "")
            sheet_name = meta.get("sheet_name", "")
            sheet_type = meta.get("guessed_sheet_type", "unknown_sheet")

            # Quality gate
            quality = quality_by_id.get(chunk_id, {})
            score = quality.get("quality_score", 1.0)
            if score < MIN_QUALITY_SCORE:
                excluded_sheets.add(sheet_name)
                continue

            # Sheet type filter
            if sheet_type not in IMPL_SHEET_TYPES:
                excluded_sheets.add(sheet_name)
                continue

            # Chunk type filter
            if chunk_type not in IMPL_CHUNK_TYPES:
                excluded_sheets.add(sheet_name)
                continue

            # Sheet readiness filter
            if impl_sheet_ids and sheet_id not in impl_sheet_ids:
                excluded_sheets.add(sheet_name)
                manual_review_excluded.append(sheet_name)
                continue

            selected.append(chunk)
            selected_sheet_names.add(sheet_name)

        # Build result stats
        by_sheet_type: dict[str, int] = {}
        by_chunk_type: dict[str, int] = {}
        for c in selected:
            st = c.get("metadata", {}).get("guessed_sheet_type", "unknown")
            ct = c["chunk_type"]
            by_sheet_type[st] = by_sheet_type.get(st, 0) + 1
            by_chunk_type[ct] = by_chunk_type.get(ct, 0) + 1

        result = EvidenceSelectionResult(
            total_chunks=len(self._chunks),
            selected_chunks=len(selected),
            excluded_chunks=len(self._chunks) - len(selected),
            selected_sheets=sorted(selected_sheet_names),
            excluded_sheets=sorted(excluded_sheets - selected_sheet_names),
            by_sheet_type=by_sheet_type,
            by_chunk_type=by_chunk_type,
            manual_review_excluded=sorted(set(manual_review_excluded)),
        )

        self._selected = selected
        logger.info(
            f"Selected {len(selected)}/{len(self._chunks)} chunks for implementation graph"
        )
        return selected, result

    def write_results(self) -> Path:
        """Write selected evidence to file."""
        out_path = self.output_dir / "excel_implementation_candidate_evidence.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for chunk in self._selected:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        logger.info(f"Wrote {len(self._selected)} candidates to {out_path}")
        return out_path
