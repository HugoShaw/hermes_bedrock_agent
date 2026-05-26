"""doc_pipeline — standardised S3-to-KB document processing pipeline."""

from .runners.full_pipeline import run_pipeline

__all__ = ["run_pipeline"]
