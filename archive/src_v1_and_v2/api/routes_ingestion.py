"""Ingestion API routes — lightweight status and dry-run endpoints.

Phase 8 only implements lightweight interfaces.
Full ingestion job queue is deferred to Phase 9+.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from hermes_bedrock_agent.configs.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


class IngestionStatus(BaseModel):
    """Current ingestion pipeline status."""

    status: str = Field(default="idle", description="idle, running, completed, error")
    documents_registered: int = Field(default=0)
    documents_pending: int = Field(default=0)
    last_run: Optional[str] = Field(default=None)
    message: str = Field(default="")


class DryRunRequest(BaseModel):
    """Dry-run ingestion request."""

    s3_prefix: str = Field(default="", description="S3 prefix to scan")
    file_types: list[str] = Field(
        default_factory=lambda: ["pdf", "md", "txt", "py", "sql"],
        description="File extensions to include",
    )
    max_files: int = Field(default=100, ge=1, le=1000, description="Max files to scan")


class DryRunResult(BaseModel):
    """Dry-run result — what WOULD be ingested without executing."""

    success: bool = True
    files_found: int = 0
    files_new: int = 0
    files_updated: int = 0
    files_unchanged: int = 0
    sample_files: list[str] = Field(default_factory=list)
    message: str = ""


@router.get("/status", response_model=IngestionStatus)
async def get_ingestion_status() -> IngestionStatus:
    """Get current ingestion pipeline status.

    Returns basic status info. Full job tracking deferred to Phase 9.
    """
    return IngestionStatus(
        status="idle",
        documents_registered=0,
        documents_pending=0,
        last_run=None,
        message="Ingestion pipeline ready. Full job queue available in Phase 9.",
    )


@router.post("/dry-run", response_model=DryRunResult)
async def dry_run_ingestion(request: DryRunRequest) -> DryRunResult:
    """Dry-run: scan S3 and report what would be ingested.

    Does NOT actually ingest. Reports file counts and samples.
    """
    try:
        # In Phase 8, return a placeholder response
        # Full S3 scanning deferred to Phase 9 integration
        return DryRunResult(
            success=True,
            files_found=0,
            files_new=0,
            files_updated=0,
            files_unchanged=0,
            sample_files=[],
            message=(
                f"Dry-run scan target: s3://.../{request.s3_prefix} "
                f"(types: {request.file_types}, max: {request.max_files}). "
                f"Full S3 integration available in Phase 9."
            ),
        )
    except Exception as e:
        logger.error(f"Dry-run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
