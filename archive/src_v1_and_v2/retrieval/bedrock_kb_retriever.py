"""Bedrock Knowledge Base retriever — optional KB-based retrieval.

Provides:
- BedrockKBRetriever: retrieve from Bedrock Knowledge Bases
- Converts KB results to TextEvidence format

Separate from text_retriever.py (which handles OpenSearch).
Uses clients/bedrock_kb_client.py for all Bedrock KB communication.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Optional

from hermes_bedrock_agent.configs.logging import get_logger
from hermes_bedrock_agent.schemas.retrieval import RetrievalSource, TextEvidence

logger = get_logger(__name__)


@dataclass
class KBRetrieverConfig:
    """Configuration for Bedrock KB retrieval."""

    knowledge_base_id: str = ""
    top_k: int = 5
    min_score: float = 0.0


class BedrockKBRetriever:
    """Bedrock Knowledge Base retriever.

    Queries one or more Bedrock Knowledge Bases and converts results
    to TextEvidence format compatible with the fusion stage.

    Uses clients/bedrock_kb_client.py via dependency injection.
    """

    def __init__(
        self,
        kb_client,
        config: Optional[KBRetrieverConfig] = None,
    ):
        """Initialize with injected Bedrock KB client.

        Args:
            kb_client: Instance of BedrockKBClient from clients/.
            config: Retrieval configuration.
        """
        self._client = kb_client
        self.config = config or KBRetrieverConfig()

    def retrieve(
        self,
        query_text: str,
        *,
        knowledge_base_id: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> list[TextEvidence]:
        """Retrieve from a single Bedrock Knowledge Base.

        Args:
            query_text: Search query.
            knowledge_base_id: KB ID (overrides config default).
            top_k: Number of results to retrieve.

        Returns:
            List of TextEvidence objects from the KB.
        """
        kb_id = knowledge_base_id or self.config.knowledge_base_id
        k = top_k or self.config.top_k

        if not kb_id:
            logger.warning("No knowledge_base_id configured for KB retrieval")
            return []

        try:
            results = self._client.retrieve(
                query=query_text,
                kb_id=kb_id,
                top_k=k,
            )
        except Exception as e:
            logger.warning(f"Bedrock KB retrieval failed: {e}")
            return []

        return self._parse_results(results, query_text=query_text)

    def retrieve_multi(
        self,
        query_text: str,
        knowledge_base_ids: list[str],
        *,
        top_k: Optional[int] = None,
    ) -> list[TextEvidence]:
        """Retrieve from multiple Bedrock Knowledge Bases.

        Args:
            query_text: Search query.
            knowledge_base_ids: List of KB IDs to query.
            top_k: Number of results per KB.

        Returns:
            Combined TextEvidence list from all KBs.
        """
        all_evidence: list[TextEvidence] = []
        k = top_k or self.config.top_k

        for kb_id in knowledge_base_ids:
            evidence = self.retrieve(query_text, knowledge_base_id=kb_id, top_k=k)
            all_evidence.extend(evidence)

        # Re-rank by score
        all_evidence.sort(key=lambda e: e.score, reverse=True)
        for rank, ev in enumerate(all_evidence):
            all_evidence[rank] = ev.model_copy(update={"rank": rank})

        return all_evidence

    def _parse_results(
        self,
        results: Any,
        query_text: str = "",
    ) -> list[TextEvidence]:
        """Parse Bedrock KB response into TextEvidence list."""
        evidence_list: list[TextEvidence] = []

        if not results:
            return evidence_list

        # Handle list of result dicts
        items = results if isinstance(results, list) else []
        if isinstance(results, dict):
            items = results.get("results", results.get("retrievalResults", []))

        for rank, item in enumerate(items):
            content = ""
            source_uri = ""
            score = 0.0

            if isinstance(item, dict):
                # Standard Bedrock KB response format
                content_obj = item.get("content", {})
                if isinstance(content_obj, dict):
                    content = content_obj.get("text", "")
                elif isinstance(content_obj, str):
                    content = content_obj

                location = item.get("location", {})
                if isinstance(location, dict):
                    s3_loc = location.get("s3Location", {})
                    source_uri = s3_loc.get("uri", location.get("uri", ""))

                score = item.get("score", item.get("relevanceScore", 0.5))

            if not content:
                continue

            # Filter by min_score
            if score < self.config.min_score:
                continue

            # Generate stable evidence_id
            evidence_id = hashlib.sha256(
                f"kb_{source_uri}:{rank}:{query_text[:50]}".encode()
            ).hexdigest()[:16]

            # Generate chunk_id from content hash (KB doesn't provide chunk_id)
            chunk_id = hashlib.sha256(content[:200].encode()).hexdigest()[:12]

            evidence = TextEvidence(
                evidence_id=f"kb_{evidence_id}",
                chunk_id=f"kb_chunk_{chunk_id}",
                document_id=f"kb_doc_{hashlib.sha256(source_uri.encode()).hexdigest()[:8]}",
                source_uri=source_uri,
                content=content,
                source=RetrievalSource.BEDROCK_KB,
                score=score,
                rank=rank,
                query_text=query_text,
            )
            evidence_list.append(evidence)

        return evidence_list
