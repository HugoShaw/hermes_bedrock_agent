"""LanceDB vector store — local vector database backend.

Provides:
- LanceDBStore: VectorStoreBackend implementation using LanceDB
- Local-first: no external service dependency
- Default path: ~/projects/data/vector_store/lancedb

Supports:
- Vector similarity search (cosine, L2, dot)
- Simple keyword search (text contains fallback)
- Hybrid search (RRF fusion of vector + keyword)
- Metadata filtering via LanceDB SQL-like WHERE clauses
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.vector_store.base import (
    VectorSearchResult,
    VectorStoreBackend,
    VectorStoreRecord,
)

logger = get_logger(__name__)

# Default path
DEFAULT_LANCEDB_PATH = os.path.expanduser("~/projects/data/vector_store/lancedb")
DEFAULT_COLLECTION = "murata_e2e"


class LanceDBStore(VectorStoreBackend):
    """LanceDB local vector store implementation.

    Features:
    - Zero-dependency local vector DB (no server required)
    - Cosine / L2 / dot product distance
    - Metadata filtering via SQL WHERE clauses
    - Keyword fallback via text LIKE matching
    - Hybrid search via RRF fusion

    Args:
        db_path: Path to LanceDB storage directory.
        collection: Table/collection name.
        distance: Distance metric ('cosine', 'L2', 'dot').
        rrf_k: RRF constant for hybrid search fusion.
    """

    def __init__(
        self,
        *,
        db_path: str = DEFAULT_LANCEDB_PATH,
        collection: str = DEFAULT_COLLECTION,
        distance: str = "cosine",
        rrf_k: int = 60,
    ):
        self._db_path = db_path
        self._collection = collection
        self._distance = distance
        self._rrf_k = rrf_k
        self._db = None
        self._table = None

    def _ensure_connection(self):
        """Lazily connect to LanceDB and get or verify table exists."""
        if self._db is not None:
            return

        try:
            import lancedb
        except ImportError as e:
            raise ImportError(
                "LanceDB is required for local vector store. "
                "Install it with: pip install lancedb"
            ) from e

        # Ensure directory exists
        Path(self._db_path).mkdir(parents=True, exist_ok=True)

        self._db = lancedb.connect(self._db_path)

        # Check if table already exists
        try:
            resp = self._db.list_tables()
            existing_tables = resp.tables if hasattr(resp, "tables") else list(resp)
        except (AttributeError, TypeError):
            # Fallback for older LanceDB versions
            existing_tables = self._db.table_names()  # type: ignore[attr-defined]

        if self._collection in existing_tables:
            self._table = self._db.open_table(self._collection)
            logger.debug(
                f"Opened existing LanceDB table: {self._collection} "
                f"({self._table.count_rows()} rows)"
            )
        else:
            self._table = None
            logger.debug(f"LanceDB table '{self._collection}' not yet created")

    def _create_table_from_records(self, records: list[VectorStoreRecord]):
        """Create table from first batch of records."""
        data = [self._record_to_dict(r) for r in records]
        self._table = self._db.create_table(self._collection, data)
        logger.info(
            f"Created LanceDB table '{self._collection}' with {len(data)} records"
        )

    def _record_to_dict(self, record: VectorStoreRecord) -> dict[str, Any]:
        """Convert VectorStoreRecord to LanceDB row dict."""
        return {
            "chunk_id": record.chunk_id,
            "document_id": record.document_id,
            "text": record.text,
            "vector": record.embedding,
            "source_uri": record.source_uri,
            "source_type": record.source_type,
            "page": record.page if record.page is not None else -1,
            "section_title": record.section_title,
            "visual_block_ids": json.dumps(record.visual_block_ids),
            "acl": json.dumps(record.acl),
            "content_hash": record.content_hash,
            "embedding_model": record.embedding_model,
            "metadata_json": json.dumps(record.metadata),
        }

    def _row_to_result(self, row: dict[str, Any], rank: int = 0) -> VectorSearchResult:
        """Convert LanceDB row to VectorSearchResult."""
        distance = row.get("_distance", 0.0)
        # Convert distance to similarity score:
        # LanceDB cosine distance ranges [0, 2]. Use reciprocal normalization
        # so that score is always in (0, 1] even when distance > 1.
        if distance is not None and distance >= 0:
            score = 1.0 / (1.0 + distance)
        else:
            score = 0.0

        # Parse JSON fields
        visual_ids = []
        acl = []
        try:
            visual_ids = json.loads(row.get("visual_block_ids", "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            acl = json.loads(row.get("acl", "[]"))
        except (json.JSONDecodeError, TypeError):
            pass

        page_val = row.get("page")
        if page_val == -1:
            page_val = None

        return VectorSearchResult(
            chunk_id=row.get("chunk_id", ""),
            document_id=row.get("document_id", ""),
            text=row.get("text", ""),
            source_uri=row.get("source_uri", ""),
            source_type=row.get("source_type", ""),
            page=page_val,
            section_title=row.get("section_title", ""),
            visual_block_ids=visual_ids,
            acl=acl,
            score=score,
            distance=distance if distance is not None else 0.0,
        )

    def _build_where_clause(self, filters: Optional[dict[str, Any]]) -> Optional[str]:
        """Build LanceDB WHERE clause from filter dict.

        Supports:
        - {"field": "value"} → field = 'value'
        - {"field": ["v1", "v2"]} → field IN ('v1', 'v2')
        """
        if not filters:
            return None

        clauses = []
        for key, value in filters.items():
            if isinstance(value, list):
                # IN clause
                vals = ", ".join(f"'{v}'" for v in value)
                clauses.append(f"{key} IN ({vals})")
            elif isinstance(value, str):
                clauses.append(f"{key} = '{value}'")
            elif isinstance(value, (int, float)):
                clauses.append(f"{key} = {value}")
            else:
                clauses.append(f"{key} = '{value}'")

        return " AND ".join(clauses) if clauses else None

    # --- VectorStoreBackend interface ---

    def upsert_chunks(self, records: list[VectorStoreRecord]) -> int:
        """Insert or update chunk records into LanceDB.

        If table doesn't exist, creates it. Otherwise appends.
        """
        if not records:
            return 0

        self._ensure_connection()

        if self._table is None:
            self._create_table_from_records(records)
            return len(records)

        # Add to existing table
        data = [self._record_to_dict(r) for r in records]
        self._table.add(data)
        logger.debug(f"Added {len(data)} records to LanceDB table '{self._collection}'")
        return len(data)

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """Vector similarity search using LanceDB.

        Args:
            query_embedding: Query vector.
            top_k: Number of results.
            filters: Metadata filters (converted to WHERE clause).

        Returns:
            Ranked results by cosine similarity.
        """
        self._ensure_connection()

        if self._table is None:
            logger.warning("No table exists yet — returning empty results")
            return []

        query = self._table.search(query_embedding).limit(top_k)

        where_clause = self._build_where_clause(filters)
        if where_clause:
            query = query.where(where_clause)

        try:
            results = query.to_list()
        except Exception as e:
            logger.warning(f"LanceDB vector search failed: {e}")
            return []

        return [self._row_to_result(row, rank=i) for i, row in enumerate(results)]

    def keyword_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """Keyword search using text LIKE matching.

        LanceDB doesn't have built-in BM25, so we use SQL LIKE
        for simple keyword matching as a fallback.

        Args:
            query: Search query text.
            top_k: Number of results.
            filters: Metadata filters.

        Returns:
            Results containing the query text.
        """
        self._ensure_connection()

        if self._table is None:
            return []

        # Build WHERE clause for text matching
        # Escape single quotes in query
        safe_query = query.replace("'", "''")
        text_clause = f"text LIKE '%{safe_query}%'"

        # Add additional filters
        extra = self._build_where_clause(filters)
        if extra:
            where = f"{text_clause} AND {extra}"
        else:
            where = text_clause

        try:
            # Use LanceDB table scan with filter
            import pyarrow as pa

            results_df = (
                self._table.search()
                .where(where)
                .limit(top_k)
                .to_list()
            )
        except Exception as e:
            logger.warning(f"LanceDB keyword search failed: {e}")
            # Fallback: scan all and filter in Python
            return self._python_keyword_fallback(query, top_k, filters)

        return [self._row_to_result(row, rank=i) for i, row in enumerate(results_df)]

    def _python_keyword_fallback(
        self,
        query: str,
        top_k: int,
        filters: Optional[dict[str, Any]],
    ) -> list[VectorSearchResult]:
        """Python-level keyword search fallback.

        Scans all records and filters by text contains.
        Used when LanceDB SQL LIKE fails.
        """
        try:
            all_rows = self._table.to_pandas()
        except Exception:
            return []

        query_lower = query.lower()
        matches = []

        for _, row in all_rows.iterrows():
            text = str(row.get("text", ""))
            if query_lower in text.lower():
                row_dict = row.to_dict()
                # Remove vector from result
                row_dict.pop("vector", None)
                row_dict["_distance"] = 0.0
                matches.append(row_dict)

        # Apply filters
        if filters:
            filtered = []
            for m in matches:
                match = True
                for key, value in filters.items():
                    if isinstance(value, list):
                        if m.get(key) not in value:
                            match = False
                    elif m.get(key) != value:
                        match = False
                if match:
                    filtered.append(m)
            matches = filtered

        return [
            self._row_to_result(m, rank=i) for i, m in enumerate(matches[:top_k])
        ]

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        *,
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
    ) -> list[VectorSearchResult]:
        """Hybrid search combining vector + keyword via RRF.

        Uses Reciprocal Rank Fusion to combine:
        1. Vector similarity results
        2. Keyword text matching results

        Args:
            query: Text query for keyword matching.
            query_embedding: Query vector for similarity search.
            top_k: Number of final results.
            filters: Metadata filters applied to both searches.

        Returns:
            Fused results ranked by RRF score.
        """
        # Get both result sets
        vector_results = self.search(
            query_embedding, top_k=top_k * 2, filters=filters
        )
        keyword_results = self.keyword_search(query, top_k=top_k * 2, filters=filters)

        # RRF fusion
        scored: dict[str, tuple[float, VectorSearchResult]] = {}

        for rank, result in enumerate(vector_results):
            rrf_score = 1.0 / (self._rrf_k + rank + 1)
            scored[result.chunk_id] = (rrf_score, result)

        for rank, result in enumerate(keyword_results):
            rrf_score = 1.0 / (self._rrf_k + rank + 1)
            if result.chunk_id in scored:
                old_score, old_result = scored[result.chunk_id]
                scored[result.chunk_id] = (old_score + rrf_score, old_result)
            else:
                scored[result.chunk_id] = (rrf_score, result)

        # Sort by combined RRF score
        sorted_results = sorted(scored.values(), key=lambda x: x[0], reverse=True)

        output = []
        for i, (score, result) in enumerate(sorted_results[:top_k]):
            # Update score to RRF combined score
            updated = VectorSearchResult(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                text=result.text,
                source_uri=result.source_uri,
                source_type=result.source_type,
                page=result.page,
                section_title=result.section_title,
                visual_block_ids=result.visual_block_ids,
                acl=result.acl,
                score=score,
                distance=result.distance,
                metadata=result.metadata,
            )
            output.append(updated)

        return output

    def count(self) -> int:
        """Return total number of records."""
        self._ensure_connection()
        if self._table is None:
            return 0
        return self._table.count_rows()

    def delete_collection(self) -> bool:
        """Delete the entire collection/table."""
        self._ensure_connection()
        try:
            self._db.drop_table(self._collection)
            self._table = None
            logger.info(f"Deleted LanceDB table '{self._collection}'")
            return True
        except Exception as e:
            logger.warning(f"Failed to delete LanceDB table: {e}")
            return False

    def health_check(self) -> dict[str, Any]:
        """Check LanceDB health."""
        try:
            self._ensure_connection()
            row_count = self._table.count_rows() if self._table else 0
            return {
                "healthy": True,
                "backend": "lancedb",
                "db_path": self._db_path,
                "collection": self._collection,
                "row_count": row_count,
                "distance_metric": self._distance,
            }
        except Exception as e:
            return {
                "healthy": False,
                "backend": "lancedb",
                "error": str(e),
            }
