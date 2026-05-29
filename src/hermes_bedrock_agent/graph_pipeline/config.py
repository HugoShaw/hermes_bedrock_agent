"""Configuration for the graph pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GraphPipelineConfig:
    # ── Identity ───────────────────────────────────────────────────────────────
    project_id: str = ""       # e.g. "sample_20260519" (normalized, ASCII)
    project_name: str = ""     # e.g. "サンプル20260519" (display, Japanese OK)

    # ── AWS / Bedrock ──────────────────────────────────────────────────────────
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "ap-northeast-1"))
    model_id: str = field(
        default_factory=lambda: os.getenv(
            "BEDROCK_EXTRACTION_MODEL_ID",
            os.getenv("BEDROCK_TEXT_MODEL_ID", "jp.anthropic.claude-sonnet-4-6"),
        )
    )

    # ── Neptune ────────────────────────────────────────────────────────────────
    neptune_graph_id: str = field(default_factory=lambda: os.getenv("NEPTUNE_GRAPH_ID", ""))

    # ── Extraction ─────────────────────────────────────────────────────────────
    llm_delay_seconds: float = 3.0
    max_tokens: int = 16000

    # ── Output ─────────────────────────────────────────────────────────────────
    output_dir: str = ""    # absolute path; set to {project_dir}/graph_output/ if empty

    # ── Execution flags ────────────────────────────────────────────────────────
    dry_run: bool = False       # generate Cypher but don't execute against Neptune
    skip_load: bool = False     # synonym for dry_run (skip loading step)

    def resolve_output_dir(self, project_dir: str | Path) -> Path:
        if self.output_dir:
            return Path(self.output_dir)
        return Path(project_dir) / "graph_output"
