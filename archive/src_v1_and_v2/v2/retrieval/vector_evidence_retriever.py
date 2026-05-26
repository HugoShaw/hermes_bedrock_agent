"""
V2 Vector Evidence Retriever — JSONL-backed keyword retrieval over evidence chunks.

Retrieves evidence chunks using keyword matching with CJK-aware tokenization.
Supports query-based retrieval, chunk ID lookup, document/source filtering.

No LLM or vector embedding required — uses heuristic scoring.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.schemas.retrieval_schema import RetrievalResult


# ============================================================
# CJK-aware tokenizer
# ============================================================

_CJK_CHAR = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]')
_WORD_PATTERN = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*|[\u4e00-\u9fff]|[\u3040-\u309f]+|[\u30a0-\u30ff]+')


def tokenize(text: str | list | Any) -> list[str]:
    """Simple CJK-aware tokenizer: splits into words, individual CJK chars, kana sequences."""
    if not text:
        return []
    if isinstance(text, list):
        text = ' '.join(str(t) for t in text)
    elif not isinstance(text, str):
        text = str(text)
    return [m.lower() for m in _WORD_PATTERN.findall(text)]


def token_overlap_score(query_tokens: list[str], text: str | list | Any) -> float:
    """Compute token overlap score between query tokens and text."""
    if not query_tokens or not text:
        return 0.0
    text_tokens = set(tokenize(text))
    if not text_tokens:
        return 0.0
    matched = sum(1 for t in query_tokens if t in text_tokens)
    return matched / len(query_tokens)


# ============================================================
# Chunk type boost weights
# ============================================================

CHUNK_TYPE_BOOSTS = {
    'summary': 1.5,
    'section': 1.3,
    'small': 1.0,
    'table': 1.2,
    'code': 0.9,
    'sql': 0.8,
    'api': 1.4,
    'config': 0.7,
    'testcase': 0.6,
    'operation': 1.1,
}


class VectorEvidenceRetriever:
    """JSONL-backed evidence chunk retriever with keyword scoring."""

    def __init__(
        self,
        output_dir: str | Path,
    ):
        self.output_dir = Path(output_dir)
        self._chunks: list[dict[str, Any]] | None = None
        self._chunk_index: dict[str, dict[str, Any]] | None = None
        self._doc_index: dict[str, list[dict[str, Any]]] | None = None

    def _load(self) -> None:
        """Lazy-load evidence chunks."""
        if self._chunks is not None:
            return

        chunks_path = self.output_dir / 'evidence_chunks.jsonl'
        self._chunks = []
        self._chunk_index = {}
        self._doc_index = {}

        with open(chunks_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                chunk = json.loads(line)
                self._chunks.append(chunk)
                cid = chunk.get('chunk_id', '')
                if cid:
                    self._chunk_index[cid] = chunk
                doc_id = chunk.get('document_id', '')
                if doc_id:
                    self._doc_index.setdefault(doc_id, []).append(chunk)

    def _score_chunk(
        self,
        chunk: dict[str, Any],
        query_tokens: list[str],
        query_raw: str,
    ) -> float:
        """Score a chunk's relevance to a query."""
        score = 0.0

        # Text overlap
        text = chunk.get('text', '')
        text_score = token_overlap_score(query_tokens, text)
        score += text_score * 3.0

        # Title overlap
        title = chunk.get('title', '')
        title_score = token_overlap_score(query_tokens, title)
        score += title_score * 2.0

        # Heading path overlap
        heading = chunk.get('heading_path', '')
        heading_score = token_overlap_score(query_tokens, heading)
        score += heading_score * 1.5

        # Source path partial match
        source_path = chunk.get('source_path', '')
        source_score = token_overlap_score(query_tokens, source_path)
        score += source_score * 1.0

        # Exact substring match boost (for short queries)
        query_lower = query_raw.lower()
        if len(query_lower) < 20 and query_lower in text.lower():
            score += 2.0
        elif len(query_lower) < 40:
            # Check partial matches for each CJK segment
            for token in query_tokens:
                if len(token) >= 2 and token in text.lower():
                    score += 0.5

        # Chunk type boost
        chunk_type = chunk.get('chunk_type', 'small')
        type_boost = CHUNK_TYPE_BOOSTS.get(chunk_type, 1.0)
        score *= type_boost

        return score

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        """Retrieve top-k evidence chunks matching query."""
        self._load()
        assert self._chunks is not None

        query_tokens = tokenize(query)
        if not query_tokens:
            return RetrievalResult(
                source='vector_evidence',
                items=[],
                score=0.0,
                metadata={'query': query, 'top_k': top_k, 'reason': 'empty query tokens'},
            )

        # Apply filters
        candidates = self._chunks
        if filters:
            if 'chunk_type' in filters:
                ct = filters['chunk_type']
                if isinstance(ct, str):
                    candidates = [c for c in candidates if c.get('chunk_type') == ct]
                elif isinstance(ct, list):
                    candidates = [c for c in candidates if c.get('chunk_type') in ct]
            if 'document_id' in filters:
                did = filters['document_id']
                candidates = [c for c in candidates if c.get('document_id') == did]
            if 'source_path' in filters:
                sp = filters['source_path']
                candidates = [c for c in candidates if sp.lower() in (c.get('source_path') or '').lower()]

        # Score all candidates
        scored: list[tuple[float, dict[str, Any]]] = []
        for chunk in candidates:
            s = self._score_chunk(chunk, query_tokens, query)
            if s > 0:
                scored.append((s, chunk))

        # Sort by score descending
        scored.sort(key=lambda x: -x[0])

        # Take top_k
        top_items = []
        for score, chunk in scored[:top_k]:
            top_items.append({
                'chunk_id': chunk.get('chunk_id', ''),
                'document_id': chunk.get('document_id', ''),
                'section_id': chunk.get('section_id', ''),
                'chunk_type': chunk.get('chunk_type', ''),
                'title': chunk.get('title', ''),
                'heading_path': chunk.get('heading_path', ''),
                'source_path': chunk.get('source_path', ''),
                'text': chunk.get('text', '')[:500],  # Truncate for context
                'score': round(score, 4),
            })

        avg_score = sum(item['score'] for item in top_items) / max(len(top_items), 1)

        return RetrievalResult(
            source='vector_evidence',
            items=top_items,
            score=round(avg_score, 4),
            metadata={
                'query': query,
                'top_k': top_k,
                'total_candidates': len(candidates),
                'total_matched': len(scored),
                'filters_applied': filters or {},
            },
        )

    def retrieve_by_chunk_ids(self, chunk_ids: list[str]) -> RetrievalResult:
        """Retrieve specific chunks by ID."""
        self._load()
        assert self._chunk_index is not None

        items = []
        for cid in chunk_ids:
            chunk = self._chunk_index.get(cid)
            if chunk:
                items.append({
                    'chunk_id': chunk.get('chunk_id', ''),
                    'document_id': chunk.get('document_id', ''),
                    'section_id': chunk.get('section_id', ''),
                    'chunk_type': chunk.get('chunk_type', ''),
                    'title': chunk.get('title', ''),
                    'heading_path': chunk.get('heading_path', ''),
                    'source_path': chunk.get('source_path', ''),
                    'text': chunk.get('text', '')[:500],
                    'score': 1.0,
                })

        return RetrievalResult(
            source='vector_evidence',
            items=items,
            score=1.0 if items else 0.0,
            metadata={
                'mode': 'by_chunk_ids',
                'requested': len(chunk_ids),
                'found': len(items),
            },
        )

    def retrieve_by_document_id(self, document_id: str, top_k: int = 20) -> RetrievalResult:
        """Retrieve chunks belonging to a document."""
        self._load()
        assert self._doc_index is not None

        doc_chunks = self._doc_index.get(document_id, [])
        items = []
        for chunk in doc_chunks[:top_k]:
            items.append({
                'chunk_id': chunk.get('chunk_id', ''),
                'document_id': chunk.get('document_id', ''),
                'chunk_type': chunk.get('chunk_type', ''),
                'title': chunk.get('title', ''),
                'heading_path': chunk.get('heading_path', ''),
                'source_path': chunk.get('source_path', ''),
                'text': chunk.get('text', '')[:500],
                'score': 1.0,
            })

        return RetrievalResult(
            source='vector_evidence',
            items=items,
            score=1.0 if items else 0.0,
            metadata={
                'mode': 'by_document_id',
                'document_id': document_id,
                'total_chunks_in_doc': len(doc_chunks),
                'returned': len(items),
            },
        )

    def retrieve_by_source_path(self, source_path: str, top_k: int = 20) -> RetrievalResult:
        """Retrieve chunks from a specific source path."""
        self._load()
        assert self._chunks is not None

        sp_lower = source_path.lower()
        matched = [c for c in self._chunks if sp_lower in (c.get('source_path') or '').lower()]

        items = []
        for chunk in matched[:top_k]:
            items.append({
                'chunk_id': chunk.get('chunk_id', ''),
                'document_id': chunk.get('document_id', ''),
                'chunk_type': chunk.get('chunk_type', ''),
                'title': chunk.get('title', ''),
                'heading_path': chunk.get('heading_path', ''),
                'source_path': chunk.get('source_path', ''),
                'text': chunk.get('text', '')[:500],
                'score': 1.0,
            })

        return RetrievalResult(
            source='vector_evidence',
            items=items,
            score=1.0 if items else 0.0,
            metadata={
                'mode': 'by_source_path',
                'source_path': source_path,
                'total_matched': len(matched),
                'returned': len(items),
            },
        )
