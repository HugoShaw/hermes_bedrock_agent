"""Ingestion layer — S3/local scan, document registration, file routing, pipeline."""

from hermes_bedrock_agent.ingestion.document_registry import (
    build_document_id,
    calculate_content_hash,
    detect_new_or_changed,
    infer_source_type,
    register_documents,
)
from hermes_bedrock_agent.ingestion.file_router import FileRouter
from hermes_bedrock_agent.ingestion.pipeline import (
    IngestionPipeline,
    PipelineConfig,
    PipelineResult,
)

__all__ = [
    "build_document_id",
    "calculate_content_hash",
    "detect_new_or_changed",
    "infer_source_type",
    "register_documents",
    "FileRouter",
    "IngestionPipeline",
    "PipelineConfig",
    "PipelineResult",
]
