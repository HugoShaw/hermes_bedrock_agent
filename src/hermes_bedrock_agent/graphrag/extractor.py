"""Content and relationship extraction for GraphRAG."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Sequence


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ChunkRecord:
    """A text chunk extracted from a document."""

    id: str
    doc_id: str
    chunk_index: int
    text: str
    token_count: int
    created_at: str


@dataclass
class EntityRecord:
    """An entity (concept, person, org, etc.) extracted from a document."""

    id: str
    name: str
    entity_type: str
    description: str
    mention_count: int
    created_at: str


@dataclass
class EdgeRecord:
    """A directed edge between two graph nodes."""

    id: str
    src_id: str
    src_type: str
    dst_id: str
    dst_type: str
    edge_type: str
    weight: float
    metadata: str
    created_at: str


@dataclass
class ExtractionResult:
    """The full output of extracting a single document."""

    doc_id: str
    s3_key: str
    filename: str
    file_type: str
    content_hash: str
    char_count: int
    chunks: list[ChunkRecord] = field(default_factory=list)
    entities: list[EntityRecord] = field(default_factory=list)
    edges: list[EdgeRecord] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------

_APPROX_CHARS_PER_TOKEN = 4
_CHUNK_TOKEN_LIMIT = 512
_CHUNK_OVERLAP_TOKENS = 64
_CHUNK_CHAR_LIMIT = _CHUNK_TOKEN_LIMIT * _APPROX_CHARS_PER_TOKEN
_OVERLAP_CHARS = _CHUNK_OVERLAP_TOKENS * _APPROX_CHARS_PER_TOKEN


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // _APPROX_CHARS_PER_TOKEN)


def _split_into_chunks(paragraphs: list[str]) -> list[str]:
    """Split paragraphs into overlapping chunks of ~512 tokens."""
    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        para_len = len(para)

        if current_len + para_len > _CHUNK_CHAR_LIMIT and current_parts:
            chunk_text = "\n\n".join(current_parts)
            chunks.append(chunk_text)
            # Overlap: keep last _OVERLAP_CHARS of current chunk as seed for next
            overlap_text = chunk_text[-_OVERLAP_CHARS:] if len(chunk_text) > _OVERLAP_CHARS else chunk_text
            current_parts = [overlap_text]
            current_len = len(overlap_text)

        current_parts.append(para)
        current_len += para_len + 2  # +2 for "\n\n"

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks if chunks else [""]


# ---------------------------------------------------------------------------
# File-type text extraction
# ---------------------------------------------------------------------------

def _extract_text_txt(content_bytes: bytes) -> str:
    return content_bytes.decode("utf-8", errors="replace")


def _extract_text_md(content_bytes: bytes) -> str:
    return content_bytes.decode("utf-8", errors="replace")


def _extract_text_pdf(content_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("pypdf is required to read PDF files. Install it with: uv add pypdf") from exc

    reader = PdfReader(io.BytesIO(content_bytes))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def _extract_text_docx(content_bytes: bytes) -> str:
    try:
        from docx import Document  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError("python-docx is required to read DOCX files. Install it with: uv add python-docx") from exc

    doc = Document(io.BytesIO(content_bytes))
    return "\n\n".join(para.text for para in doc.paragraphs if para.text.strip())


def _extract_text_json(content_bytes: bytes) -> str:
    try:
        data = json.loads(content_bytes.decode("utf-8", errors="replace"))
        return json.dumps(data, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        return content_bytes.decode("utf-8", errors="replace")


def _extract_text_csv(content_bytes: bytes) -> str:
    text = content_bytes.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return ""
    header = rows[0]
    lines = [", ".join(header)]
    for row in rows[1:]:
        lines.append(", ".join(f"{h}: {v}" for h, v in zip(header, row)))
    return "\n".join(lines)


_TEXT_EXTRACTORS = {
    "txt": _extract_text_txt,
    "md": _extract_text_md,
    "pdf": _extract_text_pdf,
    "docx": _extract_text_docx,
    "json": _extract_text_json,
    "csv": _extract_text_csv,
}

SUPPORTED_FILE_TYPES = set(_TEXT_EXTRACTORS.keys())


def extract_text(content_bytes: bytes, file_type: str) -> str:
    """Extract plain text from *content_bytes* according to *file_type*."""
    extractor = _TEXT_EXTRACTORS.get(file_type.lower())
    if extractor is None:
        raise ValueError(f"Unsupported file type: {file_type!r}. Supported: {sorted(SUPPORTED_FILE_TYPES)}")
    return extractor(content_bytes)


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

def _extract_entities_spacy(text: str) -> list[tuple[str, str]]:
    """Extract (name, type) pairs using spaCy NER."""
    import spacy  # type: ignore[import]

    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        raise ImportError("spaCy model 'en_core_web_sm' not found")

    doc = nlp(text[:100_000])  # cap to avoid OOM on huge docs
    seen: dict[str, str] = {}
    for ent in doc.ents:
        name = ent.text.strip()
        if len(name) < 2:
            continue
        seen[name] = ent.label_
    return list(seen.items())


_CAPITALIZED_PHRASE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")
_QUOTED_STRING = re.compile(r'"([^"]{2,60})"')


def _extract_entities_regex(text: str) -> list[tuple[str, str]]:
    """Fallback entity extraction: capitalized phrases and quoted strings."""
    seen: dict[str, str] = {}
    for match in _CAPITALIZED_PHRASE.finditer(text):
        name = match.group(1).strip()
        # Skip sentence-starting words when only one word and very common
        if len(name.split()) == 1 and len(name) <= 3:
            continue
        seen.setdefault(name, "CONCEPT")
    for match in _QUOTED_STRING.finditer(text):
        name = match.group(1).strip()
        seen.setdefault(name, "CONCEPT")
    return list(seen.items())


def extract_entities(text: str) -> list[tuple[str, str]]:
    """Extract (name, entity_type) pairs from *text*, preferring spaCy."""
    try:
        return _extract_entities_spacy(text)
    except (ImportError, Exception):
        return _extract_entities_regex(text)


# ---------------------------------------------------------------------------
# ID helpers
# ---------------------------------------------------------------------------

def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

def extract_document(
    s3_key: str,
    content_bytes: bytes,
    file_type: str,
) -> ExtractionResult:
    """Extract chunks, entities, and edges from a document.

    Returns an :class:`ExtractionResult` ready to be persisted to the graph DB.
    """
    filename = s3_key.split("/")[-1]
    file_type = file_type.lower().lstrip(".")
    now = _now_iso()

    raw_text = extract_text(content_bytes, file_type)
    content_hash = _sha256(raw_text)
    doc_id = _sha256(s3_key)

    # Split into paragraphs, then into overlapping chunks
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", raw_text) if p.strip()]
    chunk_texts = _split_into_chunks(paragraphs)

    result = ExtractionResult(
        doc_id=doc_id,
        s3_key=s3_key,
        filename=filename,
        file_type=file_type,
        content_hash=content_hash,
        char_count=len(raw_text),
    )

    # Build chunk records + doc→chunk edges
    chunk_ids: list[str] = []
    entity_map: dict[str, tuple[str, str]] = {}  # canonical_name → (entity_id, entity_type)

    for idx, chunk_text in enumerate(chunk_texts):
        chunk_id = _sha256(s3_key + str(idx))
        chunk_ids.append(chunk_id)
        result.chunks.append(
            ChunkRecord(
                id=chunk_id,
                doc_id=doc_id,
                chunk_index=idx,
                text=chunk_text,
                token_count=_approx_tokens(chunk_text),
                created_at=now,
            )
        )
        # CONTAINS edge: document → chunk
        edge_id = _sha256(doc_id + "CONTAINS" + chunk_id)
        result.edges.append(
            EdgeRecord(
                id=edge_id,
                src_id=doc_id,
                src_type="document",
                dst_id=chunk_id,
                dst_type="chunk",
                edge_type="CONTAINS",
                weight=1.0,
                metadata="{}",
                created_at=now,
            )
        )

        # Extract entities from this chunk
        raw_entities = extract_entities(chunk_text)
        chunk_entity_ids: list[str] = []
        for name, etype in raw_entities:
            canonical = name.strip()
            entity_id = _sha256(canonical)
            entity_map[canonical] = (entity_id, etype)
            chunk_entity_ids.append(entity_id)

            # MENTIONS edge: chunk → entity
            mentions_edge_id = _sha256(chunk_id + "MENTIONS" + entity_id)
            result.edges.append(
                EdgeRecord(
                    id=mentions_edge_id,
                    src_id=chunk_id,
                    src_type="chunk",
                    dst_id=entity_id,
                    dst_type="entity",
                    edge_type="MENTIONS",
                    weight=1.0,
                    metadata="{}",
                    created_at=now,
                )
            )

        # CO_OCCURS edges: entities co-occurring in the same chunk
        seen_pairs: set[frozenset[str]] = set()
        for i, eid_a in enumerate(chunk_entity_ids):
            for eid_b in chunk_entity_ids[i + 1:]:
                pair = frozenset([eid_a, eid_b])
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                co_edge_id = _sha256(eid_a + "CO_OCCURS" + eid_b)
                result.edges.append(
                    EdgeRecord(
                        id=co_edge_id,
                        src_id=eid_a,
                        src_type="entity",
                        dst_id=eid_b,
                        dst_type="entity",
                        edge_type="CO_OCCURS",
                        weight=1.0,
                        metadata=json.dumps({"chunk_id": chunk_id}),
                        created_at=now,
                    )
                )

    # Build entity records
    name_counts: dict[str, int] = {}
    for chunk in result.chunks:
        for name, _ in extract_entities(chunk.text):
            name_counts[name.strip()] = name_counts.get(name.strip(), 0) + 1

    for name, (entity_id, etype) in entity_map.items():
        result.entities.append(
            EntityRecord(
                id=entity_id,
                name=name,
                entity_type=etype,
                description=f"{etype}: {name}",
                mention_count=name_counts.get(name, 1),
                created_at=now,
            )
        )

    # RELATED_TO edges: entities appearing in multiple chunks of same doc
    entity_chunk_sets: dict[str, set[str]] = {}
    for edge in result.edges:
        if edge.edge_type == "MENTIONS":
            entity_chunk_sets.setdefault(edge.dst_id, set()).add(edge.src_id)

    entity_ids_list = list(entity_chunk_sets.keys())
    for i, eid_a in enumerate(entity_ids_list):
        for eid_b in entity_ids_list[i + 1:]:
            shared = entity_chunk_sets[eid_a] & entity_chunk_sets[eid_b]
            if shared:
                rel_edge_id = _sha256(eid_a + "RELATED_TO" + eid_b)
                result.edges.append(
                    EdgeRecord(
                        id=rel_edge_id,
                        src_id=eid_a,
                        src_type="entity",
                        dst_id=eid_b,
                        dst_type="entity",
                        edge_type="RELATED_TO",
                        weight=float(len(shared)),
                        metadata=json.dumps({"shared_chunks": list(shared)}),
                        created_at=now,
                    )
                )

    result.chunks = result.chunks  # already built
    # Deduplicate edges by id
    seen_edge_ids: set[str] = set()
    deduped_edges: list[EdgeRecord] = []
    for e in result.edges:
        if e.id not in seen_edge_ids:
            seen_edge_ids.add(e.id)
            deduped_edges.append(e)
    result.edges = deduped_edges

    return result


def get_file_type_from_key(s3_key: str) -> str:
    """Infer file type from S3 key extension."""
    suffix = s3_key.rsplit(".", 1)[-1].lower() if "." in s3_key else "txt"
    return suffix
