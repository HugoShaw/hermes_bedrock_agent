"""Ingestion pipeline — orchestrates S3 scan → register → route → parse.

Supports:
- S3 mode: scan a bucket/prefix, download, parse
- Local mode: read files from a local directory
- Dry-run mode: scan and register without parsing
- Mock mode: use pre-built test inputs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.ingestion.document_registry import (
    detect_new_or_changed,
    register_documents,
)
from hermes_bedrock_agent.ingestion.file_router import FileRouter
from hermes_bedrock_agent.parsers.base import ParserContext, ParserOutput
from hermes_bedrock_agent.schemas.document import NormalizedDocument, SourceDocument
from hermes_bedrock_agent.schemas.visual import VisualBlock

logger = get_logger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for an ingestion pipeline run."""

    # Source settings
    s3_bucket: str = ""
    s3_prefix: str = ""
    local_dir: Optional[str] = None

    # Processing settings
    enable_vlm: bool = False
    dry_run: bool = False
    incremental: bool = True
    max_files: Optional[int] = None

    # File filter
    allowed_extensions: Optional[set[str]] = None

    # VLM settings
    vlm_model_id: str = "anthropic.claude-sonnet-4-20250514-v1:0"


@dataclass
class PipelineResult:
    """Result of a pipeline run."""

    scanned_count: int = 0
    registered_count: int = 0
    new_count: int = 0
    changed_count: int = 0
    parsed_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    documents: list[SourceDocument] = field(default_factory=list)
    normalized: list[NormalizedDocument] = field(default_factory=list)
    visual_blocks: list[VisualBlock] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


class IngestionPipeline:
    """Orchestrates the full ingestion flow.

    Steps:
    1. Scan source (S3 or local)
    2. Register documents (assign IDs, compute hashes)
    3. Detect new/changed (incremental mode)
    4. Route to parsers
    5. Parse documents
    6. Optionally run VLM second-pass
    7. Merge results

    Does NOT perform: chunking, embedding, graph extraction, or loading.
    """

    def __init__(
        self,
        config: PipelineConfig,
        s3_client: Optional[Any] = None,
        bedrock_client: Optional[Any] = None,
        previous_registry: Optional[list[SourceDocument]] = None,
    ) -> None:
        """Initialize the pipeline.

        Args:
            config: Pipeline configuration.
            s3_client: Optional S3Client instance (from clients/s3_client.py).
            bedrock_client: Optional BedrockRuntimeClient for VLM parsing.
            previous_registry: Previous document registry for incremental mode.
        """
        self._config = config
        self._s3_client = s3_client
        self._bedrock_client = bedrock_client
        self._previous_registry = previous_registry or []
        self._router = FileRouter(enable_vlm=config.enable_vlm)

    def run(self) -> PipelineResult:
        """Execute the full ingestion pipeline.

        Returns:
            PipelineResult with all outputs and metrics.
        """
        result = PipelineResult()

        # Step 1: Scan
        file_records = self._scan_source()
        result.scanned_count = len(file_records)
        logger.info("Scanned %d files", result.scanned_count)

        if not file_records:
            return result

        # Step 2: Register
        documents = register_documents(file_records)
        result.registered_count = len(documents)
        result.documents = documents

        # Step 3: Incremental detection
        if self._config.incremental and self._previous_registry:
            new_docs, changed_docs = detect_new_or_changed(
                documents, self._previous_registry
            )
            to_process = new_docs + changed_docs
            result.new_count = len(new_docs)
            result.changed_count = len(changed_docs)
            result.skipped_count = len(documents) - len(to_process)
        else:
            to_process = documents
            result.new_count = len(documents)

        # Dry-run: stop here
        if self._config.dry_run:
            logger.info("Dry run complete: %d documents registered", result.registered_count)
            return result

        # Step 4: Route and parse
        for doc in to_process:
            try:
                parser = self._router.get_parser(doc)
                content_bytes = self._fetch_content(doc)
                if content_bytes is None:
                    result.skipped_count += 1
                    continue

                ctx = ParserContext(
                    document=doc,
                    content_bytes=content_bytes,
                    enable_vlm=self._config.enable_vlm,
                    bedrock_client=self._bedrock_client,
                    vlm_model_id=self._config.vlm_model_id,
                )
                output = parser.parse(ctx)
                result.normalized.append(output.normalized_document)
                result.visual_blocks.extend(output.visual_blocks)
                result.parsed_count += 1

            except Exception as exc:
                result.error_count += 1
                result.errors.append({
                    "document_id": doc.document_id,
                    "source_uri": doc.source_uri,
                    "error": str(exc),
                })
                logger.error("Parse failed for %s: %s", doc.source_uri, exc)

        logger.info(
            "Pipeline complete: %d parsed, %d errors, %d visual blocks",
            result.parsed_count,
            result.error_count,
            len(result.visual_blocks),
        )
        return result

    def _scan_source(self) -> list[dict]:
        """Scan S3 or local directory for files."""
        if self._config.local_dir:
            return self._scan_local(Path(self._config.local_dir))
        elif self._s3_client and self._config.s3_bucket:
            return self._scan_s3()
        else:
            logger.warning("No source configured (no s3_bucket or local_dir)")
            return []

    def _scan_s3(self) -> list[dict]:
        """Scan S3 using the S3Client."""
        objects = self._s3_client.list_objects(
            prefix=self._config.s3_prefix,
            max_keys=self._config.max_files,
            extensions=self._config.allowed_extensions,
        )
        return [
            {
                "uri": obj.uri,
                "bucket": obj.bucket,
                "key": obj.key,
                "size": obj.size,
                "last_modified": obj.last_modified,
                "etag": obj.etag,
                "content_type": obj.content_type,
            }
            for obj in objects
        ]

    def _scan_local(self, directory: Path) -> list[dict]:
        """Scan a local directory for files."""
        if not directory.exists():
            logger.error("Local directory does not exist: %s", directory)
            return []

        records: list[dict] = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            if self._config.allowed_extensions:
                if path.suffix.lower() not in self._config.allowed_extensions:
                    continue

            uri = f"file://{path.resolve()}"
            stat = path.stat()
            records.append({
                "uri": uri,
                "key": str(path.relative_to(directory)),
                "bucket": "",
                "size": stat.st_size,
                "last_modified": None,
                "etag": "",
                "content_type": "",
            })

            if self._config.max_files and len(records) >= self._config.max_files:
                break

        return records

    def _fetch_content(self, doc: SourceDocument) -> Optional[bytes]:
        """Fetch file content from S3 or local filesystem."""
        uri = doc.source_uri

        if uri.startswith("file://"):
            local_path = Path(uri.replace("file://", ""))
            if local_path.exists():
                return local_path.read_bytes()
            logger.warning("Local file not found: %s", local_path)
            return None

        if uri.startswith("s3://") and self._s3_client:
            return self._s3_client.download_bytes(doc.s3_key)

        logger.warning("Cannot fetch content for: %s", uri)
        return None
