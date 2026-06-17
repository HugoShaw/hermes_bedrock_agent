"""Parsing orchestrator: end-to-end multi-type parsing for a project.

Coordinates file profiling, role inference, strategy selection, and
multi-parser execution to produce normalized Markdown output.
"""

from __future__ import annotations

import json
import logging
import tempfile
import time
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .utils import compute_content_hash, download_s3_file, sanitize_filename

from ..models.document import (
    DocumentRole,
    FileState,
    ParsedDocument,
    ProjectFile,
    ProjectManifest,
    SourceType,
)
from .registry import create_default_registry
from .role_inference import run_role_inference
from .strategy import SKIP_TYPES, VLM_TYPES, run_strategy_selection

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Dataclass for results
# ─────────────────────────────────────────────────────────────────────────────


class ParsingResult:
    """Summary of a parsing run."""

    def __init__(self) -> None:
        self.files_scanned: int = 0
        self.files_parsed: int = 0
        self.files_skipped: int = 0
        self.files_failed: int = 0
        self.files_already_parsed: int = 0
        self.by_parser: dict[str, int] = {}
        self.by_role: dict[str, int] = {}
        self.skip_reasons: dict[str, int] = {}
        self.errors: list[dict[str, str]] = []
        self.total_vlm_cost: float = 0.0
        self.output_files: list[str] = []
        self.duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "files_parsed": self.files_parsed,
            "files_skipped": self.files_skipped,
            "files_failed": self.files_failed,
            "files_already_parsed": self.files_already_parsed,
            "by_parser": self.by_parser,
            "by_role": self.by_role,
            "skip_reasons": self.skip_reasons,
            "errors": self.errors,
            "total_vlm_cost": round(self.total_vlm_cost, 4),
            "output_files_count": len(self.output_files),
            "duration_seconds": round(self.duration_seconds, 1),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


_safe_filename = sanitize_filename
_compute_content_hash = compute_content_hash
_download_s3_file = download_s3_file

_TYPE_SUBDIR_MAP = {
    "docx": "docx",
    "doc_vlm": "pdf",
    "pdf_vlm": "pdf",
    "html": "html",
    "text": "txt",
    "markdown": "txt",
    "csv": "csv",
    "image_vlm": "images",
    "code": "code",
    "excel_vlm": "excel",
    "mermaid": "mermaid",
    "mermaid_v2": "mermaid",
}


def _get_type_subdir(parser_type: str) -> str:
    """Map parser_type to type-aware subdirectory under parsed/ and evidence/.

    Canonical directories: excel, mermaid, csv, code, pdf, docx, html, txt, images.
    No longer uses a generic 'docs' bucket.
    """
    return _TYPE_SUBDIR_MAP.get(parser_type, "txt")


def _generate_frontmatter(
    pf: ProjectFile,
    project_id: str,
    parse_method: str,
    content_hash: str,
    evidence_paths: list[str] | None = None,
    *,
    document_id: str = "",
    document_name: str = "",
) -> str:
    """Generate YAML frontmatter for parsed Markdown output.

    Emits canonical metadata fields expected by the chunker:
      source_file, source_type, parser_type, document_type, document_id, document_name,
      project_id, evidence_paths, etc.
    """
    # Normalize source_type: excel_sheet → excel (canonical)
    source_type_val = pf.source_type.value
    if source_type_val == "excel_sheet":
        source_type_val = "excel"
    # document_type mirrors the canonical source_type
    document_type_val = source_type_val
    lines = [
        "---",
        f"source_file: \"{pf.relative_path}\"",
        f"source_type: {source_type_val}",
        f"document_role: {pf.document_role}",
        f"parser_type: {pf.parser_type}",
        f"document_type: {document_type_val}",
        f"document_id: \"{document_id}\"",
        f"document_name: \"{document_name}\"",
        f"project_id: {project_id}",
        f"parsed_at: \"{datetime.now().isoformat()}\"",
        f"content_hash: \"{content_hash}\"",
        f"file_size_bytes: {pf.size_bytes}",
    ]
    if evidence_paths:
        lines.append("evidence_paths:")
        for ep in evidence_paths:
            lines.append(f"  - \"{ep}\"")
    lines.append("---")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ─────────────────────────────────────────────────────────────────────────────


def run_project_parsing(
    project_id: str,
    manifest: ProjectManifest,
    output_dir: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    skip_vlm: bool = False,
    limit: int = 0,
) -> ParsingResult:
    """Run multi-type parsing for all files in a project manifest.

    Args:
        project_id: Project identifier
        manifest: ProjectManifest with all files
        output_dir: Root output directory (e.g., outputs/yangma_v2)
        dry_run: If True, only classify and report without parsing
        force: Re-parse files that already have output
        skip_vlm: Skip VLM-based parsers (pdf_vlm, image_vlm)
        limit: Process at most N parseable files (0 = no limit)

    Returns:
        ParsingResult with statistics
    """
    start_time = time.time()
    result = ParsingResult()
    result.files_scanned = len(manifest.files)

    # Step 1: Run role inference on all files
    logger.info("Step 1: Running role inference on %d files...", len(manifest.files))
    run_role_inference(manifest.files)

    # Step 2: Run strategy selection
    logger.info("Step 2: Running strategy selection...")
    run_strategy_selection(manifest.files)

    # Count by role
    for pf in manifest.files:
        role = pf.document_role or "unclassified"
        result.by_role[role] = result.by_role.get(role, 0) + 1

    # Step 3: Determine which files to parse
    parsed_dir = output_dir / "parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = output_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    candidates: list[ProjectFile] = []
    for pf in manifest.files:
        if pf.parser_type in SKIP_TYPES:
            result.files_skipped += 1
            reason = pf.skip_reason or pf.parser_type
            result.skip_reasons[reason] = result.skip_reasons.get(reason, 0) + 1
            continue

        if skip_vlm and pf.parser_type in VLM_TYPES:
            result.files_skipped += 1
            reason = "vlm_skipped_by_flag"
            result.skip_reasons[reason] = result.skip_reasons.get(reason, 0) + 1
            pf.skip_reason = reason
            continue

        # Check if already parsed (output file exists)
        safe_name = _safe_filename(pf.relative_path)
        type_subdir = _get_type_subdir(pf.parser_type)
        output_path = parsed_dir / type_subdir / f"{safe_name}.md"
        if output_path.exists() and not force:
            result.files_already_parsed += 1
            pf.state = FileState.PARSED
            pf.parsed_output_path = str(output_path)
            continue

        candidates.append(pf)

    if limit > 0:
        candidates = candidates[:limit]

    logger.info(
        "Step 3: %d files to parse, %d skipped, %d already parsed",
        len(candidates), result.files_skipped, result.files_already_parsed,
    )

    if dry_run:
        # In dry-run mode, just report what would be parsed
        for pf in candidates:
            parser_type = pf.parser_type
            result.by_parser[parser_type] = result.by_parser.get(parser_type, 0) + 1
        result.files_parsed = len(candidates)
        result.duration_seconds = time.time() - start_time
        return result

    # Step 4: Create parser registry and parse
    registry = create_default_registry()

    with tempfile.TemporaryDirectory(prefix="dualrag_parse_") as tmpdir:
        tmp_root = Path(tmpdir)

        for i, pf in enumerate(candidates):
            logger.info(
                "Parsing [%d/%d] %s (%s) ...",
                i + 1, len(candidates), pf.relative_path, pf.parser_type,
            )

            is_s3 = pf.path.startswith("s3://")
            safe_name = _safe_filename(pf.relative_path)

            # Resolve local file path
            if is_s3:
                # Preserve extension for parser detection
                ext = PurePosixPath(pf.relative_path).suffix
                local_path = tmp_root / f"{safe_name}{ext}"
            else:
                local_path = Path(pf.path)

            # Download from S3 if needed
            if is_s3:
                try:
                    _download_s3_file(pf.path, local_path)
                except Exception as exc:
                    logger.error("Download failed for %s: %s", pf.relative_path, exc)
                    pf.state = FileState.PARSE_FAILED
                    pf.error = f"download_failed: {exc}"
                    result.files_failed += 1
                    result.errors.append({
                        "file": pf.relative_path,
                        "error": f"download_failed: {exc}",
                    })
                    continue

            # Compute content hash
            try:
                pf.content_hash = _compute_content_hash(local_path)
            except Exception:
                pf.content_hash = ""

            # Find parser
            parser = registry.get_parser(local_path, pf.source_type)
            if parser is None:
                logger.warning("No parser found for %s (%s)", pf.relative_path, pf.source_type)
                pf.state = FileState.PARSE_FAILED
                pf.error = "no_parser_available"
                result.files_failed += 1
                result.errors.append({
                    "file": pf.relative_path,
                    "error": "no_parser_available",
                })
                continue

            # Update state
            pf.state = FileState.PARSING

            # Build parser config
            type_subdir = _get_type_subdir(pf.parser_type)
            type_evidence_dir = evidence_dir / type_subdir
            type_evidence_dir.mkdir(parents=True, exist_ok=True)
            file_evidence_dir = type_evidence_dir / safe_name
            parse_cfg: dict[str, Any] = {
                "vlm_enabled": True,
                "dry_run": False,
                "output_dir": file_evidence_dir,
            }

            # Parse
            try:
                docs = parser.parse(
                    local_path,
                    project_id,
                    config=parse_cfg,
                    relative_path=pf.relative_path,
                )
            except Exception as exc:
                logger.exception("Parse failed for %s: %s", pf.relative_path, exc)
                pf.state = FileState.PARSE_FAILED
                pf.error = str(exc)[:500]
                result.files_failed += 1
                result.errors.append({
                    "file": pf.relative_path,
                    "error": str(exc)[:300],
                })
                continue

            if not docs:
                logger.warning("Parser returned no documents for %s", pf.relative_path)
                pf.state = FileState.PARSE_FAILED
                pf.error = "parser_returned_empty"
                result.files_failed += 1
                result.errors.append({
                    "file": pf.relative_path,
                    "error": "parser_returned_empty",
                })
                continue

            # Write output Markdown with frontmatter
            doc = docs[0]
            evidence_paths = doc.evidence_paths or []
            frontmatter = _generate_frontmatter(
                pf, project_id, doc.parse_method,
                doc.content_hash, evidence_paths,
                document_id=doc.doc_id,
                document_name=doc.title,
            )

            type_parsed_dir = parsed_dir / type_subdir
            type_parsed_dir.mkdir(parents=True, exist_ok=True)
            output_path = type_parsed_dir / f"{safe_name}.md"
            full_content = f"{frontmatter}\n\n{doc.content_markdown}"
            output_path.write_text(full_content, encoding="utf-8")

            # Update manifest entry
            pf.state = FileState.PARSED
            pf.parsed_at = datetime.now().isoformat()
            pf.parsed_output_path = str(output_path)
            pf.error = ""

            # Track stats
            result.files_parsed += 1
            result.by_parser[pf.parser_type] = result.by_parser.get(pf.parser_type, 0) + 1
            result.output_files.append(str(output_path))

            cost = doc.metadata.get("estimated_cost_usd", 0.0)
            result.total_vlm_cost += cost

            logger.info(
                "  → PARSED: %s (%d chars, parser=%s)",
                safe_name, len(doc.content_markdown), pf.parser_type,
            )

    result.duration_seconds = time.time() - start_time
    return result


def save_parsing_manifest(
    manifest: ProjectManifest,
    result: ParsingResult,
    output_dir: Path,
) -> Path:
    """Save the enhanced parsing manifest with role/strategy annotations."""
    manifest_data = manifest.to_dict()
    manifest_data["parsing_run"] = {
        "timestamp": datetime.now().isoformat(),
        "result": result.to_dict(),
    }
    manifest_data["manifest_version"] = "2.1"

    out_path = output_dir / "parsing_manifest.json"
    out_path.write_text(
        json.dumps(manifest_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Parsing manifest saved: %s", out_path)
    return out_path
