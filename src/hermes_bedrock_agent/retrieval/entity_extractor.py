"""Deterministic entity extraction from queries and chunks. No LLM calls."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..knowledge_base.schemas import RetrievedChunk


@dataclass
class ExtractedEntity:
    text: str
    entity_type: str  # api, field, mapping, process, status, file, system, rule, condition, business_term, id_code
    source: str  # "query", "rewrite", "chunk"
    confidence: float  # 0.0 - 1.0


_KEYWORD_TYPE_TRIGGERS: list[tuple[list[str], str]] = [
    (["API", "api", "endpoint", "エンドポイント"], "api"),
    (["マッピング", "mapping", "変換"], "mapping"),
    (["ルール", "条件", "rule", "condition"], "rule"),
    (["フロー", "処理", "flow", "process", "シーケンス"], "process"),
    (["ステータス", "status", "状態"], "status"),
    (["ファイル", "file", "パス"], "file"),
    (["システム", "system", "サーバ"], "system"),
]


def _detect_keyword_context(query: str, term: str) -> Optional[str]:
    """Check if the query context suggests a specific entity type for the term."""
    q_lower = query.lower()
    for keywords, etype in _KEYWORD_TYPE_TRIGGERS:
        for kw in keywords:
            if kw.lower() in q_lower:
                return etype
    return None


def _extract_from_text(text: str, source: str) -> list[ExtractedEntity]:
    """Extract entities from a single text string."""
    entities: list[ExtractedEntity] = []

    # Alphanumeric codes (N101, 301, 302, A001) — highest confidence
    # Cannot use \b on both sides since CJK chars are \w in Python regex
    for m in re.finditer(r"(?<![A-Za-z0-9_])[A-Z]\d{2,4}(?![A-Za-z0-9_])|(?<![A-Za-z0-9_])\d{3,4}(?![A-Za-z0-9_])", text):
        t = m.group(0)
        entities.append(ExtractedEntity(text=t, entity_type="id_code", source=source, confidence=0.9))

    # UPPER_CASE identifiers (COMPANY_CODE, SAP_ID)
    for m in re.finditer(r"\b[A-Z][A-Z0-9_]{2,}\b", text):
        t = m.group(0)
        # Determine if field or id_code based on presence of underscore
        etype = "field" if "_" in t else "id_code"
        entities.append(ExtractedEntity(text=t, entity_type=etype, source=source, confidence=0.8))

    # CamelCase words (DataSpider, PurchaseOrder)
    for m in re.finditer(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", text):
        t = m.group(0)
        context_type = _detect_keyword_context(text, t)
        etype = context_type if context_type in ("api", "system") else "api"
        entities.append(ExtractedEntity(text=t, entity_type=etype, source=source, confidence=0.7))

    # Katakana terms >= 2 chars
    for m in re.finditer(r"[゠-ヿ]{2,}", text):
        t = m.group(0)
        context_type = _detect_keyword_context(text, t)
        if context_type:
            etype = context_type
            conf = 0.75
        else:
            etype = "business_term"
            conf = 0.7
        entities.append(ExtractedEntity(text=t, entity_type=etype, source=source, confidence=conf))

    # Kanji compound words >= 2 chars
    for m in re.finditer(r"[一-鿿]{2,}", text):
        t = m.group(0)
        context_type = _detect_keyword_context(text, t)
        if context_type:
            etype = context_type
            conf = 0.7
        else:
            etype = "business_term"
            conf = 0.6
        entities.append(ExtractedEntity(text=t, entity_type=etype, source=source, confidence=conf))

    return entities


def _extract_from_chunks(chunks: list[RetrievedChunk]) -> list[ExtractedEntity]:
    """Extract entities from chunk metadata (workbook_name, sheet_name)."""
    entities: list[ExtractedEntity] = []
    seen_workbooks: set[str] = set()
    seen_sheets: set[str] = set()

    for chunk in chunks:
        wb = getattr(chunk, "workbook_name", "") or getattr(chunk, "document_name", "") or ""
        if wb and wb not in seen_workbooks:
            seen_workbooks.add(wb)
            entities.append(ExtractedEntity(
                text=wb, entity_type="business_term", source="chunk", confidence=0.5,
            ))

        sn = getattr(chunk, "sheet_name", "") or ""
        if sn and sn not in seen_sheets:
            seen_sheets.add(sn)
            entities.append(ExtractedEntity(
                text=sn, entity_type="business_term", source="chunk", confidence=0.4,
            ))

    return entities


def _deduplicate(entities: list[ExtractedEntity]) -> list[ExtractedEntity]:
    """Deduplicate by text (case-insensitive), keeping highest confidence."""
    best: dict[str, ExtractedEntity] = {}
    for e in entities:
        key = e.text.lower()
        if key not in best or e.confidence > best[key].confidence:
            best[key] = e
    return list(best.values())


def extract_entities(
    original_query: str,
    rewritten_queries: list[str],
    top_chunks: list[RetrievedChunk],
    max_entities: int = 20,
) -> list[ExtractedEntity]:
    """Deterministic lightweight entity extraction. No LLM calls.

    Processes original query, rewritten queries, and top chunk metadata
    to produce a ranked list of entities for graph expansion.
    """
    all_entities: list[ExtractedEntity] = []

    # Process original query first (highest priority source)
    all_entities.extend(_extract_from_text(original_query, source="query"))

    # Process rewritten queries
    for rq in rewritten_queries:
        if rq:
            all_entities.extend(_extract_from_text(rq, source="rewrite"))

    # Process top chunks metadata
    all_entities.extend(_extract_from_chunks(top_chunks))

    # Deduplicate and truncate
    deduped = _deduplicate(all_entities)

    # Sort by confidence descending, then by source priority (query > rewrite > chunk)
    source_priority = {"query": 0, "rewrite": 1, "chunk": 2}
    deduped.sort(key=lambda e: (-e.confidence, source_priority.get(e.source, 3)))

    return deduped[:max_entities]
