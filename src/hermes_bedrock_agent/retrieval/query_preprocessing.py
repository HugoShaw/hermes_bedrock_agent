"""Query preprocessing: normalization, intent detection, multi-query rewrite."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


def normalize_query(query: str) -> str:
    """Normalize user query for better matching.

    - Strip leading/trailing whitespace
    - Normalize Unicode (NFKC for Japanese)
    - Collapse multiple spaces
    - Convert full-width alphanumeric to half-width
    """
    query = query.strip()
    query = unicodedata.normalize("NFKC", query)
    query = re.sub(r"\s+", " ", query)
    return query


INTENT_KEYWORDS: dict[str, list[str]] = {
    "mapping": ["マッピング", "mapping", "変換", "transform", "対応表", "対応"],
    "flowchart": ["フロー", "flow", "シーケンス", "sequence", "手順", "処理順序", "呼出順序"],
    "api": ["API", "api", "endpoint", "呼出", "インターフェース", "interface", "リクエスト", "レスポンス"],
    "field": ["フィールド", "field", "項目", "カラム", "column", "データ項目"],
    "rule": ["ルール", "rule", "条件", "condition", "ビジネスルール", "判定", "分岐"],
    "overview": ["概要", "overview", "全体", "summary", "一覧", "構成"],
}

INTENT_CHUNK_TYPE_HINTS: dict[str, list[str]] = {
    "mapping": ["mapping_table", "cross_sheet_summary"],
    "flowchart": ["flowchart", "overview"],
    "api": ["api_spec", "mapping_table"],
    "field": ["data_condition", "mapping_table"],
    "rule": ["business_rule", "data_condition"],
    "overview": ["overview", "cross_sheet_summary"],
}


@dataclass
class QueryIntent:
    label: str  # mapping|flowchart|api|field|rule|overview
    confidence: float  # 0.0 to 1.0
    chunk_type_hints: list[str] = field(default_factory=list)


def detect_intent(query: str) -> QueryIntent:
    """Lightweight keyword-based intent detection. No LLM calls."""
    query_lower = query.lower()
    scores: dict[str, int] = {}

    for intent, keywords in INTENT_KEYWORDS.items():
        count = 0
        for kw in keywords:
            if kw.lower() in query_lower or kw in query:
                count += 1
        if count > 0:
            scores[intent] = count

    if not scores:
        return QueryIntent(label="overview", confidence=0.1, chunk_type_hints=[])

    best_intent = max(scores, key=lambda k: scores[k])
    max_possible = len(INTENT_KEYWORDS[best_intent])
    confidence = min(1.0, scores[best_intent] / max(1, max_possible) + 0.3)

    return QueryIntent(
        label=best_intent,
        confidence=round(confidence, 2),
        chunk_type_hints=INTENT_CHUNK_TYPE_HINTS.get(best_intent, []),
    )


@dataclass
class RewrittenQueries:
    original: str
    normalized: str
    intent: QueryIntent
    business_query: str
    technical_query: str
    keyword_query: str


_BUSINESS_EXPANSIONS: dict[str, str] = {
    "mapping": "データ変換 対応関係 入出力マッピング",
    "flowchart": "処理フロー 業務手順 シーケンス図",
    "api": "API連携 インターフェース仕様 呼出先",
    "field": "データ項目 フィールド定義 カラム仕様",
    "rule": "ビジネスルール 判定条件 分岐ロジック",
    "overview": "システム概要 全体構成 アーキテクチャ",
}

_TECHNICAL_EXPANSIONS: dict[str, str] = {
    "mapping": "transform mapping table column conversion",
    "flowchart": "sequence flow diagram process step",
    "api": "endpoint request response interface call",
    "field": "field column schema data type",
    "rule": "condition branch logic validation check",
    "overview": "architecture module system component",
}


def _extract_keywords(query: str) -> str:
    """Extract raw keywords from query for lexical matching."""
    # Extract CJK sequences (kanji, katakana)
    cjk_pattern = re.compile(r"[　-鿿豈-﫿]+")
    # Extract Latin identifiers (camelCase, snake_case, UPPER)
    latin_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

    tokens: list[str] = []
    tokens.extend(cjk_pattern.findall(query))
    tokens.extend(w for w in latin_pattern.findall(query) if len(w) > 1)

    return " ".join(tokens)


def rewrite_queries(query: str, intent: QueryIntent) -> RewrittenQueries:
    """Generate multiple query variants for hybrid retrieval.

    Rule-based (no LLM). Uses intent to select expansion terms.
    """
    normalized = normalize_query(query)
    keyword_query = _extract_keywords(normalized)

    business_expansion = _BUSINESS_EXPANSIONS.get(intent.label, "")
    technical_expansion = _TECHNICAL_EXPANSIONS.get(intent.label, "")

    business_query = f"{normalized} {business_expansion}".strip()
    technical_query = f"{normalized} {technical_expansion}".strip()

    return RewrittenQueries(
        original=query,
        normalized=normalized,
        intent=intent,
        business_query=business_query,
        technical_query=technical_query,
        keyword_query=keyword_query if keyword_query else normalized,
    )
