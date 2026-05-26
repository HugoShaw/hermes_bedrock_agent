"""Pipeline configuration - loads from .env and provides defaults."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


@dataclass
class PipelineConfig:
    """Configuration for the Excel Parse Pipeline."""

    # AWS / S3
    aws_region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "ap-northeast-1"))
    s3_bucket: str = field(default_factory=lambda: os.getenv("S3_BUCKET", "s3-hulftchina-rd"))
    s3_input_prefix: str = field(default_factory=lambda: os.getenv("S3_RAW_PREFIX", "サンプル20260519/"))
    s3_output_prefix: str = "output/sample_20260519/excel_parse_pipeline"

    # Bedrock LLM
    bedrock_text_model: str = field(
        default_factory=lambda: os.getenv("BEDROCK_TEXT_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")
    )
    bedrock_vlm_model: str = field(
        default_factory=lambda: os.getenv("BEDROCK_VLM_MODEL_ID", "jp.anthropic.claude-sonnet-4-6")
    )

    # Local paths
    output_dir: Path = field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "outputs" / "excel_parse_pipeline" / "sample_20260519"
    )
    downloads_dir: Path = field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "outputs" / "excel_parse_pipeline" / "sample_20260519" / "downloads"
    )

    # Pipeline settings
    max_tokens: int = 12000
    temperature: float = 0.0
    read_timeout: int = 600
    use_vlm: bool = True
    dry_run: bool = False

    # Neptune (for future graph import)
    neptune_graph_id: str = field(default_factory=lambda: os.getenv("NEPTUNE_GRAPH_ID", ""))

    def ensure_dirs(self):
        """Create all output directories."""
        subdirs = [
            "downloads",
            "atlas",
            "parse_plans",
            "structured",
            "graph",
            "kb_chunks",
            "review",
            "images",
        ]
        for sub in subdirs:
            (self.output_dir / sub).mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
