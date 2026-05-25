"""
Evidence Store Builder — orchestrates the full Stage 04 pipeline.

Pipeline steps:
  1. Load documents from S3
  2. Parse sections
  3. Build summaries (extractive)
  4. Build evidence chunks
  5. Validate with V2 schemas
  6. Write JSONL outputs
  7. Optionally build vector index
  8. Generate report

All outputs go to: data/outputs/{run_id}/
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from hermes_bedrock_agent.v2.schemas.document_schema import DocumentRecord, SectionRecord
from hermes_bedrock_agent.v2.schemas.evidence_schema import EvidenceChunk, ALLOWED_CHUNK_TYPES
from hermes_bedrock_agent.v2.evidence.document_loader import DocumentLoader
from hermes_bedrock_agent.v2.evidence.document_structure_parser import DocumentStructureParser
from hermes_bedrock_agent.v2.evidence.summary_builder import (
    build_document_summary,
    build_section_summary,
)
from hermes_bedrock_agent.v2.evidence.chunk_builder import ChunkBuilder, ChunkConfig
from hermes_bedrock_agent.v2.evidence.evidence_index import EvidenceIndex, EvidenceIndexStatus
from hermes_bedrock_agent.v2.evidence.jsonl_io import write_jsonl, ensure_parent_dir

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    """Accumulated statistics for the pipeline run."""
    documents_loaded: int = 0
    documents_failed: int = 0
    sections_total: int = 0
    chunks_total: int = 0
    chunks_rejected: int = 0
    chunks_by_type: dict[str, int] = field(default_factory=dict)
    chunks_by_doc_type: dict[str, int] = field(default_factory=dict)
    total_chunk_chars: int = 0
    max_chunk_chars: int = 0
    min_chunk_chars: int = 999999
    empty_chunks_rejected: int = 0
    missing_metadata_count: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    index_status: EvidenceIndexStatus = field(default_factory=EvidenceIndexStatus)

    @property
    def avg_chunk_chars(self) -> float:
        return self.total_chunk_chars / max(self.chunks_total, 1)


class EvidenceStoreBuilder:
    """Orchestrate the full Stage 04 evidence store pipeline.

    Parameters
    ----------
    config_path:
        Path to the YAML config file (e.g. configs/murata_semantic_v2.yaml).
    run_id:
        Run identifier (default: from config).
    dataset:
        Dataset name (default: from config).
    build_index:
        Whether to build the LanceDB vector index.
    max_files:
        Limit on documents to load (for dev/testing).
    summary_mode:
        Summary generation mode: extractive | none.
    """

    def __init__(
        self,
        config_path: str,
        run_id: str | None = None,
        dataset: str | None = None,
        build_index: bool = False,
        max_files: int | None = None,
        summary_mode: str = "extractive",
    ) -> None:
        self.config_path = config_path
        self.build_index = build_index
        self.max_files = max_files
        self.summary_mode = summary_mode

        # Load config
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.run_id = run_id or self.config["run"]["run_id"]
        self.dataset = dataset or self.config["source"]["dataset"]
        self.project = self.config["source"].get("project", "murata")
        self.output_dir = Path(self.config["output"]["output_dir"])

        # Chunking config
        chunking = self.config.get("chunking", {})
        self.chunk_config = ChunkConfig(
            chunk_size=chunking.get("chunk_size", 1500),
            chunk_overlap=chunking.get("chunk_overlap", 200),
            max_chunk_size=chunking.get("max_chunk_size", 3000),
            min_chunk_size=chunking.get("min_chunk_size", 100),
            summary_mode=self.summary_mode,
            dataset=self.dataset,
            run_id=self.run_id,
            project=self.project,
        )

        self.stats = PipelineStats()

    def run(self) -> PipelineStats:
        """Execute the full pipeline and return statistics."""
        start_time = time.time()
        logger.info("=" * 60)
        logger.info("Stage 04: Vector Evidence Store Builder")
        logger.info("  config: %s", self.config_path)
        logger.info("  run_id: %s", self.run_id)
        logger.info("  dataset: %s", self.dataset)
        logger.info("  build_index: %s", self.build_index)
        logger.info("  max_files: %s", self.max_files or "unlimited")
        logger.info("  summary_mode: %s", self.summary_mode)
        logger.info("=" * 60)

        all_documents: list[DocumentRecord] = []
        all_sections: list[SectionRecord] = []
        all_chunks: list[EvidenceChunk] = []

        # Step 1: Load documents
        logger.info("Step 1: Loading documents from S3...")
        try:
            loader = DocumentLoader(
                bucket=self.config["source"]["s3_bucket"],
                prefix=self.config["source"]["s3_prefix"],
                dataset=self.dataset,
                run_id=self.run_id,
                project=self.project,
                max_files=self.max_files,
            )
            doc_pairs = loader.load()
        except Exception as exc:
            err = f"Document loading failed: {exc}"
            logger.error(err)
            self.stats.errors.append(err)
            self.stats.duration_seconds = time.time() - start_time
            self._write_report()
            return self.stats

        self.stats.documents_loaded = len(doc_pairs)
        logger.info("Loaded %d documents", len(doc_pairs))

        # Step 2-4: Process each document
        parser = DocumentStructureParser()
        chunk_builder = ChunkBuilder(config=self.chunk_config)

        for doc, raw in doc_pairs:
            all_documents.append(doc)

            # Step 2: Parse sections
            try:
                sections = parser.parse(doc, raw)
            except Exception as exc:
                logger.warning("Section parse failed for %s: %s", doc.source_path, exc)
                self.stats.documents_failed += 1
                self.stats.warnings.append(f"Section parse failed: {doc.source_path}: {exc}")
                sections = []

            all_sections.extend(sections)

            # Step 3: Build summaries
            doc_summary = ""
            section_summaries: dict[str, str] = {}
            if self.summary_mode != "none":
                try:
                    doc_summary = build_document_summary(doc, sections, mode=self.summary_mode)
                    for sec in sections:
                        if sec.text.strip():
                            sec_sum = build_section_summary(sec, mode=self.summary_mode)
                            if sec_sum:
                                section_summaries[sec.section_id] = sec_sum
                except Exception as exc:
                    logger.warning("Summary build failed for %s: %s", doc.source_path, exc)
                    self.stats.warnings.append(f"Summary failed: {doc.source_path}: {exc}")

            # Step 4: Build chunks
            try:
                chunks = chunk_builder.build_chunks(doc, sections, doc_summary, section_summaries)
            except Exception as exc:
                logger.warning("Chunk build failed for %s: %s", doc.source_path, exc)
                self.stats.documents_failed += 1
                self.stats.warnings.append(f"Chunk build failed: {doc.source_path}: {exc}")
                chunks = []

            # Step 5: Validate
            valid_chunks = self._validate_chunks(chunks)
            all_chunks.extend(valid_chunks)

        self.stats.sections_total = len(all_sections)
        self.stats.chunks_total = len(all_chunks)

        # Compute stats
        self._compute_chunk_stats(all_chunks)

        # Step 6: Write JSONL outputs
        logger.info("Step 6: Writing JSONL outputs...")
        self._write_jsonl_outputs(all_documents, all_sections, all_chunks)

        # Step 7: Optionally build vector index
        logger.info("Step 7: Vector index...")
        index = EvidenceIndex(
            collection_name=self.config.get("vector_store", {}).get(
                "collection_name", "murata_e2e_murata_semantic_v2"
            ),
            db_path=self.config.get("vector_store", {}).get("db_path", "data/lancedb"),
            embedding_model=self.config.get("vector_store", {}).get(
                "embedding_model", "amazon.titan-embed-text-v2:0"
            ),
            region="ap-northeast-1",
        )
        self.stats.index_status = index.build(all_chunks, build_index=self.build_index)

        # Step 8: Generate report
        self.stats.duration_seconds = time.time() - start_time
        logger.info("Step 8: Generating report...")
        self._write_report()

        logger.info("=" * 60)
        logger.info("Stage 04 complete in %.1fs", self.stats.duration_seconds)
        logger.info("  Documents: %d", self.stats.documents_loaded)
        logger.info("  Sections: %d", self.stats.sections_total)
        logger.info("  Chunks: %d", self.stats.chunks_total)
        logger.info("  Index status: %s", self.stats.index_status.status_label)
        logger.info("=" * 60)

        return self.stats

    def _validate_chunks(self, chunks: list[EvidenceChunk]) -> list[EvidenceChunk]:
        """Validate chunks and filter invalid ones."""
        valid: list[EvidenceChunk] = []
        for chunk in chunks:
            # Check text not empty
            if not chunk.text or not chunk.text.strip():
                self.stats.empty_chunks_rejected += 1
                self.stats.chunks_rejected += 1
                continue
            # Check chunk_type is valid
            if chunk.chunk_type not in ALLOWED_CHUNK_TYPES:
                self.stats.chunks_rejected += 1
                self.stats.warnings.append(
                    f"Invalid chunk_type '{chunk.chunk_type}' for chunk {chunk.chunk_id}"
                )
                continue
            # Check run_id matches
            if chunk.run_id != self.run_id:
                chunk.run_id = self.run_id  # Fix silently
            if chunk.dataset != self.dataset:
                chunk.dataset = self.dataset  # Fix silently
            valid.append(chunk)
        return valid

    def _compute_chunk_stats(self, chunks: list[EvidenceChunk]) -> None:
        """Compute statistics from the final chunk set."""
        type_counter: Counter = Counter()
        doc_type_counter: Counter = Counter()

        for chunk in chunks:
            text_len = len(chunk.text)
            self.stats.total_chunk_chars += text_len
            self.stats.max_chunk_chars = max(self.stats.max_chunk_chars, text_len)
            self.stats.min_chunk_chars = min(self.stats.min_chunk_chars, text_len)
            type_counter[chunk.chunk_type] += 1
            doc_type_counter[chunk.doc_type] += 1

            # Check for missing metadata
            if not chunk.metadata:
                self.stats.missing_metadata_count += 1

        if not chunks:
            self.stats.min_chunk_chars = 0

        self.stats.chunks_by_type = dict(type_counter.most_common())
        self.stats.chunks_by_doc_type = dict(doc_type_counter.most_common())

    def _write_jsonl_outputs(
        self,
        documents: list[DocumentRecord],
        sections: list[SectionRecord],
        chunks: list[EvidenceChunk],
    ) -> None:
        """Write all JSONL output files."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        doc_path = self.output_dir / "documents.jsonl"
        sec_path = self.output_dir / "sections.jsonl"
        chunk_path = self.output_dir / "evidence_chunks.jsonl"

        write_jsonl(doc_path, documents)
        write_jsonl(sec_path, sections)
        write_jsonl(chunk_path, chunks)

        logger.info("Written: %s (%d records)", doc_path, len(documents))
        logger.info("Written: %s (%d records)", sec_path, len(sections))
        logger.info("Written: %s (%d records)", chunk_path, len(chunks))

    def _write_report(self) -> None:
        """Generate the vector_index_report.md."""
        report_path = self.output_dir / "vector_index_report.md"
        ensure_parent_dir(report_path)

        lines = [
            "# Vector Evidence Store Report",
            "",
            f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Config:** {self.config_path}",
            f"**Run ID:** {self.run_id}",
            f"**Dataset:** {self.dataset}",
            f"**Duration:** {self.stats.duration_seconds:.1f}s",
            "",
            "---",
            "",
            "## Input",
            "",
            f"| Field | Value |",
            f"| ----- | ----- |",
            f"| S3 bucket | {self.config['source']['s3_bucket']} |",
            f"| S3 prefix | {self.config['source']['s3_prefix']} |",
            f"| Max files | {self.max_files or 'unlimited'} |",
            f"| Summary mode | {self.summary_mode} |",
            "",
            "---",
            "",
            "## Output Summary",
            "",
            f"| Metric | Count |",
            f"| ------ | ----- |",
            f"| Documents loaded | {self.stats.documents_loaded} |",
            f"| Documents failed | {self.stats.documents_failed} |",
            f"| Sections total | {self.stats.sections_total} |",
            f"| Evidence chunks total | {self.stats.chunks_total} |",
            f"| Chunks rejected | {self.stats.chunks_rejected} |",
            f"| Empty chunks rejected | {self.stats.empty_chunks_rejected} |",
            f"| Missing metadata | {self.stats.missing_metadata_count} |",
            "",
            "---",
            "",
            "## Chunk Statistics",
            "",
            f"| Metric | Value |",
            f"| ------ | ----- |",
            f"| Average chunk length (chars) | {self.stats.avg_chunk_chars:.0f} |",
            f"| Max chunk length (chars) | {self.stats.max_chunk_chars} |",
            f"| Min chunk length (chars) | {self.stats.min_chunk_chars} |",
            f"| Total chars | {self.stats.total_chunk_chars} |",
            "",
            "---",
            "",
            "## Chunks by Type",
            "",
            "| chunk_type | count |",
            "| ---------- | ----- |",
        ]
        for ct, count in sorted(self.stats.chunks_by_type.items()):
            lines.append(f"| {ct} | {count} |")

        lines.extend([
            "",
            "---",
            "",
            "## Chunks by Doc Type",
            "",
            "| doc_type | count |",
            "| -------- | ----- |",
        ])
        for dt, count in sorted(self.stats.chunks_by_doc_type.items()):
            lines.append(f"| {dt} | {count} |")

        lines.extend([
            "",
            "---",
            "",
            "## Vector Index Status",
            "",
            f"| Field | Value |",
            f"| ----- | ----- |",
            f"| Requested | {self.stats.index_status.requested} |",
            f"| Status | {self.stats.index_status.status_label} |",
            f"| Collection | {self.stats.index_status.collection_name or 'N/A'} |",
            f"| Chunks indexed | {self.stats.index_status.chunks_indexed} |",
            f"| Error | {self.stats.index_status.error or 'None'} |",
            "",
        ])

        if self.stats.errors:
            lines.extend([
                "---",
                "",
                "## Errors",
                "",
            ])
            for err in self.stats.errors:
                lines.append(f"- {err}")
            lines.append("")

        if self.stats.warnings:
            lines.extend([
                "---",
                "",
                "## Warnings",
                "",
            ])
            for warn in self.stats.warnings[:50]:
                lines.append(f"- {warn}")
            if len(self.stats.warnings) > 50:
                lines.append(f"- ... and {len(self.stats.warnings) - 50} more")
            lines.append("")

        lines.extend([
            "---",
            "",
            "## Next Recommended Action",
            "",
            "Execute Stage 05: Business Semantic Graph",
            "",
            "Use the evidence chunks (especially `summary` and `section` types) as the",
            "primary extraction source for business-layer graph nodes and edges.",
            "",
        ])

        report_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Report written: %s", report_path)
