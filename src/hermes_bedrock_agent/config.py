"""Unified configuration — loaded from .env at project root."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=False)


@dataclass
class Config:
    # ── AWS ────────────────────────────────────────────────────────────────────
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "ap-northeast-1"))
    s3_bucket: str = field(default_factory=lambda: os.getenv("S3_BUCKET", "s3-hulftchina-rd"))

    # ── Bedrock models ─────────────────────────────────────────────────────────
    vlm_model_id: str = field(
        default_factory=lambda: os.getenv("BEDROCK_VLM_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")
    )
    embed_model_id: str = field(
        default_factory=lambda: os.getenv("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
    )
    embed_dimensions: int = 1024

    # ── LanceDB ────────────────────────────────────────────────────────────────
    lancedb_path: str = field(
        default_factory=lambda: os.getenv(
            "VECTOR_LOCAL_STORE_PATH",
            "/home/ubuntu/projects/data/vector_store/lancedb",
        )
    )
    vector_collection: str = "murata_excel_vlm_dual_rag"

    # ── Neptune ────────────────────────────────────────────────────────────────
    neptune_graph_id: str = field(
        default_factory=lambda: os.getenv("NEPTUNE_GRAPH_ID", "")
    )

    # ── VLM parsing ────────────────────────────────────────────────────────────
    vlm_tile_size: int = 3000
    vlm_tile_overlap: int = 300
    vlm_max_image_px: int = 3000
    vlm_delay_seconds: float = 3.0

    # ── PDF rendering ──────────────────────────────────────────────────────────
    pdf_default_dpi: int = 150
    pdf_wide_threshold_mm: float = 1000.0

    # ── Chunking ───────────────────────────────────────────────────────────────
    chunk_max_chars: int = 2000
    chunk_min_chars: int = 100
    embed_batch_size: int = 10

    # ── LibreOffice ────────────────────────────────────────────────────────────
    libreoffice_port: int = 2002
    libreoffice_host: str = "localhost"

    # ── I/O paths (set per run) ────────────────────────────────────────────────
    output_base: str = ""

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT


config = Config()
