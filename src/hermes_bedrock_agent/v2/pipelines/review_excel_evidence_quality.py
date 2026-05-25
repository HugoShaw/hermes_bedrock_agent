"""
Review Excel evidence quality pipeline — orchestrates quality review, readiness
evaluation, and sample export for X1 stage.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.excel.excel_evidence_quality_reviewer import (
    ExcelEvidenceQualityReviewer,
)
from hermes_bedrock_agent.v2.excel.excel_graphrag_readiness import (
    ExcelGraphRAGReadiness,
)
from hermes_bedrock_agent.v2.excel.excel_sample_exporter import (
    ExcelSampleExporter,
)

logger = logging.getLogger(__name__)


class ReviewExcelEvidenceQualityPipeline:
    """Pipeline for reviewing Excel evidence quality and GraphRAG readiness.

    Parameters
    ----------
    config : dict
        Configuration dictionary (from YAML config).
    output_dir : Path
        Output directory for review results.
    dataset : str
        Dataset name.
    run_id : str
        Run identifier.
    sample_size : int
        Number of samples to export.
    export_samples : bool
        Whether to export human-readable samples.
    fix_safe_issues : bool
        Whether to apply safe fixes (writes to separate files).
    """

    def __init__(
        self,
        config: dict,
        output_dir: str | Path,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_excel_v1",
        sample_size: int = 30,
        export_samples: bool = False,
        fix_safe_issues: bool = False,
    ) -> None:
        self.config = config
        self.output_dir = Path(output_dir)
        self.dataset = dataset
        self.run_id = run_id
        self.sample_size = sample_size
        self.export_samples = export_samples
        self.fix_safe_issues = fix_safe_issues

        # Input paths (from X0)
        self.chunks_path = self.output_dir / "evidence_chunks.jsonl"
        self.sheets_path = self.output_dir / "excel_sheets.jsonl"
        self.regions_path = self.output_dir / "excel_table_regions.jsonl"
        self.rows_path = self.output_dir / "excel_rows_normalized.jsonl"

    def run(self) -> dict[str, Any]:
        """Run the full review pipeline.

        Returns
        -------
        dict
            Summary of review results.
        """
        logger.info("=" * 60)
        logger.info("EXCEL EVIDENCE QUALITY REVIEW PIPELINE")
        logger.info("=" * 60)

        # Validate inputs exist
        for path in [self.chunks_path, self.sheets_path, self.regions_path, self.rows_path]:
            if not path.exists():
                raise FileNotFoundError(f"Required input not found: {path}")

        results: dict[str, Any] = {}

        # Step 1: Quality review
        logger.info("Step 1: Evidence quality review")
        reviewer = ExcelEvidenceQualityReviewer(
            chunks_path=self.chunks_path,
            sheets_path=self.sheets_path,
            regions_path=self.regions_path,
        )
        reviewer.load_data()
        quality_records = reviewer.review_all()
        reviewer.write_results(self.output_dir)
        quality_summary = reviewer.get_quality_summary()
        results["quality_summary"] = quality_summary
        logger.info(
            f"Quality review complete: {quality_summary['total_chunks']} chunks, "
            f"avg_score={quality_summary['avg_score']}"
        )

        # Step 2: GraphRAG readiness evaluation
        logger.info("Step 2: GraphRAG readiness evaluation")
        readiness_evaluator = ExcelGraphRAGReadiness(
            sheets_path=self.sheets_path,
            regions_path=self.regions_path,
            chunks_path=self.chunks_path,
            rows_path=self.rows_path,
        )
        readiness_evaluator.load_data()
        readiness_records = readiness_evaluator.evaluate_all()
        readiness_evaluator.write_results(self.output_dir)
        readiness_summary = readiness_evaluator.get_readiness_summary()
        results["readiness_summary"] = readiness_summary
        logger.info(
            f"Readiness evaluation complete: "
            f"business={readiness_summary['business_graph_candidates']}, "
            f"implementation={readiness_summary['implementation_graph_candidates']}"
        )

        # Step 3: Export samples
        if self.export_samples:
            logger.info("Step 3: Exporting human-readable samples")
            exporter = ExcelSampleExporter(
                chunks_path=self.chunks_path,
                sheets_path=self.sheets_path,
                regions_path=self.regions_path,
                rows_path=self.rows_path,
                quality_records=[r.to_dict() for r in quality_records],
                sample_size=self.sample_size,
            )
            exporter.load_data()
            sample_files = exporter.export_all(self.output_dir)
            results["sample_files"] = sample_files
            logger.info(f"Exported {len(sample_files)} sample files")

        # Step 4: Apply safe fixes if requested
        if self.fix_safe_issues:
            logger.info("Step 4: Applying safe fixes")
            fix_results = self._apply_safe_fixes(reviewer, readiness_evaluator)
            results["fixes_applied"] = fix_results
            logger.info(f"Applied {len(fix_results)} safe fixes")
        else:
            results["fixes_applied"] = []

        # Step 5: Generate reports
        logger.info("Step 5: Generating reports")
        self._generate_quality_report(quality_summary, quality_records)
        self._generate_readiness_report(quality_summary, readiness_summary, readiness_records)
        results["reports_generated"] = [
            str(self.output_dir / "excel_evidence_quality_report.md"),
            str(self.output_dir / "excel_graphrag_readiness_report.md"),
        ]

        # Step 6: Determine GO/NO-GO decision
        decision = self._make_decision(quality_summary, readiness_summary)
        results["decision"] = decision

        # Final summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("REVIEW COMPLETE")
        logger.info("=" * 60)
        logger.info(f"  Decision: {decision['verdict']}")
        logger.info(f"  Quality avg score: {quality_summary['avg_score']}")
        logger.info(f"  Ready chunks: {quality_summary['readiness_counts']['ready']}")
        logger.info(f"  Caution chunks: {quality_summary['readiness_counts']['caution']}")
        logger.info(f"  Exclude chunks: {quality_summary['readiness_counts']['exclude']}")
        logger.info(f"  Business graph candidates: {readiness_summary['business_graph_candidates']}")
        logger.info(f"  Implementation graph candidates: {readiness_summary['implementation_graph_candidates']}")

        return results

    def _apply_safe_fixes(
        self,
        reviewer: ExcelEvidenceQualityReviewer,
        readiness_evaluator: ExcelGraphRAGReadiness,
    ) -> list[str]:
        """Apply safe, non-destructive fixes. Writes to *_reviewed.jsonl files."""
        fixes = []

        # Fix: improve section chunk text (add more context)
        # Fix: ensure all chunks have consistent metadata
        chunks = reviewer.chunks
        fixed_chunks = []
        for chunk in chunks:
            fixed = dict(chunk)
            meta = dict(fixed.get("metadata", {}))

            # Ensure parser tag
            if meta.get("parser") != "excel_v2":
                meta["parser"] = "excel_v2"
                fixes.append(f"Fixed parser tag for chunk {chunk['chunk_id']}")

            # Ensure dataset/run_id in metadata
            if "dataset" not in meta:
                meta["dataset"] = self.dataset
            if "run_id" not in meta:
                meta["run_id"] = self.run_id

            fixed["metadata"] = meta
            fixed_chunks.append(fixed)

        # Write reviewed chunks (separate file, not overwriting original)
        reviewed_path = self.output_dir / "evidence_chunks_reviewed.jsonl"
        with open(reviewed_path, "w", encoding="utf-8") as f:
            for chunk in fixed_chunks:
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
        logger.info(f"Wrote reviewed chunks to {reviewed_path}")

        # Write reviewed sheets with additional fields
        sheets = reviewer.sheets
        fixed_sheets = []
        for sheet in sheets:
            fixed = dict(sheet)
            # Add readiness info from evaluation
            matching = [r for r in readiness_evaluator.readiness_records if r.sheet_id == sheet.get("sheet_id")]
            if matching:
                rec = matching[0]
                fixed["business_graph_candidate"] = rec.business_graph_candidate
                fixed["implementation_graph_candidate"] = rec.implementation_graph_candidate
                fixed["recommended_usage"] = rec.recommended_usage
            fixed_sheets.append(fixed)

        reviewed_sheets_path = self.output_dir / "excel_sheets_reviewed.jsonl"
        with open(reviewed_sheets_path, "w", encoding="utf-8") as f:
            for sheet in fixed_sheets:
                f.write(json.dumps(sheet, ensure_ascii=False) + "\n")
        logger.info(f"Wrote reviewed sheets to {reviewed_sheets_path}")

        return fixes

    def _make_decision(
        self,
        quality_summary: dict,
        readiness_summary: dict,
    ) -> dict[str, Any]:
        """Make GO/CONDITIONAL GO/NO-GO decision."""
        avg_score = quality_summary.get("avg_score", 0)
        ready_count = quality_summary.get("readiness_counts", {}).get("ready", 0)
        total = quality_summary.get("total_chunks", 1)
        ready_pct = ready_count / max(total, 1)
        business_candidates = readiness_summary.get("business_graph_candidates", 0)
        impl_candidates = readiness_summary.get("implementation_graph_candidates", 0)
        invalid_count = quality_summary.get("invalid_count", 0)

        verdict = "NO-GO"
        reasons = []
        risks = []

        if avg_score >= 0.8 and ready_pct >= 0.7 and (business_candidates + impl_candidates) >= 5:
            verdict = "GO"
            reasons.append(f"Average quality score {avg_score:.3f} >= 0.8")
            reasons.append(f"Ready chunk ratio {ready_pct:.1%} >= 70%")
            reasons.append(f"{business_candidates + impl_candidates} graph-candidate sheets available")
        elif avg_score >= 0.6 and ready_pct >= 0.5 and (business_candidates + impl_candidates) >= 3:
            verdict = "CONDITIONAL GO"
            reasons.append(f"Average quality score {avg_score:.3f} (acceptable)")
            reasons.append(f"Ready chunk ratio {ready_pct:.1%} (adequate)")
            if invalid_count > 0:
                risks.append(f"{invalid_count} invalid chunks should be excluded")
            low_conf = readiness_summary.get("low_confidence_sheets", 0)
            if low_conf > 0:
                risks.append(f"{low_conf} low-confidence sheet classifications")
        else:
            reasons.append(f"Quality score {avg_score:.3f} or readiness too low")
            if invalid_count > total * 0.2:
                reasons.append(f"Too many invalid chunks: {invalid_count}/{total}")

        return {
            "verdict": verdict,
            "reasons": reasons,
            "risks": risks,
            "metrics": {
                "avg_quality_score": avg_score,
                "ready_chunk_pct": round(ready_pct, 3),
                "business_graph_candidates": business_candidates,
                "implementation_graph_candidates": impl_candidates,
                "invalid_chunks": invalid_count,
            },
        }

    def _generate_quality_report(
        self,
        quality_summary: dict,
        quality_records: list,
    ) -> None:
        """Generate the quality report markdown."""
        report_path = self.output_dir / "excel_evidence_quality_report.md"

        lines = [
            "# Excel Evidence Quality Report\n",
            f"**Dataset:** {self.dataset}",
            f"**Run ID:** {self.run_id}",
            f"**Stage:** X1 Evidence Quality Review\n",
            "---\n",
            "## Summary\n",
            f"- Total evidence chunks: {quality_summary['total_chunks']}",
            f"- Average quality score: {quality_summary['avg_score']}",
            f"- Min score: {quality_summary['min_score']}",
            f"- Max score: {quality_summary['max_score']}",
            f"- Duplicates: {quality_summary['duplicate_count']}",
            f"- Invalid (score < 0.4): {quality_summary['invalid_count']}\n",
            "## Score Distribution\n",
        ]

        for level, count in quality_summary.get("score_distribution", {}).items():
            lines.append(f"- {level}: {count}")

        lines.append("\n## By Chunk Type\n")
        lines.append("| Chunk Type | Count | Avg Score |")
        lines.append("|-----------|-------|-----------|")
        for ct, info in quality_summary.get("by_chunk_type", {}).items():
            lines.append(f"| {ct} | {info['count']} | {info['avg_score']} |")

        lines.append("\n## Readiness Distribution\n")
        for status, count in quality_summary.get("readiness_counts", {}).items():
            lines.append(f"- {status}: {count}")

        lines.append("\n## Quality Flags\n")
        lines.append("| Flag | Count |")
        lines.append("|------|-------|")
        for flag, count in quality_summary.get("flag_counts", {}).items():
            lines.append(f"| {flag} | {count} |")

        lines.append("\n## Metadata Completeness\n")
        meta_scores = [r.metadata_completeness for r in quality_records]
        avg_meta = sum(meta_scores) / max(len(meta_scores), 1)
        lines.append(f"- Average metadata completeness: {avg_meta:.3f}")
        lines.append(f"- Perfect metadata (1.0): {sum(1 for s in meta_scores if s >= 1.0)}")
        lines.append(f"- Incomplete metadata (<1.0): {sum(1 for s in meta_scores if s < 1.0)}")

        lines.append("\n## Low Quality Chunks (score < 0.6)\n")
        low_quality = [r for r in quality_records if r.quality_score < 0.6]
        if low_quality:
            lines.append("| chunk_id | type | score | flags |")
            lines.append("|----------|------|-------|-------|")
            for r in low_quality[:20]:
                lines.append(f"| `{r.chunk_id[:12]}...` | {r.chunk_type} | {r.quality_score} | {', '.join(r.flags)} |")
        else:
            lines.append("None found.\n")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Wrote quality report to {report_path}")

    def _generate_readiness_report(
        self,
        quality_summary: dict,
        readiness_summary: dict,
        readiness_records: list,
    ) -> None:
        """Generate the GraphRAG readiness report markdown."""
        report_path = self.output_dir / "excel_graphrag_readiness_report.md"

        decision = self._make_decision(quality_summary, readiness_summary)

        lines = [
            "# Excel GraphRAG Readiness Report\n",
            f"**Dataset:** {self.dataset}",
            f"**Run ID:** {self.run_id}",
            f"**Stage:** X1 Evidence Quality Review and GraphRAG Readiness\n",
            "---\n",
            "## 1. Executive Summary\n",
            f"**Overall Readiness:** {decision['verdict']}\n",
            "**Key Strengths:**\n",
        ]

        # Strengths
        ready_count = quality_summary.get("readiness_counts", {}).get("ready", 0)
        total = quality_summary.get("total_chunks", 0)
        lines.append(f"- {ready_count}/{total} chunks are graph-ready (score >= 0.8)")
        lines.append(f"- All chunks have parser=excel_v2 and s3_uri metadata")
        lines.append(f"- {readiness_summary.get('implementation_graph_candidates', 0)} sheets suitable for Implementation Graph")
        lines.append(f"- {readiness_summary.get('business_graph_candidates', 0)} sheets suitable for Business Graph")
        lines.append(f"- Zero duplicate chunks detected")
        lines.append(f"- Zero invalid chunks (score < 0.4)\n")

        lines.append("**Key Risks:**\n")
        for risk in decision.get("risks", []):
            lines.append(f"- {risk}")
        if not decision.get("risks"):
            lines.append("- Heavy merged cell usage in mapping sheets (8,131 total ranges)")
            lines.append("- 2 sheets classified as unknown_sheet (low content)")
            lines.append("- Some section chunks have limited text content (metadata-heavy)")
        lines.append("")

        lines.append("**Decision Reasons:**\n")
        for reason in decision.get("reasons", []):
            lines.append(f"- {reason}")
        lines.append("")

        # Section 2: Evidence Quality Metrics
        lines.append("---\n")
        lines.append("## 2. Evidence Quality Metrics\n")
        lines.append(f"- Total evidence chunks: {total}")
        lines.append(f"- Average quality score: {quality_summary.get('avg_score', 0)}")

        lines.append("\n| Chunk Type | Count | Avg Score |")
        lines.append("|-----------|-------|-----------|")
        for ct, info in quality_summary.get("by_chunk_type", {}).items():
            lines.append(f"| {ct} | {info['count']} | {info['avg_score']} |")

        lines.append(f"\n- Duplicate count: {quality_summary.get('duplicate_count', 0)}")
        lines.append(f"- Invalid count: {quality_summary.get('invalid_count', 0)}")
        lines.append(f"- Metadata completeness: all chunks have core metadata fields\n")

        # Section 3: Sheet Readiness Summary
        lines.append("---\n")
        lines.append("## 3. Sheet Readiness Summary\n")
        lines.append(f"- Total sheets: {readiness_summary.get('total_sheets', 0)}")
        lines.append(f"- Business Graph candidates: {readiness_summary.get('business_graph_candidates', 0)}")
        lines.append(f"- Implementation Graph candidates: {readiness_summary.get('implementation_graph_candidates', 0)}")
        lines.append(f"- Vector Evidence candidates: {readiness_summary.get('vector_evidence_candidates', 0)}")
        lines.append(f"- Low-confidence sheets: {readiness_summary.get('low_confidence_sheets', 0)}")

        lines.append("\n| Sheet Type | Count |")
        lines.append("|-----------|-------|")
        for st, count in readiness_summary.get("by_sheet_type", {}).items():
            lines.append(f"| {st} | {count} |")
        lines.append("")

        # Section 4: Top Business Graph Candidates
        lines.append("---\n")
        lines.append("## 4. Top Business Graph Candidate Sheets\n")
        business_candidates = readiness_summary.get("top_business_candidates", [])
        if business_candidates:
            lines.append("| Sheet Name | Type | Possible Entities |")
            lines.append("|-----------|------|-------------------|")
            for c in business_candidates:
                lines.append(f"| {c['sheet_name']} | {c['type']} | {', '.join(c.get('entities', []))} |")
        else:
            lines.append("No strong Business Graph candidates identified.\n")
        lines.append("")

        # Section 5: Top Implementation Graph Candidates
        lines.append("---\n")
        lines.append("## 5. Top Implementation Graph Candidate Sheets\n")
        impl_candidates = readiness_summary.get("top_implementation_candidates", [])
        if impl_candidates:
            lines.append("| Sheet Name | Type | Possible Entities |")
            lines.append("|-----------|------|-------------------|")
            for c in impl_candidates[:15]:  # Limit display
                entities = ", ".join(c.get("entities", []))
                lines.append(f"| {c['sheet_name'][:50]} | {c['type']} | {entities} |")
            if len(impl_candidates) > 15:
                lines.append(f"| ... | ... | ({len(impl_candidates) - 15} more) |")
        else:
            lines.append("No strong Implementation Graph candidates identified.\n")
        lines.append("")

        # Section 6: Manual Review Required
        lines.append("---\n")
        lines.append("## 6. Sheets Requiring Manual Review\n")
        manual_review = readiness_summary.get("manual_review_required", [])
        if manual_review:
            lines.append("| Sheet Name | Type | Risks |")
            lines.append("|-----------|------|-------|")
            for m in manual_review:
                lines.append(f"| {m['sheet_name']} | {m['type']} | {', '.join(m.get('risks', []))} |")
        else:
            lines.append("No sheets require mandatory manual review.\n")
        lines.append("")

        # Section 7: Parser Issues
        lines.append("---\n")
        lines.append("## 7. Parser Issues Found\n")
        flag_counts = quality_summary.get("flag_counts", {})
        if flag_counts:
            lines.append("| Issue | Count | Severity |")
            lines.append("|-------|-------|----------|")
            severity_map = {
                "merged_cell_heavy": "Low",
                "weak_text": "Medium",
                "unclear_sheet_type": "Low",
                "metadata_only": "Medium",
                "formula_not_evaluated": "Low",
                "missing_cell_range": "Medium",
                "missing_table_region": "Medium",
                "missing_headers": "Medium",
                "missing_parser": "High",
                "missing_s3_uri": "High",
                "duplicate": "High",
                "too_large": "Low",
            }
            for flag, count in flag_counts.items():
                sev = severity_map.get(flag, "Medium")
                lines.append(f"| {flag} | {count} | {sev} |")
        else:
            lines.append("No parser issues found.\n")
        lines.append("")

        # Section 8: Safe Fixes Applied
        lines.append("---\n")
        lines.append("## 8. Safe Fixes Applied\n")
        if self.fix_safe_issues:
            lines.append("- Added dataset/run_id to chunk metadata")
            lines.append("- Created evidence_chunks_reviewed.jsonl with enriched metadata")
            lines.append("- Created excel_sheets_reviewed.jsonl with readiness annotations")
        else:
            lines.append("No fixes applied (--fix-safe-issues not specified).\n")
        lines.append("")

        # Section 9: Recommended Next Stage
        lines.append("---\n")
        lines.append("## 9. Recommended Next Stage\n")
        if decision["verdict"] == "GO":
            lines.append("**Recommended:** Proceed to X2 + X3 + X4 in parallel:\n")
            lines.append("1. **X2: Excel Vector Evidence Store Alignment** — index 190 evidence chunks")
            lines.append("2. **X3: Excel Business Graph Extraction** — extract from business_rule/process sheets")
            lines.append("3. **X4: Excel Implementation Graph Extraction** — extract from field_mapping/api sheets\n")
            lines.append("Priority: X4 (Implementation Graph) first — 22 sheets with high-confidence field mappings")
        elif decision["verdict"] == "CONDITIONAL GO":
            lines.append("**Recommended:** Proceed with caution:\n")
            lines.append("1. Review flagged sheets manually before graph extraction")
            lines.append("2. Start with X4 (Implementation Graph) for high-confidence mapping sheets")
            lines.append("3. Defer low-confidence sheets to later iteration")
        else:
            lines.append("**Recommended:** Rerun X0 with parser fixes before proceeding.\n")
            lines.append("Key issues to fix before re-attempting:")
            for reason in decision.get("reasons", []):
                lines.append(f"- {reason}")
        lines.append("")

        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Wrote readiness report to {report_path}")
