"""
証拠品質チェッカー — EvidenceRecord の品質を検証しレポートを出力するモジュール。

全レコードに対して一意性・必須フィールド・種別整合性などを検証し、
JSONL 形式の課題リストと Markdown サマリーを生成する。

出力:
- evidence_quality_report.jsonl
- reports/evidence_quality_summary.md
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.evidence_pipeline.evidence_schema import (
    EvidenceRecord,
    VALID_RECORD_TYPES,
)

logger = logging.getLogger(__name__)

# text_for_embedding が必要な record_type
_EMBEDDING_TYPES = frozenset({
    "table_region",
    "table_row",
    "field_definition",
    "graph_candidate",
    "sheet_summary",
    "business_rule",
})

# text_for_llm が必要な record_type
_LLM_TEXT_TYPES = frozenset({
    "table_region",
    "table_row",
    "field_definition",
    "graph_candidate",
    "table_header_structure",
    "business_rule",
    "sheet_summary",
})


class EvidenceQualityChecker:
    """EvidenceRecord リストの品質を検証するクラス。

    check_all() で問題リストを返し、
    write_report() で JSONL + Markdown レポートを出力する。
    """

    def __init__(self, dataset: str, run_id: str) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def check_all(self, records: list[EvidenceRecord]) -> list[dict[str, Any]]:
        """全レコードを検証して問題リストを返す。"""
        issues: list[dict[str, Any]] = []

        seen_ids: dict[str, int] = {}
        for idx, rec in enumerate(records):
            issues.extend(self._check_record(rec, idx, seen_ids))

        logger.info(
            "EvidenceQualityChecker: %d records checked, %d issues found",
            len(records),
            len(issues),
        )
        return issues

    def write_report(
        self,
        issues: list[dict[str, Any]],
        output_dir: str,
    ) -> None:
        """JSONL 課題ファイルと Markdown サマリーを書き出す。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        jsonl_path = out / "evidence_quality_report.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for issue in issues:
                fh.write(json.dumps(issue, ensure_ascii=False) + "\n")

        summary_dir = out / "reports"
        summary_dir.mkdir(parents=True, exist_ok=True)
        summary_path = summary_dir / "evidence_quality_summary.md"
        summary_path.write_text(
            self._build_summary(issues),
            encoding="utf-8",
        )

        logger.info(
            "EvidenceQualityChecker: wrote %d issues → %s, summary → %s",
            len(issues),
            jsonl_path,
            summary_path,
        )

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    def _check_record(
        self,
        rec: EvidenceRecord,
        idx: int,
        seen_ids: dict[str, int],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []

        def _issue(check: str, detail: str, severity: str = "error") -> dict[str, Any]:
            return {
                "record_index": idx,
                "record_id": rec.record_id,
                "record_type": rec.record_type,
                "sheet_name": rec.sheet_name,
                "row_number": rec.row_number,
                "check": check,
                "detail": detail,
                "severity": severity,
            }

        # record_id uniqueness
        if rec.record_id in seen_ids:
            issues.append(_issue(
                "record_id_duplicate",
                f"record_id '{rec.record_id}' already seen at index {seen_ids[rec.record_id]}",
            ))
        else:
            seen_ids[rec.record_id] = idx

        # record_type validity
        if rec.record_type not in VALID_RECORD_TYPES:
            issues.append(_issue(
                "invalid_record_type",
                f"record_type '{rec.record_type}' is not in VALID_RECORD_TYPES",
            ))

        # text_for_embedding present for embeddable types
        if rec.record_type in _EMBEDDING_TYPES and not rec.text_for_embedding:
            issues.append(_issue(
                "missing_text_for_embedding",
                f"record_type '{rec.record_type}' requires non-empty text_for_embedding",
                severity="warning",
            ))

        # text_for_llm present for text types
        if rec.record_type in _LLM_TEXT_TYPES and not rec.text_for_llm:
            issues.append(_issue(
                "missing_text_for_llm",
                f"record_type '{rec.record_type}' requires non-empty text_for_llm",
                severity="warning",
            ))

        # source_file / sheet_name present
        if not rec.source_file:
            issues.append(_issue(
                "missing_source_file",
                "source_file is empty",
                severity="warning",
            ))
        if not rec.sheet_name:
            issues.append(_issue(
                "missing_sheet_name",
                "sheet_name is empty",
                severity="warning",
            ))

        # table_row specific checks
        if rec.record_type == "table_row":
            if rec.row_number is None:
                issues.append(_issue(
                    "table_row_missing_row_number",
                    "table_row record must have a row_number",
                ))
            if not rec.source_cell_refs:
                issues.append(_issue(
                    "table_row_missing_cell_refs",
                    "table_row record should have source_cell_refs",
                    severity="warning",
                ))
            if rec.table_type == "field_mapping_table":
                issues.extend(self._check_field_mapping_row(rec, idx))

        # graph_candidate checks
        if rec.record_type == "graph_candidate":
            edges = rec.graph_hints.get("candidate_edges", [])
            if not edges:
                issues.append(_issue(
                    "graph_candidate_no_edges",
                    "graph_candidate record has no candidate_edges in graph_hints",
                    severity="warning",
                ))

        # image_reference checks
        if rec.record_type == "image_reference" and not rec.image_path:
            issues.append(_issue(
                "image_reference_missing_path",
                "image_reference record must have a non-empty image_path",
            ))

        return issues

    def _check_field_mapping_row(
        self,
        rec: EvidenceRecord,
        idx: int,
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        roles = set(rec.column_roles.values())

        def _issue(check: str, detail: str) -> dict[str, Any]:
            return {
                "record_index": idx,
                "record_id": rec.record_id,
                "record_type": rec.record_type,
                "sheet_name": rec.sheet_name,
                "row_number": rec.row_number,
                "check": check,
                "detail": detail,
                "severity": "warning",
            }

        if "source_field" not in roles:
            issues.append(_issue(
                "field_mapping_no_source_field",
                "field_mapping_table row has no column with role 'source_field'",
            ))
        if "target_field" not in roles:
            issues.append(_issue(
                "field_mapping_no_target_field",
                "field_mapping_table row has no column with role 'target_field'",
            ))
        return issues

    @staticmethod
    def _build_summary(issues: list[dict[str, Any]]) -> str:
        total = len(issues)
        by_severity: dict[str, int] = defaultdict(int)
        by_check: dict[str, int] = defaultdict(int)
        by_type: dict[str, int] = defaultdict(int)

        for issue in issues:
            by_severity[issue.get("severity", "error")] += 1
            by_check[issue.get("check", "")] += 1
            by_type[issue.get("record_type", "")] += 1

        lines: list[str] = [
            "# Evidence Quality Summary",
            "",
            f"Total issues: **{total}**",
            "",
            "## Breakdown by Severity",
            "",
            "| Severity | Count |",
            "|----------|-------|",
        ]
        for sev in ("error", "warning", "info"):
            lines.append(f"| {sev} | {by_severity.get(sev, 0)} |")

        lines += [
            "",
            "## Breakdown by Check",
            "",
            "| Check | Count |",
            "|-------|-------|",
        ]
        for check, count in sorted(by_check.items(), key=lambda x: -x[1]):
            lines.append(f"| {check} | {count} |")

        lines += [
            "",
            "## Breakdown by Record Type",
            "",
            "| RecordType | Issues |",
            "|------------|--------|",
        ]
        for rtype, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"| {rtype} | {count} |")

        if issues:
            lines += [
                "",
                "## Examples (first 10 issues)",
                "",
                "| # | RecordType | Sheet | Row | Check | Detail |",
                "|---|------------|-------|-----|-------|--------|",
            ]
            for i, issue in enumerate(issues[:10], start=1):
                detail = issue.get("detail", "")[:80]
                lines.append(
                    f"| {i} "
                    f"| {issue.get('record_type', '')} "
                    f"| {issue.get('sheet_name', '')} "
                    f"| {issue.get('row_number', '')} "
                    f"| {issue.get('check', '')} "
                    f"| {detail} |"
                )

        return "\n".join(lines) + "\n"
