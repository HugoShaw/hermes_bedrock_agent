"""Full end-to-end pipeline runner: S3 source → KB ingestion."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import PipelineConfig, config as _default_config
from ..models import Chunk, IngestStats, ParseResult, WorkManifest

logger = logging.getLogger(__name__)


# ── Stage helpers ─────────────────────────────────────────────────────────────

def _run_parse_stages(
    xlsx_path: str,
    output_dir: str,
    cfg: PipelineConfig,
    ground_truth_map: Optional[dict[str, str]] = None,
) -> list[ParseResult]:
    """Stages 2-5: Excel → PDF → Image → VLM → Markdown post-processing."""
    from ..stages.excel_to_pdf import convert_excel_to_pdfs
    from ..stages.markdown_post import post_process_all
    from ..stages.pdf_to_image import render_all_sheets
    from ..stages.vlm_parse import parse_all_sheets

    pdf_dir = os.path.join(output_dir, "pdf")
    image_dir = os.path.join(output_dir, "images")
    parsed_dir = os.path.join(output_dir, "vlm_parsed")

    # Stage 2: Excel → PDF
    logger.info("=== Stage 2: Excel → PDF ===")
    sheet_pdfs = convert_excel_to_pdfs(xlsx_path, pdf_dir, cfg=cfg)

    # Stage 3: PDF → Image
    logger.info("=== Stage 3: PDF → Image ===")
    all_images = render_all_sheets(sheet_pdfs, image_dir, cfg=cfg)

    # Stage 4: VLM parse
    logger.info("=== Stage 4: VLM Parsing ===")
    parse_results = parse_all_sheets(all_images, parsed_dir, cfg=cfg, resume=True)

    # Stage 5: Markdown post-processing
    logger.info("=== Stage 5: Markdown Post-processing ===")
    parse_results = post_process_all(parse_results, ground_truth_map=ground_truth_map)

    return parse_results


def _run_ingest_stages(
    parse_results: list[ParseResult],
    workbook_name: str,
    source_excel_s3_path: str,
    output_dir: str,
    cfg: PipelineConfig,
    mode: str = "append",
    skip_graph: bool = False,
) -> IngestStats:
    """Stages 6-8: Chunking → Vector embedding → Neptune graph."""
    from ..stages.chunker import chunk_all_results
    from ..stages.graph_ingest import ingest_to_graph
    from ..stages.vector_embed import embed_chunks

    s3_pdf_prefix = f"s3://{cfg.s3_bucket}/outputs/{workbook_name}/pdf"
    s3_md_prefix = f"s3://{cfg.s3_bucket}/outputs/{workbook_name}/vlm_parsed"

    # Stage 6: Chunking
    logger.info("=== Stage 6: Chunking ===")
    chunks = chunk_all_results(
        parse_results,
        workbook_name=workbook_name,
        source_excel_s3_path=source_excel_s3_path,
        source_pdf_s3_prefix=s3_pdf_prefix,
        source_md_s3_prefix=s3_md_prefix,
        cfg=cfg,
    )
    logger.info("Total chunks: %d", len(chunks))

    # Save JSONL
    jsonl_path = os.path.join(output_dir, "chunks.jsonl")
    os.makedirs(output_dir, exist_ok=True)
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for ch in chunks:
            f.write(ch.model_dump_json() + "\n")
    logger.info("Chunks saved: %s", jsonl_path)

    # Stage 7: Vector embedding
    logger.info("=== Stage 7: Vector Embedding ===")
    lancedb_added = embed_chunks(chunks, cfg=cfg, mode=mode)

    # Stage 8: Neptune graph
    neptune_stats: dict = {"node_count": 0, "edge_count": 0, "error_count": 0}
    if not skip_graph:
        logger.info("=== Stage 8: Neptune Graph ===")
        try:
            neptune_stats = ingest_to_graph(chunks, cfg=cfg)
        except Exception as e:
            logger.warning("Neptune graph step failed (non-fatal): %s", e)

    return IngestStats(
        workbook_name=workbook_name,
        chunks_total=len(chunks),
        lancedb_added=lancedb_added,
        neptune_nodes=neptune_stats.get("node_count", 0),
        neptune_edges=neptune_stats.get("edge_count", 0),
        neptune_errors=neptune_stats.get("error_count", 0),
    )


# ── Public entry point ────────────────────────────────────────────────────────

def run_pipeline(
    xlsx_path: Optional[str] = None,
    s3_prefix: Optional[str] = None,
    output_dir: Optional[str] = None,
    parsed_dir: Optional[str] = None,
    stages: str = "all",
    mode: str = "append",
    ground_truth: Optional[str] = None,
    sheet_index: Optional[int] = None,
    skip_graph: bool = False,
    cfg: Optional[PipelineConfig] = None,
) -> dict:
    """Run the doc_pipeline.

    Args:
        xlsx_path:   Local path to an Excel file to process.
        s3_prefix:   S3 prefix to scan and download Excel files from.
        output_dir:  Base output directory for this run.
        parsed_dir:  Path to existing parsed markdown dir (for --stages ingest).
        stages:      Which stages to run: "all" | "parse" | "ingest" | "images" | "vlm".
        mode:        LanceDB write mode: "append" | "replace" | "rebuild".
        ground_truth: Path to a .mmd file to inject (used with sheet_index).
        sheet_index: Sheet index to apply ground_truth to (1-based).
        skip_graph:  Skip Neptune graph stage even if configured.
        cfg:         Pipeline config (uses global default if None).

    Returns:
        Summary dict with stats.
    """
    cfg = cfg or _default_config
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir or f"outputs/run_{ts}"
    os.makedirs(run_dir, exist_ok=True)

    summary: dict = {"run_dir": run_dir, "stages": stages, "timestamp": ts}

    # ── Resolve workbook list ──────────────────────────────────────────────
    workbook_paths: list[tuple[str, str]] = []  # (local_path, s3_excel_path)

    if xlsx_path:
        s3_excel_path = f"s3://{cfg.s3_bucket}/{Path(xlsx_path).name}"
        workbook_paths.append((xlsx_path, s3_excel_path))

    elif s3_prefix:
        from ..stages.s3_discovery import discover, download_excel_files

        logger.info("=== Stage 1: S3 Discovery ===")
        manifest = discover(s3_prefix, cfg=cfg)
        dl_dir = os.path.join(run_dir, "downloads")
        manifest = download_excel_files(manifest, dl_dir, cfg=cfg)

        for sf in manifest.excel_files:
            if sf.local_path:
                s3_key = sf.key
                workbook_paths.append((sf.local_path, f"s3://{cfg.s3_bucket}/{s3_key}"))

    elif parsed_dir and stages in ("ingest",):
        # Ingest from pre-existing parsed markdown only
        workbook_name = Path(parsed_dir).name
        parse_results = _load_parsed_results(parsed_dir)
        stats = _run_ingest_stages(
            parse_results,
            workbook_name=workbook_name,
            source_excel_s3_path="",
            output_dir=os.path.join(run_dir, workbook_name),
            cfg=cfg,
            mode=mode,
            skip_graph=skip_graph,
        )
        summary["ingest"] = stats.model_dump()
        _save_summary(run_dir, summary)
        return summary
    else:
        raise ValueError("Provide --file, --s3-prefix, or --parsed-dir with --stages ingest")

    # ── Process each workbook ──────────────────────────────────────────────
    all_stats: list[dict] = []

    for local_xlsx, s3_excel_path in workbook_paths:
        workbook_name = Path(local_xlsx).stem
        wb_dir = os.path.join(run_dir, workbook_name)
        os.makedirs(wb_dir, exist_ok=True)

        logger.info("\n" + "=" * 60)
        logger.info("Processing: %s", workbook_name)
        logger.info("=" * 60)

        parse_results: list[ParseResult] = []

        # Ground-truth map (sheet name → .mmd path)
        gt_map: dict[str, str] = {}
        if ground_truth and sheet_index:
            # We don't know the sheet name yet; will apply after parsing
            pass

        if stages in ("all", "parse", "images", "vlm"):
            parse_results = _run_parse_stages(local_xlsx, wb_dir, cfg, ground_truth_map=gt_map)

            # Late ground-truth injection (we know sheet names now)
            if ground_truth and sheet_index and parse_results:
                from ..stages.markdown_post import post_process

                for i, r in enumerate(parse_results):
                    if r.sheet_info.index == sheet_index:
                        parse_results[i] = post_process(r, ground_truth_mmd=ground_truth)
                        logger.info("Applied ground-truth to sheet %d", sheet_index)
                        break

        if stages in ("all", "ingest") and (parse_results or stages == "ingest"):
            if not parse_results and stages == "ingest":
                parse_results = _load_parsed_results(os.path.join(wb_dir, "vlm_parsed"))

            ingest_dir = os.path.join(wb_dir, "dual_rag")
            stats = _run_ingest_stages(
                parse_results,
                workbook_name=workbook_name,
                source_excel_s3_path=s3_excel_path,
                output_dir=ingest_dir,
                cfg=cfg,
                mode=mode,
                skip_graph=skip_graph,
            )
            all_stats.append(stats.model_dump())
            logger.info(
                "Done: %d chunks, %d LanceDB rows, %d+%d Neptune nodes/edges",
                stats.chunks_total, stats.lancedb_added,
                stats.neptune_nodes, stats.neptune_edges,
            )

    summary["workbooks"] = all_stats
    _save_summary(run_dir, summary)
    return summary


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_parsed_results(parsed_dir: str) -> list[ParseResult]:
    """Reconstruct ParseResult list from a vlm_parsed directory."""
    from ..models import SheetInfo

    results: list[ParseResult] = []
    parsed_path = Path(parsed_dir)

    for md_file in sorted(parsed_path.glob("sheet_*.md")):
        stem = md_file.stem  # e.g. sheet_01
        try:
            idx = int(stem.split("_")[1])
        except (IndexError, ValueError):
            continue

        meta_file = parsed_path / f"{stem}_meta.json"
        sheet_name = stem
        if meta_file.exists():
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)
            sheet_name = meta.get("sheet_name", stem)

        markdown = md_file.read_text(encoding="utf-8")
        results.append(
            ParseResult(
                sheet_info=SheetInfo(index=idx, name=sheet_name, rows=0, cols=0),
                markdown=markdown,
            )
        )

    logger.info("Loaded %d parsed sheets from %s", len(results), parsed_dir)
    return results


def _save_summary(run_dir: str, summary: dict) -> None:
    path = os.path.join(run_dir, "run_summary.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info("Run summary: %s", path)
