"""
Pipeline: Export Excel Parsed Content as Markdown (X7).

Orchestrates the ExcelMarkdownExporter and ExcelMarkdownReporter.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def run_markdown_export_pipeline(
    config: dict[str, Any],
    run_id: str,
    dataset: str,
    input_dir: str,
    output_dir: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full X7 markdown export pipeline.

    Args:
        config: Project config dict.
        run_id: Run ID.
        dataset: Dataset name.
        input_dir: Input directory with parsed JSONL files.
        output_dir: Output directory for markdown files.
        options: Export options dict.

    Returns:
        Pipeline result dict.
    """
    from hermes_bedrock_agent.v2.excel.excel_markdown_exporter import ExcelMarkdownExporter
    from hermes_bedrock_agent.v2.excel.excel_markdown_reporter import ExcelMarkdownReporter

    exporter = ExcelMarkdownExporter(
        input_dir=input_dir,
        output_dir=output_dir,
        run_id=run_id,
        dataset=dataset,
        config=config,
        options=options or {},
    )

    result = exporter.export_all()

    # Generate report
    reporter = ExcelMarkdownReporter(
        stats=result["stats"],
        generated_files=result["generated_files"],
        output_dir=output_dir,
        run_id=run_id,
        dataset=dataset,
    )
    reporter.generate_report()

    # Add report to files list
    report_path = str(Path(output_dir) / "markdown_export_report.md")
    if report_path not in result["generated_files"]:
        result["generated_files"].append(report_path)

    return result
