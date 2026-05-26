#!/usr/bin/env python3
"""Batch convert multiple Excel files to Markdown+Mermaid.

Usage:
    python scripts/batch_convert_excel_to_markdown.py \
        --manifest data/input/excel_batch_manifest.yaml \
        --output-root data/outputs/excel_markdown
"""
import sys
import json
import yaml
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Batch Excel to Markdown conversion")
    parser.add_argument("--manifest", type=str, required=True, help="Path to batch manifest YAML")
    parser.add_argument("--output-root", type=str, required=True, help="Root output directory")
    args = parser.parse_args()
    
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        return 1
    
    with open(manifest_path, 'r', encoding='utf-8') as f:
        manifest = yaml.safe_load(f) or {}
    
    jobs = manifest.get("jobs", [])
    if not jobs:
        logger.error("No jobs in manifest")
        return 1
    
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    
    results = []
    
    for i, job in enumerate(jobs):
        document_id = job.get("document_id", f"doc_{i:03d}")
        title = job.get("title", document_id)
        input_uri = job.get("input_uri", "")
        config = job.get("config", "")
        skeleton = job.get("skeleton", "")
        override = job.get("overrides", "") or job.get("override", "")
        reference_md = job.get("reference_markdown", "")
        
        logger.info(f"{'='*60}")
        logger.info(f"Job {i+1}/{len(jobs)}: {document_id}")
        logger.info(f"{'='*60}")
        
        # Build command
        cmd = [
            sys.executable,
            str(project_root / "scripts" / "convert_excel_to_markdown.py"),
            "--document-id", document_id,
            "--title", title,
            "--output-root", str(output_root),
        ]
        
        # Determine if input is local file or S3 URI
        if input_uri.startswith("s3://"):
            cmd.extend(["--input-uri", input_uri])
        else:
            cmd.extend(["--local-file", input_uri])
        
        render_visuals = job.get("render_visuals", True)
        cmd.extend(["--render-visuals", str(render_visuals).lower()])
        
        if config:
            cmd.extend(["--config", config])
        if skeleton:
            cmd.extend(["--skeleton", skeleton])
        if override:
            cmd.extend(["--override", override])
        if reference_md:
            cmd.extend(["--reference-md", reference_md])
        
        # Run conversion
        start_time = datetime.now(timezone.utc)
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(project_root),
            )
            
            status = "OK" if proc.returncode == 0 else "ERROR"
            error = ""
            if proc.returncode != 0:
                error = (proc.stderr or proc.stdout)[-500:]
                logger.error(f"Job {document_id} failed: {error[:200]}")
            else:
                logger.info(f"Job {document_id}: OK")
            
        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
            error = "Timed out after 600s"
            logger.error(f"Job {document_id}: TIMEOUT")
        except Exception as e:
            status = "ERROR"
            error = str(e)
            logger.error(f"Job {document_id}: {e}")
        
        end_time = datetime.now(timezone.utc)
        
        # Gather output stats
        doc_dir = output_root / document_id
        stats = _gather_stats(doc_dir)
        
        results.append({
            "document_id": document_id,
            "title": title,
            "status": status,
            "error": error[:200] if error else "",
            "duration_seconds": (end_time - start_time).total_seconds(),
            **stats,
        })
    
    # Write batch summary
    _write_batch_summary_md(results, output_root / "batch_summary.md")
    _write_batch_summary_json(results, output_root / "batch_summary.json")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"BATCH CONVERSION COMPLETE")
    print(f"{'='*60}")
    ok_count = sum(1 for r in results if r["status"] == "OK")
    print(f"Results: {ok_count}/{len(results)} OK")
    for r in results:
        status_icon = "✅" if r["status"] == "OK" else "❌"
        print(f"  {status_icon} {r['document_id']}: {r['status']}")
    print(f"\nBatch summary: {output_root / 'batch_summary.md'}")
    print(f"{'='*60}\n")
    
    return 0 if ok_count == len(results) else 1


def _gather_stats(doc_dir: Path) -> dict:
    """Gather statistics from output directory."""
    stats = {
        "has_full_md": False,
        "has_rag_md": False,
        "has_business_mermaid": False,
        "mermaid_count": 0,
        "warnings": 0,
    }
    
    if not doc_dir.exists():
        return stats
    
    md_dir = doc_dir / "markdown"
    if md_dir.exists():
        stats["has_full_md"] = any(md_dir.glob("*.full.md"))
        stats["has_rag_md"] = any(md_dir.glob("*.rag.md"))
    
    br_dir = doc_dir / "mermaid" / "business_readable"
    if br_dir.exists():
        stats["has_business_mermaid"] = any(br_dir.glob("*.mmd"))
    
    mermaid_dir = doc_dir / "mermaid"
    if mermaid_dir.exists():
        stats["mermaid_count"] = len(list(mermaid_dir.rglob("*.mmd")))
    
    return stats


def _write_batch_summary_md(results: list, path: Path):
    """Write batch summary markdown."""
    lines = ["# Excel Batch Conversion Summary", ""]
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Total jobs: {len(results)}")
    lines.append("")
    
    lines.append("| Document ID | Status | Duration | Mermaid | RAG MD | Warnings |")
    lines.append("|---|:---:|---:|---:|:---:|---:|")
    
    for r in results:
        status = "✅" if r["status"] == "OK" else "❌"
        rag = "✓" if r.get("has_rag_md") else "✗"
        lines.append(
            f"| {r['document_id']} | {status} {r['status']} | "
            f"{r['duration_seconds']:.1f}s | {r.get('mermaid_count',0)} | "
            f"{rag} | {r.get('warnings',0)} |"
        )
    
    lines.append("")
    ok = sum(1 for r in results if r["status"] == "OK")
    lines.append(f"\n**Result**: {ok}/{len(results)} successful")
    
    # Errors
    errors = [r for r in results if r["status"] != "OK"]
    if errors:
        lines.append("\n## Errors\n")
        for r in errors:
            lines.append(f"### {r['document_id']}")
            lines.append(f"Status: {r['status']}")
            lines.append(f"Error: {r.get('error', 'unknown')}")
            lines.append("")
    
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_batch_summary_json(results: list, path: Path):
    """Write batch summary JSON."""
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "ok": sum(1 for r in results if r["status"] == "OK"),
        "failed": sum(1 for r in results if r["status"] != "OK"),
        "jobs": results,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    sys.exit(main() or 0)
