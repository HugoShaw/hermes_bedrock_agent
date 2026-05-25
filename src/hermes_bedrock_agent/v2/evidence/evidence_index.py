"""
Thin adapter for building a LanceDB vector index from evidence chunks.

Two modes:
  jsonl-only   — skip index building entirely (default for Stage 04)
  build-index  — embed chunks and write to a LanceDB collection

When embedding is not available (missing credentials, missing model access),
the builder gracefully reports the issue without failing the pipeline.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.schemas.evidence_schema import EvidenceChunk

logger = logging.getLogger(__name__)


class EvidenceIndexStatus:
    """Result of an index build attempt."""

    def __init__(
        self,
        requested: bool = False,
        success: bool = False,
        collection_name: str = "",
        chunks_indexed: int = 0,
        error: str = "",
    ) -> None:
        self.requested = requested
        self.success = success
        self.collection_name = collection_name
        self.chunks_indexed = chunks_indexed
        self.error = error

    @property
    def status_label(self) -> str:
        if not self.requested:
            return "not_requested"
        if self.success:
            return "built_successfully"
        if self.error:
            return "failed"
        return "skipped"

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "success": self.success,
            "status": self.status_label,
            "collection_name": self.collection_name,
            "chunks_indexed": self.chunks_indexed,
            "error": self.error,
        }


class EvidenceIndex:
    """Adapter for LanceDB vector index building.

    Supports two modes:
      - ``build_index=False`` → returns immediately (jsonl-only)
      - ``build_index=True`` → attempts to embed and write to LanceDB

    Parameters
    ----------
    collection_name:
        LanceDB collection/table name (e.g. ``murata_e2e_murata_semantic_v2``).
    db_path:
        Path to the LanceDB data directory (default: ``data/lancedb``).
    embedding_model:
        Bedrock embedding model ID (default: ``amazon.titan-embed-text-v2:0``).
    embedding_dimension:
        Expected embedding vector dimension (default: 1024).
    region:
        AWS region for Bedrock embedding calls.
    """

    def __init__(
        self,
        collection_name: str = "murata_e2e_murata_semantic_v2",
        db_path: str = "data/lancedb",
        embedding_model: str = "amazon.titan-embed-text-v2:0",
        embedding_dimension: int = 1024,
        region: str = "ap-northeast-1",
    ) -> None:
        self.collection_name = collection_name
        self.db_path = db_path
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        self.region = region

    def build(
        self,
        chunks: list[EvidenceChunk],
        *,
        build_index: bool = False,
    ) -> EvidenceIndexStatus:
        """Optionally build the vector index.

        Args:
            chunks: Evidence chunks to index.
            build_index: If False (default), skip entirely.

        Returns:
            EvidenceIndexStatus with outcome details.
        """
        if not build_index:
            logger.info("Vector index build not requested — skipping (jsonl-only mode)")
            return EvidenceIndexStatus(requested=False)

        logger.info(
            "Vector index build requested: collection=%s, chunks=%d",
            self.collection_name, len(chunks),
        )

        try:
            return self._do_build(chunks)
        except Exception as exc:
            err_msg = f"Vector index build failed: {exc}"
            logger.error(err_msg)
            return EvidenceIndexStatus(
                requested=True,
                success=False,
                collection_name=self.collection_name,
                error=err_msg,
            )

    def _do_build(self, chunks: list[EvidenceChunk]) -> EvidenceIndexStatus:
        """Attempt actual LanceDB index building."""
        # Check dependencies
        try:
            import lancedb  # type: ignore
        except ImportError:
            return EvidenceIndexStatus(
                requested=True, success=False,
                collection_name=self.collection_name,
                error="lancedb package not installed",
            )

        try:
            import boto3
        except ImportError:
            return EvidenceIndexStatus(
                requested=True, success=False,
                collection_name=self.collection_name,
                error="boto3 not available for embedding calls",
            )

        # Open/create LanceDB
        db_dir = Path(self.db_path)
        db_dir.mkdir(parents=True, exist_ok=True)
        db = lancedb.connect(str(db_dir))

        # Embed chunks
        bedrock = boto3.client("bedrock-runtime", region_name=self.region)
        records: list[dict] = []
        errors = 0

        for chunk in chunks:
            text = chunk.text[:8000]  # Titan v2 limit
            try:
                response = bedrock.invoke_model(
                    modelId=self.embedding_model,
                    body=__import__("json").dumps({
                        "inputText": text,
                        "dimensions": self.embedding_dimension,
                    }),
                    contentType="application/json",
                    accept="application/json",
                )
                result = __import__("json").loads(response["body"].read())
                embedding = result["embedding"]
            except Exception as exc:
                errors += 1
                if errors <= 3:
                    logger.warning("Embedding failed for chunk %s: %s", chunk.chunk_id, exc)
                if errors == 10:
                    return EvidenceIndexStatus(
                        requested=True, success=False,
                        collection_name=self.collection_name,
                        chunks_indexed=len(records),
                        error=f"Too many embedding failures ({errors}), aborting",
                    )
                continue

            records.append({
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "section_id": chunk.section_id or "",
                "chunk_type": chunk.chunk_type,
                "doc_type": chunk.doc_type,
                "title": chunk.title,
                "text": text,
                "source_path": chunk.source_path,
                "run_id": chunk.run_id,
                "dataset": chunk.dataset,
                "vector": embedding,
            })

        if not records:
            return EvidenceIndexStatus(
                requested=True, success=False,
                collection_name=self.collection_name,
                error="No records to index (all embeddings failed)",
            )

        # Write to LanceDB
        import pyarrow as pa  # type: ignore

        table = db.create_table(
            self.collection_name,
            data=records,
            mode="overwrite",
        )
        logger.info(
            "Created LanceDB table '%s' with %d records",
            self.collection_name, len(records),
        )

        return EvidenceIndexStatus(
            requested=True,
            success=True,
            collection_name=self.collection_name,
            chunks_indexed=len(records),
        )
