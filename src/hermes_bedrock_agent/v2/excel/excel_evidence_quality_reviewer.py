"""
Excel evidence quality reviewer — evaluate generated evidence chunks for GraphRAG readiness.

Computes quality scores, identifies issues, and flags chunks needing attention.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Quality flags
FLAG_MISSING_SHEET_NAME = "missing_sheet_name"
FLAG_MISSING_CELL_RANGE = "missing_cell_range"
FLAG_MISSING_TABLE_REGION = "missing_table_region"
FLAG_MISSING_HEADERS = "missing_headers"
FLAG_WEAK_TEXT = "weak_text"
FLAG_TOO_LARGE = "too_large"
FLAG_DUPLICATE = "duplicate"
FLAG_METADATA_ONLY = "metadata_only"
FLAG_UNCLEAR_SHEET_TYPE = "unclear_sheet_type"
FLAG_FORMULA_NOT_EVALUATED = "formula_not_evaluated"
FLAG_MERGED_CELL_HEAVY = "merged_cell_heavy"
FLAG_MISSING_PARSER = "missing_parser"
FLAG_MISSING_S3_URI = "missing_s3_uri"

# Thresholds
MIN_TEXT_LENGTH = 80
MAX_TEXT_LENGTH = 3000
WEAK_TEXT_THRESHOLD = 120
METADATA_ONLY_THRESHOLD = 100


@dataclass
class ChunkQualityRecord:
    """Quality assessment for a single evidence chunk."""
    chunk_id: str
    chunk_type: str
    title: str
    text_length: int
    quality_score: float = 1.0
    flags: list[str] = field(default_factory=list)
    metadata_completeness: float = 1.0
    readability_score: float = 1.0
    graph_readiness: str = "ready"  # ready / caution / exclude
    workbook_name: str = ""
    sheet_name: str = ""
    guessed_sheet_type: str = ""
    cell_range: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class ExcelEvidenceQualityReviewer:
    """Review quality of Excel evidence chunks for GraphRAG readiness.

    Parameters
    ----------
    chunks_path : Path
        Path to evidence_chunks.jsonl from X0.
    sheets_path : Path
        Path to excel_sheets.jsonl from X0.
    regions_path : Path
        Path to excel_table_regions.jsonl from X0.
    """

    def __init__(
        self,
        chunks_path: Path,
        sheets_path: Path,
        regions_path: Path,
    ) -> None:
        self.chunks_path = Path(chunks_path)
        self.sheets_path = Path(sheets_path)
        self.regions_path = Path(regions_path)
        self._chunks: list[dict] = []
        self._sheets: list[dict] = []
        self._regions: list[dict] = []
        self._quality_records: list[ChunkQualityRecord] = []

    def load_data(self) -> None:
        """Load all input data."""
        self._chunks = [
            json.loads(line) for line in self.chunks_path.read_text().strip().split("\n") if line.strip()
        ]
        self._sheets = [
            json.loads(line) for line in self.sheets_path.read_text().strip().split("\n") if line.strip()
        ]
        self._regions = [
            json.loads(line) for line in self.regions_path.read_text().strip().split("\n") if line.strip()
        ]
        logger.info(
            f"Loaded {len(self._chunks)} chunks, {len(self._sheets)} sheets, {len(self._regions)} regions"
        )

    def review_all(self) -> list[ChunkQualityRecord]:
        """Review all chunks and return quality records."""
        if not self._chunks:
            self.load_data()

        # Build lookup for sheets by sheet_id
        sheet_lookup = {s.get("sheet_id", ""): s for s in self._sheets}

        # Detect duplicates by text prefix
        text_prefix_map: dict[str, list[str]] = {}
        for c in self._chunks:
            prefix = c["text"][:200]
            text_prefix_map.setdefault(prefix, []).append(c["chunk_id"])
        duplicate_ids = set()
        for prefix, ids in text_prefix_map.items():
            if len(ids) > 1:
                duplicate_ids.update(ids[1:])  # keep first, flag rest

        self._quality_records = []
        for chunk in self._chunks:
            record = self._review_chunk(chunk, sheet_lookup, duplicate_ids)
            self._quality_records.append(record)

        logger.info(f"Reviewed {len(self._quality_records)} chunks")
        return self._quality_records

    def _review_chunk(
        self,
        chunk: dict,
        sheet_lookup: dict[str, dict],
        duplicate_ids: set[str],
    ) -> ChunkQualityRecord:
        """Review a single chunk."""
        metadata = chunk.get("metadata", {})
        chunk_id = chunk["chunk_id"]
        chunk_type = chunk["chunk_type"]
        title = chunk.get("title", "")
        text = chunk.get("text", "")
        text_length = len(text)

        record = ChunkQualityRecord(
            chunk_id=chunk_id,
            chunk_type=chunk_type,
            title=title,
            text_length=text_length,
            workbook_name=metadata.get("workbook_name", ""),
            sheet_name=metadata.get("sheet_name", ""),
            guessed_sheet_type=metadata.get("guessed_sheet_type", ""),
            cell_range=metadata.get("cell_range", ""),
        )

        flags = []
        score = 1.0

        # Check metadata completeness
        expected_keys = {"workbook_id", "workbook_name", "parser", "s3_uri"}
        if chunk_type != "summary":
            expected_keys.update({"sheet_id", "sheet_name", "sheet_index", "guessed_sheet_type"})
        if chunk_type in ("table", "api", "testcase", "config"):
            expected_keys.update({"table_region_id", "cell_range", "row_numbers", "columns"})

        present_keys = set(metadata.keys())
        missing_keys = expected_keys - present_keys
        metadata_completeness = 1.0 - (len(missing_keys) / max(len(expected_keys), 1))
        record.metadata_completeness = metadata_completeness

        # Specific metadata checks
        if not metadata.get("sheet_name") and chunk_type != "summary":
            flags.append(FLAG_MISSING_SHEET_NAME)
            score -= 0.15

        if not metadata.get("cell_range") and chunk_type in ("table", "api"):
            flags.append(FLAG_MISSING_CELL_RANGE)
            score -= 0.1

        if not metadata.get("table_region_id") and chunk_type in ("table", "api"):
            flags.append(FLAG_MISSING_TABLE_REGION)
            score -= 0.1

        if not metadata.get("columns") and chunk_type in ("table", "api"):
            flags.append(FLAG_MISSING_HEADERS)
            score -= 0.1

        if metadata.get("parser") != "excel_v2":
            flags.append(FLAG_MISSING_PARSER)
            score -= 0.2

        if not metadata.get("s3_uri"):
            flags.append(FLAG_MISSING_S3_URI)
            score -= 0.1

        # Text quality checks
        if text_length < WEAK_TEXT_THRESHOLD:
            flags.append(FLAG_WEAK_TEXT)
            score -= 0.15
            if text_length < METADATA_ONLY_THRESHOLD:
                flags.append(FLAG_METADATA_ONLY)
                score -= 0.1

        if text_length > MAX_TEXT_LENGTH:
            flags.append(FLAG_TOO_LARGE)
            score -= 0.05

        # Readability: check if text has actual content beyond headers
        content_lines = [l for l in text.split("\n") if l.strip() and not l.startswith(("Workbook:", "Sheet:", "Region:", "Rows:", "Sheet index:", "Size:", "Non-empty", "Merged", "Has formula", "Has comment", "Guessed", "Table region", "Extension:", "Source:", "Sheet count:"))]
        readability = min(1.0, len(content_lines) / max(1, text_length / 200))
        record.readability_score = round(readability, 2)
        if readability < 0.3:
            score -= 0.1

        # Duplicate check
        if chunk_id in duplicate_ids:
            flags.append(FLAG_DUPLICATE)
            score -= 0.3

        # Sheet type clarity
        sheet_type = metadata.get("guessed_sheet_type", "unknown_sheet")
        if sheet_type == "unknown_sheet" and chunk_type not in ("summary",):
            flags.append(FLAG_UNCLEAR_SHEET_TYPE)
            score -= 0.1

        # Formula check
        if metadata.get("has_formula"):
            flags.append(FLAG_FORMULA_NOT_EVALUATED)
            score -= 0.05

        # Merged cell heaviness - check from sheet data
        sheet_id = metadata.get("sheet_id", "")
        if sheet_id and sheet_id in {s.get("sheet_id") for s in self._sheets}:
            sheet_data = next((s for s in self._sheets if s.get("sheet_id") == sheet_id), None)
            if sheet_data:
                merged_count = len(sheet_data.get("merged_cell_ranges", []))
                if merged_count > 500:
                    flags.append(FLAG_MERGED_CELL_HEAVY)
                    score -= 0.05

        # Clamp score
        score = max(0.0, min(1.0, score))
        record.quality_score = round(score, 2)
        record.flags = flags

        # Determine graph readiness
        if score >= 0.8:
            record.graph_readiness = "ready"
        elif score >= 0.6:
            record.graph_readiness = "caution"
        else:
            record.graph_readiness = "exclude"

        # Build reason
        if flags:
            record.reason = f"Issues: {', '.join(flags)}"
        else:
            record.reason = "No issues found"

        return record

    def get_quality_summary(self) -> dict[str, Any]:
        """Get aggregate quality metrics."""
        if not self._quality_records:
            return {}

        scores = [r.quality_score for r in self._quality_records]
        by_type = {}
        for r in self._quality_records:
            by_type.setdefault(r.chunk_type, []).append(r.quality_score)

        flag_counts: dict[str, int] = {}
        for r in self._quality_records:
            for f in r.flags:
                flag_counts[f] = flag_counts.get(f, 0) + 1

        readiness_counts = {"ready": 0, "caution": 0, "exclude": 0}
        for r in self._quality_records:
            readiness_counts[r.graph_readiness] += 1

        return {
            "total_chunks": len(self._quality_records),
            "avg_score": round(sum(scores) / len(scores), 3),
            "min_score": min(scores),
            "max_score": max(scores),
            "score_distribution": {
                "excellent_1.0": sum(1 for s in scores if s >= 0.95),
                "good_0.8_0.95": sum(1 for s in scores if 0.8 <= s < 0.95),
                "usable_0.6_0.8": sum(1 for s in scores if 0.6 <= s < 0.8),
                "weak_0.4_0.6": sum(1 for s in scores if 0.4 <= s < 0.6),
                "invalid_below_0.4": sum(1 for s in scores if s < 0.4),
            },
            "by_chunk_type": {
                ct: {
                    "count": len(scores_list),
                    "avg_score": round(sum(scores_list) / len(scores_list), 3),
                }
                for ct, scores_list in by_type.items()
            },
            "flag_counts": dict(sorted(flag_counts.items(), key=lambda x: -x[1])),
            "readiness_counts": readiness_counts,
            "duplicate_count": sum(1 for r in self._quality_records if FLAG_DUPLICATE in r.flags),
            "invalid_count": sum(1 for r in self._quality_records if r.quality_score < 0.4),
        }

    def write_results(self, output_dir: Path) -> None:
        """Write quality review results to output directory."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Write quality JSONL
        quality_path = output_dir / "excel_evidence_quality.jsonl"
        with open(quality_path, "w", encoding="utf-8") as f:
            for record in self._quality_records:
                f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        logger.info(f"Wrote {len(self._quality_records)} quality records to {quality_path}")

    @property
    def quality_records(self) -> list[ChunkQualityRecord]:
        return self._quality_records

    @property
    def chunks(self) -> list[dict]:
        return self._chunks

    @property
    def sheets(self) -> list[dict]:
        return self._sheets
