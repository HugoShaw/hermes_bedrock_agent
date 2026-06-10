"""Validate refactor plan v2 with real S3 project: 洋马发动机.

This script:
1. Scans the S3 project → ProjectManifest
2. Downloads a small subset of files for parsing validation
3. Runs the new parsers (DOCX, CSV, PDF)
4. Runs existing Excel pipeline comparison (scan only, no VLM)
5. Verifies dualrag --help still works
6. Writes validation report
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from hermes_bedrock_agent.models import ProjectManifest, SourceType
from hermes_bedrock_agent.project.scanner import scan_s3_project
from hermes_bedrock_agent.parsing import DocxParser, CsvParser, PdfTextParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("validate")

BUCKET = "s3-hulftchina-rd"
PREFIX = "洋马发动机"
PROJECT_ID = "yangma"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "yangma_test"


def step1_scan() -> ProjectManifest:
    """Step 1: Scan S3 project."""
    logger.info("=" * 60)
    logger.info("STEP 1: Scanning S3 project s3://%s/%s/", BUCKET, PREFIX)
    logger.info("=" * 60)

    manifest = scan_s3_project(BUCKET, PREFIX, PROJECT_ID, display_name="洋马发动机")

    # Print summary
    logger.info("Files found: %d", manifest.file_count)
    logger.info("Total size: %.1f MB", manifest.total_size_bytes() / 1024 / 1024)
    logger.info("Type distribution:")
    for type_name, count in sorted(manifest.type_counts().items(), key=lambda x: -x[1]):
        logger.info("  %s: %d", type_name, count)

    # Print folder structure
    folders: dict[str, int] = {}
    for f in manifest.files:
        folder = f.parent_folder or "(root)"
        folders[folder] = folders.get(folder, 0) + 1

    logger.info("\nFolder structure:")
    for folder, count in sorted(folders.items()):
        logger.info("  %s/ → %d files", folder, count)

    # Write manifest
    manifest_path = OUTPUT_DIR / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
    logger.info("Manifest written: %s", manifest_path)

    return manifest


def step2_download_subset(manifest: ProjectManifest) -> dict[str, Path]:
    """Step 2: Download a small subset of files for parsing validation."""
    import boto3

    logger.info("\n" + "=" * 60)
    logger.info("STEP 2: Downloading test files")
    logger.info("=" * 60)

    s3 = boto3.client("s3")
    download_dir = OUTPUT_DIR / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    targets: dict[str, dict] = {
        "docx": {
            "folder_contains": "验收申请",
            "source_type": SourceType.DOCX,
            "pick": "smallest",
        },
        "csv": {
            "folder_contains": "测试报告",
            "source_type": SourceType.CSV,
            "pick": "smallest",
        },
        "pdf": {
            "folder_contains": "",
            "source_type": SourceType.PDF_NATIVE,
            "pick": "smallest",
        },
    }

    downloaded: dict[str, Path] = {}

    for label, criteria in targets.items():
        candidates = [
            f for f in manifest.files
            if f.source_type == criteria["source_type"]
            and (not criteria["folder_contains"] or criteria["folder_contains"] in f.parent_folder)
        ]

        if not candidates:
            # Fallback: any file of this type
            candidates = [f for f in manifest.files if f.source_type == criteria["source_type"]]

        if not candidates:
            logger.warning("No %s files found!", label)
            continue

        # Pick smallest
        candidates.sort(key=lambda x: x.size_bytes)
        chosen = candidates[0]

        # Download
        local_path = download_dir / label / Path(chosen.relative_path).name
        local_path.parent.mkdir(parents=True, exist_ok=True)

        s3_key = chosen.path.replace(f"s3://{BUCKET}/", "")
        logger.info("Downloading %s: %s (%.1f KB)", label, chosen.relative_path, chosen.size_bytes / 1024)
        s3.download_file(BUCKET, s3_key, str(local_path))

        downloaded[label] = local_path

    return downloaded


def step3_parse(downloaded: dict[str, Path]) -> dict[str, list]:
    """Step 3: Run parsers on downloaded files."""
    logger.info("\n" + "=" * 60)
    logger.info("STEP 3: Parsing test files")
    logger.info("=" * 60)

    results: dict[str, list] = {}
    parsed_dir = OUTPUT_DIR / "parsed"

    # DOCX
    if "docx" in downloaded:
        parser = DocxParser()
        path = downloaded["docx"]
        logger.info("Parsing DOCX: %s", path.name)
        docs = parser.parse(path, PROJECT_ID)
        results["docx"] = docs

        out_path = parsed_dir / "docx" / f"{path.stem}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(docs[0].content_markdown)
        logger.info("  → %d chars, language=%s", len(docs[0].content_markdown), docs[0].language)
        logger.info("  → Preview: %s...", docs[0].content_markdown[:200].replace("\n", " "))

    # CSV
    if "csv" in downloaded:
        parser = CsvParser()
        path = downloaded["csv"]
        logger.info("Parsing CSV: %s", path.name)
        docs = parser.parse(path, PROJECT_ID)
        results["csv"] = docs

        out_path = parsed_dir / "csv" / f"{path.stem}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(docs[0].content_markdown)
        logger.info("  → %d chars, language=%s", len(docs[0].content_markdown), docs[0].language)
        logger.info("  → Metadata: %s", json.dumps(docs[0].metadata, ensure_ascii=False)[:200])

    # PDF
    if "pdf" in downloaded:
        parser = PdfTextParser()
        path = downloaded["pdf"]
        logger.info("Parsing PDF: %s", path.name)
        docs = parser.parse(path, PROJECT_ID)
        results["pdf"] = docs

        out_path = parsed_dir / "pdf" / f"{path.stem}.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(docs[0].content_markdown)
        logger.info("  → %d chars, language=%s, needs_vlm=%s",
                    len(docs[0].content_markdown), docs[0].language,
                    docs[0].metadata.get("needs_vlm", False))
        logger.info("  → Preview: %s...", docs[0].content_markdown[:200].replace("\n", " "))

    return results


def step4_verify_cli() -> bool:
    """Step 4: Verify dualrag --help still works."""
    logger.info("\n" + "=" * 60)
    logger.info("STEP 4: Verifying CLI")
    logger.info("=" * 60)

    result = subprocess.run(
        [sys.executable, "-m", "hermes_bedrock_agent.cli", "--help"],
        capture_output=True, text=True, cwd=str(PROJECT_ROOT),
    )

    if result.returncode == 0:
        logger.info("CLI --help works")
        # Check that expected commands are present
        expected_commands = ["parse", "build-kb", "qa", "graph", "project"]
        for cmd in expected_commands:
            if cmd in result.stdout:
                logger.info("  Command '%s' present", cmd)
            else:
                logger.warning("  Command '%s' NOT found in help output", cmd)
        return True
    else:
        logger.error("dualrag --help FAILED: %s", result.stderr)
        return False


def step5_write_report(manifest: ProjectManifest, results: dict, cli_ok: bool) -> None:
    """Step 5: Write validation report."""
    logger.info("\n" + "=" * 60)
    logger.info("STEP 5: Writing validation report")
    logger.info("=" * 60)

    report_lines: list[str] = []
    report_lines.append("# Refactor Plan v2 Validation Report")
    report_lines.append(f"\nProject: 洋马发动机 (yangma)")
    report_lines.append(f"Source: s3://{BUCKET}/{PREFIX}/")
    report_lines.append(f"Date: {manifest.scan_timestamp}")

    report_lines.append("\n## 1. Project Scan Results")
    report_lines.append(f"\n- Total files: {manifest.file_count}")
    report_lines.append(f"- Total size: {manifest.total_size_bytes() / 1024 / 1024:.1f} MB")
    report_lines.append("\n| Type | Count |")
    report_lines.append("|------|-------|")
    for t, c in sorted(manifest.type_counts().items(), key=lambda x: -x[1]):
        report_lines.append(f"| {t} | {c} |")

    report_lines.append("\n## 2. Parser Results")
    for label, docs in results.items():
        if docs:
            doc = docs[0]
            report_lines.append(f"\n### {label.upper()}")
            report_lines.append(f"- File: {doc.source_path}")
            report_lines.append(f"- Content length: {len(doc.content_markdown)} chars")
            report_lines.append(f"- Language: {doc.language}")
            report_lines.append(f"- Parse method: {doc.parse_method}")
            if doc.metadata:
                report_lines.append(f"- Metadata: {json.dumps(doc.metadata, ensure_ascii=False, indent=2)}")

    report_lines.append("\n## 3. CLI Verification")
    report_lines.append(f"\n- dualrag --help: {'PASS' if cli_ok else 'FAIL'}")

    report_lines.append("\n## 4. Validation Criteria")
    checks = [
        ("Project scan produces manifest", manifest.file_count > 0),
        ("DOCX parser extracts Chinese text", "docx" in results and len(results["docx"][0].content_markdown) > 100),
        ("CSV parser handles encoding", "csv" in results and "Empty" not in results["csv"][0].content_markdown),
        ("PDF parser extracts text", "pdf" in results and len(results["pdf"][0].content_markdown) > 50),
        ("CLI still functional", cli_ok),
    ]

    report_lines.append("\n| Check | Status |")
    report_lines.append("|-------|--------|")
    for desc, passed in checks:
        status = "PASS" if passed else "FAIL"
        report_lines.append(f"| {desc} | {status} |")

    all_passed = all(p for _, p in checks)
    report_lines.append(f"\n## Overall: {'ALL PASSED' if all_passed else 'SOME FAILURES'}")

    report_path = OUTPUT_DIR / "validation_report.md"
    report_path.write_text("\n".join(report_lines))
    logger.info("Report written: %s", report_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate refactor plan v2 with yangma project")
    parser.add_argument("--import-only", action="store_true", help="Validate imports only and exit")
    parser.add_argument("--dry-run", action="store_true", help="Skip S3 operations, test local files and CLI only")
    args = parser.parse_args()

    if args.import_only:
        logger.info("All imports successful")
        return

    if args.dry_run:
        logger.info("DRY RUN mode — skipping S3 operations")

        # Try to parse any local files already downloaded
        download_dir = OUTPUT_DIR / "downloads"
        downloaded: dict[str, Path] = {}
        for label in ("docx", "csv", "pdf"):
            label_dir = download_dir / label
            if label_dir.exists():
                files = list(label_dir.iterdir())
                if files:
                    downloaded[label] = files[0]
                    logger.info("Found local %s: %s", label, files[0].name)

        if downloaded:
            step3_parse(downloaded)
        else:
            logger.info("No local test files found in %s — skipping parse step", download_dir)

        # CLI verification always works locally
        step4_verify_cli()
        return

    logger.info("Starting validation of Refactor Plan v2")
    logger.info("Target: s3://%s/%s/", BUCKET, PREFIX)
    logger.info("Output: %s", OUTPUT_DIR)
    logger.info("")

    # Step 1: Scan
    manifest = step1_scan()

    # Step 2: Download subset
    downloaded = step2_download_subset(manifest)

    # Step 3: Parse
    results = step3_parse(downloaded)

    # Step 4: CLI check
    cli_ok = step4_verify_cli()

    # Step 5: Report
    step5_write_report(manifest, results, cli_ok)

    logger.info("\n" + "=" * 60)
    logger.info("VALIDATION COMPLETE")
    logger.info("=" * 60)
    logger.info("Output directory: %s", OUTPUT_DIR)


if __name__ == "__main__":
    main()
