"""Intent router — classifies user questions into retrieval strategies.

Determines whether to use text search, graph traversal, or hybrid approach
based on question patterns and keywords.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class IntentType(str, Enum):
    """Classification of user question intent."""

    DEFINITION = "definition"
    PROCEDURE = "procedure"
    IMPACT_ANALYSIS = "impact_analysis"
    DEPENDENCY = "dependency"
    EVIDENCE_LOOKUP = "evidence_lookup"
    GENERAL = "general"


class RetrievalStrategy(str, Enum):
    """Retrieval approach to use."""

    TEXT = "text"
    GRAPH = "graph"
    HYBRID = "hybrid"
    KB_OPTIONAL = "kb_optional"


@dataclass
class IntentClassification:
    """Result of intent classification."""

    intent: IntentType
    strategy: RetrievalStrategy
    confidence: float = 0.0
    reasoning: str = ""
    keywords_matched: list[str] = field(default_factory=list)


# Pattern definitions: (compiled_regex, intent_type, retrieval_strategy)
_INTENT_PATTERNS: list[tuple[re.Pattern, IntentType, RetrievalStrategy]] = [
    # Impact analysis patterns (check BEFORE definition to avoid "what is the impact" → definition)
    (re.compile(r"(影響|impact|affect|変更.*影響|修改.*影响|change.*affect|what\s+happens\s+if)", re.IGNORECASE),
     IntentType.IMPACT_ANALYSIS, RetrievalStrategy.GRAPH),

    # Dependency patterns
    (re.compile(r"(依存|depends?\s+on|呼び出|calls?|接続|connects?|関連|depends|关联|调用|引用|references?)", re.IGNORECASE),
     IntentType.DEPENDENCY, RetrievalStrategy.GRAPH),

    # Procedure / how-to patterns
    (re.compile(r"(手順|フロー|流程|ステップ|how\s+to|procedure|操作方法|怎么做|步骤|process\s+of)", re.IGNORECASE),
     IntentType.PROCEDURE, RetrievalStrategy.HYBRID),

    # Evidence / lookup patterns
    (re.compile(r"(根拠|evidence|ソース|source|どこに書|where.*documented|哪里|记录在|出典)", re.IGNORECASE),
     IntentType.EVIDENCE_LOOKUP, RetrievalStrategy.TEXT),

    # Definition patterns (checked last since "what is" is generic)
    (re.compile(r"(とは|って何|what\s+is|define|定義|概要|説明して|是什么|什么是)", re.IGNORECASE),
     IntentType.DEFINITION, RetrievalStrategy.HYBRID),
]


def classify_intent(
    question: str,
    *,
    default_strategy: RetrievalStrategy = RetrievalStrategy.HYBRID,
) -> IntentClassification:
    """Classify a user question into an intent and retrieval strategy.

    Uses keyword/pattern matching for fast, deterministic classification.
    No LLM call required.

    Args:
        question: The user's question text.
        default_strategy: Strategy to use when no pattern matches.

    Returns:
        IntentClassification with intent type and recommended strategy.
    """
    if not question or not question.strip():
        return IntentClassification(
            intent=IntentType.GENERAL,
            strategy=default_strategy,
            confidence=0.0,
            reasoning="Empty question",
        )

    question_lower = question.lower().strip()
    matched_keywords: list[str] = []
    best_match: Optional[tuple[IntentType, RetrievalStrategy]] = None
    best_confidence = 0.0

    for pattern, intent_type, strategy in _INTENT_PATTERNS:
        matches = pattern.findall(question_lower)
        if matches:
            # Score based on match count and position
            confidence = min(0.6 + 0.1 * len(matches), 0.95)
            if confidence > best_confidence:
                best_confidence = confidence
                best_match = (intent_type, strategy)
                matched_keywords = [str(m) for m in matches[:5]]

    if best_match:
        return IntentClassification(
            intent=best_match[0],
            strategy=best_match[1],
            confidence=best_confidence,
            reasoning=f"Matched patterns: {matched_keywords}",
            keywords_matched=matched_keywords,
        )

    # Default: hybrid search for general questions
    return IntentClassification(
        intent=IntentType.GENERAL,
        strategy=default_strategy,
        confidence=0.3,
        reasoning="No specific pattern matched, using default hybrid strategy",
    )
