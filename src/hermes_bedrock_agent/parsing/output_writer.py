"""Unified output writer for the parse-all command.

Writes parser output to a canonical directory structure:
    parsed/excel/<workbook_name>/sheet_XX.md        (with YAML frontmatter)
    parsed/mermaid/mermaid_parsed.md                (chunk-ready Mermaid markdown)
    evidence/excel/<workbook_name>/sheet_XX/         (PDF + PNG + metadata)
    evidence/mermaid/                               (reserved for Mermaid evidence)
    intermediates/mermaid/                          (raw .mmd, structure JSON, linkage)
    legacy_compat/<WorkbookName>/vlm_parsed/         (symlink → parsed/excel/...)
    legacy_compat/<WorkbookName>/pdf/                (symlink → evidence PDFs)
    legacy_compat/<WorkbookName>/images/             (symlink → evidence PNGs)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkbookPaths:
    """Path bundle for a single workbook within the unified output structure."""

    workbook_name: str
    safe_name: str  # filesystem-safe name (same as workbook_name for Japanese — Path handles it)
    # Staging dirs (where parsers write initially — same layout as legacy)
    staging_dir: Path  # run_dir / _staging / <name>
    pdf_staging: Path  # staging_dir / pdf
    image_staging: Path  # staging_dir / images
    vlm_staging: Path  # staging_dir / vlm_parsed
    # Canonical output dirs
    parsed_dir: Path  # run_dir / parsed / excel / <name>
    evidence_dir: Path  # run_dir / evidence / excel / <name>
    legacy_dir: Path  # run_dir / legacy_compat / <name>


@dataclass
class WorkbookResult:
    """Results for one workbook after reorganization."""

    workbook_name: str
    sheets_parsed: int = 0
    pdf_count: int = 0
    image_count: int = 0
    parsed_md_count: int = 0
    evidence_files: int = 0
    legacy_symlinks_created: bool = False


@dataclass
class MermaidResult:
    """Results for Mermaid parsing output."""

    parsed_path: str = ""  # path to parsed/mermaid/mermaid_parsed.md
    intermediates_dir: str = ""  # path to intermediates/mermaid/
    node_count: int = 0
    edge_count: int = 0
    subgraph_count: int = 0
    linked_workbook: Optional[str] = None
    linked_sheet: Optional[str] = None
    linkage_confidence: float = 0.0
    source_files: list = field(default_factory=list)


class UnifiedOutputWriter:
    """Writes parser output to canonical structure with legacy_compat symlinks."""

    def __init__(self, run_dir: Path, project_id: str):
        self.run_dir = run_dir
        self.project_id = project_id
        self.parsed_base = run_dir / "parsed" / "excel"
        self.evidence_base = run_dir / "evidence" / "excel"
        self.legacy_base = run_dir / "legacy_compat"
        self.intermediates_base = run_dir / "intermediates"
        self._staging_base = run_dir / "_staging"
        self._workbook_results: list[WorkbookResult] = []
        self._mermaid_result: Optional[MermaidResult] = None

    def setup_workbook(self, workbook_name: str) -> WorkbookPaths:
        """Create staging directory structure for a workbook.

        Parsers write to staging dirs (same flat layout as legacy).
        After parsing, call reorganize_workbook() to move to canonical structure.
        """
        safe_name = workbook_name  # Japanese filenames work on Linux/ext4

        staging_dir = self._staging_base / safe_name
        pdf_staging = staging_dir / "pdf"
        image_staging = staging_dir / "images"
        vlm_staging = staging_dir / "vlm_parsed"

        # Create staging dirs
        pdf_staging.mkdir(parents=True, exist_ok=True)
        image_staging.mkdir(parents=True, exist_ok=True)
        vlm_staging.mkdir(parents=True, exist_ok=True)

        # Create canonical output dirs
        parsed_dir = self.parsed_base / safe_name
        evidence_dir = self.evidence_base / safe_name
        legacy_dir = self.legacy_base / safe_name

        parsed_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        legacy_dir.mkdir(parents=True, exist_ok=True)

        return WorkbookPaths(
            workbook_name=workbook_name,
            safe_name=safe_name,
            staging_dir=staging_dir,
            pdf_staging=pdf_staging,
            image_staging=image_staging,
            vlm_staging=vlm_staging,
            parsed_dir=parsed_dir,
            evidence_dir=evidence_dir,
            legacy_dir=legacy_dir,
        )

    def reorganize_workbook(
        self,
        wb_paths: WorkbookPaths,
        s3_source: str,
        parse_results: list,
    ) -> WorkbookResult:
        """Move parsed output from staging to canonical structure.

        1. Move sheet_XX.md from staging/vlm_parsed/ → parsed/excel/<name>/ (add frontmatter)
        2. Move PDFs and PNGs to evidence/excel/<name>/sheet_XX/
        3. Create legacy_compat symlinks
        """
        result = WorkbookResult(workbook_name=wb_paths.workbook_name)

        # Step 1: Move and enrich markdown files
        for md_file in sorted(wb_paths.vlm_staging.glob("sheet_*.md")):
            sheet_name = md_file.stem  # e.g., "sheet_01"
            content = md_file.read_text(encoding="utf-8")

            # Extract sheet index
            try:
                sheet_idx = int(sheet_name.replace("sheet_", ""))
            except ValueError:
                sheet_idx = 0

            # Build frontmatter
            evidence_rel = f"evidence/excel/{wb_paths.safe_name}/{sheet_name}/"
            frontmatter = self._build_frontmatter(
                source_file=s3_source,
                workbook_name=wb_paths.workbook_name,
                sheet_index=sheet_idx,
                sheet_name=sheet_name,
                evidence_path=evidence_rel,
            )

            # Write to canonical location with frontmatter
            dest = wb_paths.parsed_dir / md_file.name
            dest.write_text(frontmatter + "\n\n" + content, encoding="utf-8")
            result.parsed_md_count += 1

        # Also move cross_sheet_summary.md if it exists
        cross_summary = wb_paths.vlm_staging / "cross_sheet_summary.md"
        if cross_summary.exists():
            dest = wb_paths.parsed_dir / "cross_sheet_summary.md"
            shutil.copy2(str(cross_summary), str(dest))

        # Step 2: Organize evidence files per-sheet
        for pdf_file in sorted(wb_paths.pdf_staging.glob("sheet_*.pdf")):
            sheet_name = pdf_file.stem
            sheet_evidence = wb_paths.evidence_dir / sheet_name
            sheet_evidence.mkdir(parents=True, exist_ok=True)

            # Move PDF
            dest_pdf = sheet_evidence / pdf_file.name
            shutil.copy2(str(pdf_file), str(dest_pdf))
            result.pdf_count += 1
            result.evidence_files += 1

            # Move corresponding PNG (full-page render)
            png_file = wb_paths.image_staging / f"{sheet_name}.png"
            if png_file.exists():
                dest_png = sheet_evidence / "full.png"
                shutil.copy2(str(png_file), str(dest_png))
                result.image_count += 1
                result.evidence_files += 1

            # Also copy VLM-annotated PNG if exists
            vlm_png = wb_paths.image_staging / f"{sheet_name}_vlm.png"
            if vlm_png.exists():
                dest_vlm = sheet_evidence / "vlm_annotated.png"
                shutil.copy2(str(vlm_png), str(dest_vlm))
                result.evidence_files += 1

            # Copy tile images if they exist
            tiles_dir = wb_paths.image_staging / "tiles" / sheet_name
            if not tiles_dir.exists():
                tiles_dir = wb_paths.image_staging / f"{sheet_name}_tiles"
            if tiles_dir.exists() and tiles_dir.is_dir():
                dest_tiles = sheet_evidence / "tiles"
                if not dest_tiles.exists():
                    shutil.copytree(str(tiles_dir), str(dest_tiles))
                tile_count = len(list(dest_tiles.glob("*.png")))
                result.evidence_files += tile_count

            # Write per-sheet metadata.json
            meta = {
                "workbook_name": wb_paths.workbook_name,
                "sheet_name": sheet_name,
                "sheet_index": int(sheet_name.replace("sheet_", "")) if "sheet_" in sheet_name else 0,
                "project_id": self.project_id,
                "pdf_file": pdf_file.name,
                "has_full_png": png_file.exists(),
                "has_vlm_png": vlm_png.exists(),
                "has_tiles": tiles_dir.exists() if tiles_dir else False,
                "reorganized_at": datetime.now().isoformat(),
            }
            meta_path = sheet_evidence / "metadata.json"
            meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            result.evidence_files += 1

        result.sheets_parsed = result.parsed_md_count

        # Step 3: Create legacy_compat symlinks
        self._create_legacy_symlinks(wb_paths)
        result.legacy_symlinks_created = True

        self._workbook_results.append(result)
        return result

    def _build_frontmatter(
        self,
        source_file: str,
        workbook_name: str,
        sheet_index: int,
        sheet_name: str,
        evidence_path: str,
    ) -> str:
        """Build YAML frontmatter string.

        Generates all fields required by downstream consumers:
          - chunker.py reads: source_file, source_type, parser_type, document_role, content_hash
          - graph scanner reads: source_file, source_type, parser_type, document_role
          - build-kb needs: project_id
          - future consumers: document_type, document_id, document_name, display_name

        Backward-compat: source_type, parser_type retained for existing chunker/graph code.
        """
        import hashlib

        # Deterministic document_id: hash of project + workbook (stable across re-parses)
        doc_id_input = f"{self.project_id}:{workbook_name}"
        document_id = hashlib.sha256(doc_id_input.encode()).hexdigest()[:16]

        # original_relative_path: strip s3://bucket/ prefix to get relative path
        original_relative = source_file
        if source_file.startswith("s3://"):
            # s3://bucket/path/to/file.xlsx → path/to/file.xlsx
            parts = source_file.split("/", 3)
            original_relative = parts[3] if len(parts) > 3 else source_file

        # Display name: workbook + sheet for human readability
        display_name = f"{workbook_name} / {sheet_name}"

        # Evidence paths as YAML list (all evidence for this sheet)
        evidence_base = evidence_path.rstrip("/")
        evidence_paths_yaml = (
            f"  - \"{evidence_base}/{sheet_name}.pdf\"\n"
            f"  - \"{evidence_base}/full.png\""
        )

        lines = [
            "---",
            f'project_id: "{self.project_id}"',
            f'source_file: "{source_file}"',
            f'source_type: "excel"',
            f'document_type: "excel"',
            f'document_role: "data_source"',
            f'parser_type: "excel_vlm"',
            f'document_id: "{document_id}"',
            f'document_name: "{workbook_name}"',
            f'original_relative_path: "{original_relative}"',
            f'workbook_name: "{workbook_name}"',
            f"sheet_index: {sheet_index}",
            f'sheet_name: "{sheet_name}"',
            f'display_name: "{display_name}"',
            f'unit_type: "sheet"',
            f'parsed_at: "{datetime.now().isoformat()}"',
            f'parser_version: "2.1"',
            f'evidence_path: "{evidence_path}"',
            "evidence_paths:",
            evidence_paths_yaml,
            "---",
        ]
        return "\n".join(lines)

    def _create_legacy_symlinks(self, wb_paths: WorkbookPaths) -> None:
        """Create legacy_compat/ symlinks for backward compatibility.

        legacy_compat/<name>/vlm_parsed/ → ../../parsed/excel/<name>/
        legacy_compat/<name>/pdf/        → (dir with symlinks to evidence PDFs)
        legacy_compat/<name>/images/     → (dir with symlinks to evidence PNGs)
        """
        # vlm_parsed symlink → parsed/excel/<name>/
        vlm_link = wb_paths.legacy_dir / "vlm_parsed"
        if not vlm_link.exists():
            # Compute relative path from legacy_compat/<name>/ to parsed/excel/<name>/
            rel_target = os.path.relpath(wb_paths.parsed_dir, wb_paths.legacy_dir)
            vlm_link.symlink_to(rel_target)
            logger.debug("Symlink: %s → %s", vlm_link, rel_target)

        # pdf/ directory with symlinks to individual PDFs in evidence
        pdf_link_dir = wb_paths.legacy_dir / "pdf"
        pdf_link_dir.mkdir(exist_ok=True)
        for sheet_dir in sorted(wb_paths.evidence_dir.iterdir()):
            if sheet_dir.is_dir():
                pdf_file = sheet_dir / f"{sheet_dir.name}.pdf"
                if pdf_file.exists():
                    link_path = pdf_link_dir / pdf_file.name
                    if not link_path.exists():
                        rel = os.path.relpath(pdf_file, pdf_link_dir)
                        link_path.symlink_to(rel)

        # images/ directory with symlinks to full.png files
        img_link_dir = wb_paths.legacy_dir / "images"
        img_link_dir.mkdir(exist_ok=True)
        for sheet_dir in sorted(wb_paths.evidence_dir.iterdir()):
            if sheet_dir.is_dir():
                full_png = sheet_dir / "full.png"
                if full_png.exists():
                    # Name as sheet_XX.png for legacy compatibility
                    link_name = f"{sheet_dir.name}.png"
                    link_path = img_link_dir / link_name
                    if not link_path.exists():
                        rel = os.path.relpath(full_png, img_link_dir)
                        link_path.symlink_to(rel)
                # Also link VLM annotated
                vlm_png = sheet_dir / "vlm_annotated.png"
                if vlm_png.exists():
                    link_name = f"{sheet_dir.name}_vlm.png"
                    link_path = img_link_dir / link_name
                    if not link_path.exists():
                        rel = os.path.relpath(vlm_png, img_link_dir)
                        link_path.symlink_to(rel)
                # tiles symlink
                tiles_dir = sheet_dir / "tiles"
                if tiles_dir.exists():
                    link_path = img_link_dir / f"{sheet_dir.name}_tiles"
                    if not link_path.exists():
                        rel = os.path.relpath(tiles_dir, img_link_dir)
                        link_path.symlink_to(rel)

    def write_mermaid_parsed(
        self,
        mermaid_results: list,
        links: list,
        source_s3_prefix: str = "",
    ) -> MermaidResult:
        """Write Mermaid parsed output to canonical structure.

        Generates:
            parsed/mermaid/mermaid_parsed.md     — chunk-ready markdown with frontmatter
            intermediates/mermaid/mermaid_raw.mmd — raw Mermaid source(s)
            intermediates/mermaid/mermaid_structure.json — machine-readable structure
            intermediates/mermaid/linkage_report.json — linking results

        Args:
            mermaid_results: List of (stem, source_key, MermaidParseResult) tuples.
            links: List of FlowchartLink objects from the linker.
            source_s3_prefix: S3 prefix for source attribution.

        Returns:
            MermaidResult with paths and statistics.
        """
        if not mermaid_results:
            return MermaidResult()

        # Create output directories
        parsed_mermaid_dir = self.run_dir / "parsed" / "mermaid"
        parsed_mermaid_dir.mkdir(parents=True, exist_ok=True)
        intermediates_mermaid_dir = self.intermediates_base / "mermaid"
        intermediates_mermaid_dir.mkdir(parents=True, exist_ok=True)
        evidence_mermaid_dir = self.run_dir / "evidence" / "mermaid"
        evidence_mermaid_dir.mkdir(parents=True, exist_ok=True)

        # Aggregate stats
        total_nodes = 0
        total_edges = 0
        total_subgraphs = 0
        source_files: list[str] = []
        all_nodes = []
        all_edges = []
        all_subgraphs = []
        raw_contents: list[str] = []

        for stem, source_key, result in mermaid_results:
            total_nodes += len(result.nodes)
            total_edges += len(result.edges)
            total_subgraphs += len(result.subgraphs)
            source_files.append(source_key)
            all_nodes.extend(result.nodes)
            all_edges.extend(result.edges)
            all_subgraphs.extend(result.subgraphs)
            raw_contents.append(result.raw_content)

            # Write individual raw files to intermediates
            raw_file = intermediates_mermaid_dir / f"{stem}_raw.mmd"
            raw_file.write_text(result.raw_content, encoding="utf-8")

        # Write combined raw Mermaid source
        combined_raw = intermediates_mermaid_dir / "mermaid_raw.mmd"
        combined_raw.write_text("\n\n".join(raw_contents), encoding="utf-8")

        # Write structure JSON
        structure = {
            "source_files": source_files,
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "total_subgraphs": total_subgraphs,
            "diagrams": [],
        }
        for stem, source_key, result in mermaid_results:
            structure["diagrams"].append({
                "stem": stem,
                "source_key": source_key,
                "diagram_type": result.diagram_type,
                "nodes": [n.model_dump() for n in result.nodes],
                "edges": [e.model_dump() for e in result.edges],
                "subgraphs": [sg.model_dump() for sg in result.subgraphs],
            })
        structure_path = intermediates_mermaid_dir / "mermaid_structure.json"
        structure_path.write_text(
            json.dumps(structure, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Write linkage report to intermediates
        if links:
            linkage_path = intermediates_mermaid_dir / "linkage_report.json"
            linkage_path.write_text(
                json.dumps([l.model_dump() for l in links], indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        # Determine linkage info from best link
        linked_workbook = None
        linked_sheet = None
        linkage_confidence = 0.0
        if links:
            best_link = max(links, key=lambda l: l.match_confidence)
            if best_link.match_confidence > 0:
                linked_workbook = best_link.excel_workbook
                linked_sheet = best_link.excel_sheet
                linkage_confidence = best_link.match_confidence

        # Build chunk-ready parsed markdown
        import hashlib
        source_file = source_files[0] if len(source_files) == 1 else source_s3_prefix
        doc_id_input = f"{self.project_id}:mermaid:{','.join(source_files)}"
        document_id = hashlib.sha256(doc_id_input.encode()).hexdigest()[:16]

        # Determine original_relative_path
        original_relative = source_file
        if source_file.startswith("s3://"):
            parts = source_file.split("/", 3)
            original_relative = parts[3] if len(parts) > 3 else source_file

        # Build frontmatter
        fm_lines = [
            "---",
            f'project_id: "{self.project_id}"',
            f'source_file: "{source_file}"',
            f'source_type: "mermaid"',
            f'document_type: "flowchart"',
            f'document_role: "flowchart_source"',
            f'parser_type: "mermaid_parser"',
            f'parser_version: "2.1"',
            f'document_id: "{document_id}"',
            f'document_name: "mermaid_parsed"',
            f'original_relative_path: "{original_relative}"',
            f'display_name: "Mermaid Flowchart"',
        ]
        if linked_workbook:
            fm_lines.append(f'linked_excel_workbook: "{linked_workbook}"')
        else:
            fm_lines.append("linked_excel_workbook: null")
        if linked_sheet:
            fm_lines.append(f'linked_excel_sheet: "{linked_sheet}"')
        else:
            fm_lines.append("linked_excel_sheet: null")
        if linkage_confidence > 0:
            fm_lines.append(f"linkage_confidence: {linkage_confidence:.2f}")
        else:
            fm_lines.append("linkage_confidence: null")
        fm_lines.append("mermaid_preferred: true")
        fm_lines.append(f'parsed_at: "{datetime.now().isoformat()}"')
        fm_lines.append("evidence_paths:")
        fm_lines.append('  - "intermediates/mermaid/mermaid_structure.json"')
        fm_lines.append('  - "intermediates/mermaid/mermaid_raw.mmd"')
        fm_lines.append("---")
        frontmatter = "\n".join(fm_lines)

        # Build body: human-readable, chunk-searchable markdown
        body_lines: list[str] = []
        body_lines.append("# Mermaid Flowchart Analysis")
        body_lines.append("")
        body_lines.append(f"**Source files:** {len(source_files)}")
        body_lines.append(f"**Total nodes:** {total_nodes} | **Edges:** {total_edges} | **Subgraphs:** {total_subgraphs}")
        if linked_workbook:
            body_lines.append(f"**Linked workbook:** {linked_workbook}")
        body_lines.append("")

        # Summary per diagram
        for stem, source_key, result in mermaid_results:
            body_lines.append(f"## Diagram: {stem}")
            body_lines.append("")
            body_lines.append(f"**Source:** `{source_key}`  ")
            body_lines.append(f"**Type:** {result.diagram_type}  ")
            body_lines.append(f"**Nodes:** {len(result.nodes)} | **Edges:** {len(result.edges)} | **Subgraphs:** {len(result.subgraphs)}")
            body_lines.append("")

            # Subgraphs (functional modules)
            if result.subgraphs:
                body_lines.append("### Functional Modules (Subgraphs)")
                body_lines.append("")
                for sg in result.subgraphs:
                    body_lines.append(f"#### {sg.label}")
                    sg_nodes = [n for n in result.nodes if n.subgraph == sg.id]
                    if sg_nodes:
                        for n in sg_nodes:
                            type_marker = {"decision": "◇", "terminal": "◎", "subprocess": "▣", "annotation": "📝"}.get(n.node_type, "□")
                            body_lines.append(f"- {type_marker} `{n.id}` — {n.label}")
                    body_lines.append("")

            # Node table
            if result.nodes:
                body_lines.append("### Nodes")
                body_lines.append("")
                body_lines.append("| ID | Label | Type | Subgraph |")
                body_lines.append("|---|---|---|---|")
                for n in result.nodes:
                    sg_label = ""
                    if n.subgraph:
                        sg_obj = next((sg for sg in result.subgraphs if sg.id == n.subgraph), None)
                        sg_label = sg_obj.label if sg_obj else n.subgraph
                    body_lines.append(f"| `{n.id}` | {n.label} | {n.node_type} | {sg_label} |")
                body_lines.append("")

            # Edge table
            if result.edges:
                body_lines.append("### Edges")
                body_lines.append("")
                body_lines.append("| Source | Target | Label |")
                body_lines.append("|---|---|---|")
                for e in result.edges:
                    body_lines.append(f"| `{e.source}` | `{e.target}` | {e.label or '—'} |")
                body_lines.append("")

            # Decision points
            decisions = [n for n in result.nodes if n.node_type == "decision"]
            if decisions:
                body_lines.append("### Decision Points")
                body_lines.append("")
                for d in decisions:
                    outgoing = [e for e in result.edges if e.source == d.id]
                    body_lines.append(f"- **{d.label}** (`{d.id}`)")
                    for e in outgoing:
                        target_node = next((n for n in result.nodes if n.id == e.target), None)
                        target_label = target_node.label if target_node else e.target
                        body_lines.append(f"  - {e.label or '→'} → {target_label}")
                body_lines.append("")

            # Business flow description
            body_lines.append("### Business Flow")
            body_lines.append("")
            if result.subgraphs:
                body_lines.append("Process flow through modules:")
                body_lines.append("")
                for i, sg in enumerate(result.subgraphs, 1):
                    sg_nodes = [n for n in result.nodes if n.subgraph == sg.id]
                    node_labels = [n.label for n in sg_nodes[:5]]
                    labels_str = " → ".join(node_labels) if node_labels else "(empty)"
                    body_lines.append(f"{i}. **{sg.label}**: {labels_str}")
            else:
                # Linear flow from entry to exit
                body_lines.append("Sequential process steps:")
                body_lines.append("")
                for i, n in enumerate(result.nodes[:20], 1):
                    body_lines.append(f"{i}. {n.label}")
            body_lines.append("")

            # Original Mermaid block
            body_lines.append("### Original Mermaid Source")
            body_lines.append("")
            body_lines.append("```mermaid")
            body_lines.append(result.raw_content.strip())
            body_lines.append("```")
            body_lines.append("")

        body = "\n".join(body_lines)

        # Write the chunk-ready parsed markdown
        output_path = parsed_mermaid_dir / "mermaid_parsed.md"
        output_path.write_text(frontmatter + "\n\n" + body, encoding="utf-8")

        logger.info(
            "Mermaid parsed → %s (%d nodes, %d edges, %d subgraphs)",
            output_path, total_nodes, total_edges, total_subgraphs,
        )

        self._mermaid_result = MermaidResult(
            parsed_path=str(output_path),
            intermediates_dir=str(intermediates_mermaid_dir),
            node_count=total_nodes,
            edge_count=total_edges,
            subgraph_count=total_subgraphs,
            linked_workbook=linked_workbook,
            linked_sheet=linked_sheet,
            linkage_confidence=linkage_confidence,
            source_files=source_files,
        )
        return self._mermaid_result

    def write_manifest(self) -> Path:
        """Write run-level manifest.json summarizing all workbooks and mermaid."""
        manifest = {
            "version": "2.0",
            "project_id": self.project_id,
            "created_at": datetime.now().isoformat(),
            "structure": "unified_v1",
            "output_structure_version": "2.1",
            "parsed_root": "parsed/",
            "evidence_root": "evidence/",
            "intermediates_root": "intermediates/",
            "supported_parsed_types": ["excel", "code", "csv", "pdf", "mermaid"],
            "paths": {
                "parsed": "parsed/",
                "parsed_excel": "parsed/excel/",
                "parsed_mermaid": "parsed/mermaid/",
                "evidence": "evidence/",
                "evidence_excel": "evidence/excel/",
                "evidence_mermaid": "evidence/mermaid/",
                "intermediates": "intermediates/",
                "intermediates_mermaid": "intermediates/mermaid/",
                "legacy_compat": "legacy_compat/",
            },
            "workbooks": [],
        }

        for wr in self._workbook_results:
            manifest["workbooks"].append({
                "name": wr.workbook_name,
                "sheets_parsed": wr.sheets_parsed,
                "pdf_count": wr.pdf_count,
                "image_count": wr.image_count,
                "parsed_md_count": wr.parsed_md_count,
                "evidence_files": wr.evidence_files,
                "legacy_symlinks": wr.legacy_symlinks_created,
            })

        if self._mermaid_result and self._mermaid_result.parsed_path:
            manifest["mermaid"] = {
                "parsed_path": "parsed/mermaid/mermaid_parsed.md",
                "intermediates_dir": "intermediates/mermaid/",
                "node_count": self._mermaid_result.node_count,
                "edge_count": self._mermaid_result.edge_count,
                "subgraph_count": self._mermaid_result.subgraph_count,
                "linked_workbook": self._mermaid_result.linked_workbook,
                "linked_sheet": self._mermaid_result.linked_sheet,
                "linkage_confidence": self._mermaid_result.linkage_confidence,
                "source_files": self._mermaid_result.source_files,
            }

        manifest_path = self.run_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Manifest written: %s", manifest_path)
        return manifest_path

    def cleanup_staging(self) -> None:
        """Remove the staging directory after successful reorganization."""
        if self._staging_base.exists():
            shutil.rmtree(str(self._staging_base))
            logger.debug("Staging cleaned up: %s", self._staging_base)
