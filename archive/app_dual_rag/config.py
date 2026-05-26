"""Configuration for the dual-RAG pipeline, loaded from .env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load from project root .env
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env", override=False)


class DualRAGConfig:
    aws_region: str = os.getenv("AWS_REGION", "ap-northeast-1")
    bedrock_embedding_model_id: str = os.getenv(
        "BEDROCK_EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"
    )
    vector_local_store_path: str = os.getenv(
        "VECTOR_LOCAL_STORE_PATH", "/home/ubuntu/projects/data/vector_store/lancedb"
    )
    vector_collection: str = "murata_excel_vlm_dual_rag"
    neptune_graph_id: str = os.getenv("NEPTUNE_GRAPH_ID", "")
    s3_bucket: str = os.getenv("S3_BUCKET", "s3-hulftchina-rd")

    # Input paths (relative to project root)
    project_root: Path = _PROJECT_ROOT
    vlm_parsed_dir: Path = _PROJECT_ROOT / "outputs/reparse_wb2/vlm_parsed"
    pdf_dir: Path = _PROJECT_ROOT / "outputs/reparse_wb2/pdf"
    sheet_name_mapping_csv: Path = _PROJECT_ROOT / "outputs/reparse_wb2/sheet_name_mapping.csv"
    output_dir: Path = _PROJECT_ROOT / "outputs/reparse_wb2/dual_rag"
    chunks_jsonl: Path = _PROJECT_ROOT / "outputs/reparse_wb2/dual_rag/chunks.jsonl"

    # S3 prefixes for evidence tracing
    s3_pdf_prefix: str = "outputs/reparse_wb2/pdf"
    s3_vlm_prefix: str = "outputs/reparse_wb2/vlm_parsed"
    s3_excel_key: str = "サンプル20260519/02_詳細設計/MW_IFマッピング定義書_205_発注情報(登録・変更・取消).xlsx"

    workbook_name: str = "MW_IFマッピング定義書_205_発注情報(登録・変更・取消)"

    # Chunking limits
    max_chunk_size: int = 2000
    min_chunk_size: int = 100

    def s3_pdf_path(self, sheet_nn: str) -> str:
        return f"s3://{self.s3_bucket}/{self.s3_pdf_prefix}/sheet_{sheet_nn}.pdf"

    def s3_markdown_path(self, sheet_nn: str) -> str:
        return f"s3://{self.s3_bucket}/{self.s3_vlm_prefix}/sheet_{sheet_nn}.md"

    def s3_excel_path(self) -> str:
        return f"s3://{self.s3_bucket}/{self.s3_excel_key}"


config = DualRAGConfig()
