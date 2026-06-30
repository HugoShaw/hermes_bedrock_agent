"""Keyword/lexical search over LanceDB (READ-ONLY)."""

from __future__ import annotations

import logging
import re
from typing import Optional

import lancedb

from ..config import Config, config as _default_config

logger = logging.getLogger(__name__)

# Scan limit for pandas-based keyword search
KEYWORD_SCAN_LIMIT = 2000


def _extract_search_keywords(query: str) -> list[str]:
    """Extract meaningful keywords from a query for lexical matching."""
    # CJK compounds (kanji runs of 2+ chars)
    cjk_pattern = re.compile(r"[一-鿿㐀-䶿]{2,}")
    # Katakana words (3+ chars)
    katakana_pattern = re.compile(r"[゠-ヿ]{3,}")
    # Latin identifiers (2+ chars, alphanumeric/underscore)
    latin_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")

    keywords: list[str] = []
    keywords.extend(cjk_pattern.findall(query))
    keywords.extend(katakana_pattern.findall(query))
    keywords.extend(latin_pattern.findall(query))

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for kw in keywords:
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique


def keyword_search(
    query: str,
    top_k: int = 10,
    project_id: str = "",
    cfg: Optional[Config] = None,
    store_path: Optional[str] = None,
    collection: Optional[str] = None,
) -> list[dict]:
    """Search LanceDB using keyword/lexical matching (READ-ONLY).

    Strategy:
    1. Extract keywords from query (kanji compounds, katakana, latin identifiers)
    2. Open LanceDB table
    3. Load to pandas (filtered by project_id first) — acceptable for <1000 rows/project
    4. Score by keyword match count / total keywords
    5. Return raw dicts with all metadata columns, sorted by score descending
    """
    cfg = cfg or _default_config
    db_path = store_path or cfg.lancedb_path
    coll_name = collection or cfg.vector_collection

    keywords = _extract_search_keywords(query)
    if not keywords:
        return []

    db = lancedb.connect(db_path)
    if coll_name not in db.table_names():
        logger.warning("Collection '%s' not found in %s", coll_name, db_path)
        return []

    table = db.open_table(coll_name)

    # Build filter for project scoping
    filter_expr = f"project_id = '{project_id}'" if project_id else None

    # Load filtered data to pandas for in-memory keyword matching
    if filter_expr:
        df = table.search().where(filter_expr, prefilter=True).limit(KEYWORD_SCAN_LIMIT).to_pandas()
    else:
        df = table.search().limit(KEYWORD_SCAN_LIMIT).to_pandas()

    # Detect possible truncation
    keyword_scan_truncated = len(df) >= KEYWORD_SCAN_LIMIT
    if keyword_scan_truncated:
        logger.warning(
            "keyword_search reached scan limit %d; results may be truncated for project_id=%s",
            KEYWORD_SCAN_LIMIT, project_id or "(all)",
        )

    if df.empty:
        return []

    # Drop embedding column to reduce memory (not needed for keyword matching)
    if "vector" in df.columns:
        df = df.drop(columns=["vector"])
    if "embedding" in df.columns:
        df = df.drop(columns=["embedding"])

    # Score each row by keyword hit count
    text_col = df["text"] if "text" in df.columns else None
    if text_col is None:
        return []

    total_keywords = len(keywords)
    scores: list[float] = []
    for text_val in text_col:
        if not isinstance(text_val, str):
            scores.append(0.0)
            continue
        hit_count = sum(1 for kw in keywords if kw in text_val)
        scores.append(hit_count / total_keywords)

    df = df.copy()
    df["_keyword_score"] = scores

    # Filter to rows with at least one keyword hit
    df = df[df["_keyword_score"] > 0.0]
    if df.empty:
        return []

    # Sort by score descending, take top_k
    df = df.sort_values("_keyword_score", ascending=False).head(top_k)

    # Convert to list of dicts
    results: list[dict] = []
    for _, row in df.iterrows():
        record = row.to_dict()
        record["_keyword_score"] = record.pop("_keyword_score", 0.0)
        results.append(record)

    return results
