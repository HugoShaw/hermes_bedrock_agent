"""
Business Evidence Selector for Stage 05.

Selects high-quality evidence chunks suitable for Business Semantic Graph extraction.
Excludes SQL dumps, code, config, and other non-business content.

Selection strategy:
  1. Include operation_doc and business_doc chunks (summary, section, small, operation)
  2. Include summary/section chunks from other docs if they contain business keywords
  3. Exclude JOURNAL_BASE SQL dump entirely
  4. Exclude chunk_type=sql unless clearly a business rule summary
  5. Exclude chunk_type=code and chunk_type=config
  6. Exclude binary metadata-only chunks (very short with no business terms)
  7. Deduplicate near-identical summary chunks
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# Business Keyword Sets
# ============================================================================

BUSINESS_KEYWORDS_JA = [
    "業務", "処理", "申請", "承認", "支払", "仕訳", "会計", "請求",
    "管理", "マスタ", "入力", "確認", "登録", "取消", "変更", "エラー",
    "権限", "ユーザー", "画面", "機能",
]

BUSINESS_KEYWORDS_ZH = [
    "业务", "流程", "申请", "审批", "付款", "支付", "会计", "凭证",
    "管理", "主数据", "画面", "功能", "规则", "权限", "用户", "操作",
    "资源", "角色", "系统", "添加", "修改", "删除", "查询", "检索",
]

BUSINESS_KEYWORDS_EN = [
    "business", "process", "workflow", "approval", "payment", "accounting",
    "journal", "function", "screen", "rule", "role", "user", "resource",
    "receiving", "request", "management",
]

ALL_BUSINESS_KEYWORDS = (
    BUSINESS_KEYWORDS_JA + BUSINESS_KEYWORDS_ZH + BUSINESS_KEYWORDS_EN
)

# Compiled pattern for fast matching
_KEYWORD_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in ALL_BUSINESS_KEYWORDS),
    re.IGNORECASE,
)

# ============================================================================
# Exclusion Patterns
# ============================================================================

# Files known to be SQL data dumps (exclude entirely)
SQL_DUMP_FILES = {
    "JOURNAL_BASE20180530.SQL",
    "insert_journal_base.txt",
    "insert_journal_base_before.txt",
}

# Patterns for detecting INSERT-heavy content
INSERT_PATTERN = re.compile(r"INSERT\s+INTO", re.IGNORECASE)

# Minimum text length for a chunk to be considered useful
MIN_CHUNK_TEXT_LENGTH = 30

# Minimum number of business keyword matches for marginal chunks
MIN_KEYWORD_MATCHES_FOR_MARGINAL = 2


# ============================================================================
# Selection Statistics
# ============================================================================

@dataclass
class SelectionStats:
    """Statistics from the evidence selection process."""
    total_evidence_chunks: int = 0
    selected_business_candidates: int = 0
    excluded_sql_dump: int = 0
    excluded_code_config: int = 0
    excluded_metadata_only: int = 0
    excluded_too_short: int = 0
    excluded_no_business_terms: int = 0
    excluded_insert_heavy: int = 0
    excluded_duplicate: int = 0
    selected_by_doc_type: dict[str, int] = field(default_factory=dict)
    selected_by_chunk_type: dict[str, int] = field(default_factory=dict)
    top_selected_sources: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evidence_chunks": self.total_evidence_chunks,
            "selected_business_candidates": self.selected_business_candidates,
            "excluded_sql_dump": self.excluded_sql_dump,
            "excluded_code_config": self.excluded_code_config,
            "excluded_metadata_only": self.excluded_metadata_only,
            "excluded_too_short": self.excluded_too_short,
            "excluded_no_business_terms": self.excluded_no_business_terms,
            "excluded_insert_heavy": self.excluded_insert_heavy,
            "excluded_duplicate": self.excluded_duplicate,
            "selected_by_doc_type": self.selected_by_doc_type,
            "selected_by_chunk_type": self.selected_by_chunk_type,
            "top_selected_sources": self.top_selected_sources,
        }


# ============================================================================
# Core Selection Logic
# ============================================================================

def _is_sql_dump_file(source_path: str) -> bool:
    """Check if the source file is a known SQL data dump."""
    filename = source_path.rsplit("/", 1)[-1] if "/" in source_path else source_path
    return filename in SQL_DUMP_FILES


def _is_insert_heavy(text: str, threshold: int = 5) -> bool:
    """Check if text contains many INSERT INTO statements (data dump indicator)."""
    matches = INSERT_PATTERN.findall(text)
    return len(matches) >= threshold


def _count_business_keywords(text: str) -> int:
    """Count the number of business keyword matches in text."""
    return len(_KEYWORD_PATTERN.findall(text))


def _compute_text_hash(text: str) -> str:
    """Compute a simple hash for deduplication."""
    import hashlib
    # Normalize whitespace for dedup
    normalized = re.sub(r"\s+", " ", text.strip())[:500]
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def select_business_evidence(
    evidence_chunks: list[dict[str, Any]],
    *,
    max_candidates: int = 2000,
    min_text_length: int = MIN_CHUNK_TEXT_LENGTH,
    dedup: bool = True,
) -> tuple[list[dict[str, Any]], SelectionStats]:
    """Select high-quality evidence chunks for business graph extraction.

    Args:
        evidence_chunks: All evidence chunks from Stage 04.
        max_candidates: Maximum number of candidate chunks to return.
        min_text_length: Minimum text length for a chunk to be selected.
        dedup: Whether to deduplicate near-identical chunks.

    Returns:
        (selected_chunks, stats)
    """
    stats = SelectionStats(total_evidence_chunks=len(evidence_chunks))

    selected: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for chunk in evidence_chunks:
        text = chunk.get("text", "")
        chunk_type = chunk.get("chunk_type", "")
        doc_type = chunk.get("doc_type", "")
        source_path = chunk.get("source_path", "")

        # --- Exclusion Rules ---

        # 1. Exclude SQL dump files entirely
        if _is_sql_dump_file(source_path):
            stats.excluded_sql_dump += 1
            continue

        # 2. Exclude code and config chunk types
        if chunk_type in ("code", "config"):
            stats.excluded_code_config += 1
            continue

        # 3. Exclude SQL chunk type (unless it's a short business rule)
        if chunk_type == "sql":
            # Allow short SQL chunks that contain business keywords
            if len(text) < 500 and _count_business_keywords(text) >= 2:
                pass  # Allow through
            else:
                stats.excluded_sql_dump += 1
                continue

        # 4. Exclude too-short chunks
        if len(text) < min_text_length:
            stats.excluded_too_short += 1
            continue

        # 5. Exclude INSERT-heavy content (data dumps)
        if _is_insert_heavy(text):
            stats.excluded_insert_heavy += 1
            continue

        # --- Inclusion Rules ---

        # High-priority: operation_doc and business_doc are always included
        if doc_type in ("operation_doc", "business_doc"):
            if chunk_type in ("summary", "section", "small", "operation"):
                keyword_count = _count_business_keywords(text)
                # Even business docs need at least 1 keyword or decent length
                if keyword_count >= 1 or len(text) > 100:
                    pass  # Include
                else:
                    stats.excluded_no_business_terms += 1
                    continue
            else:
                stats.excluded_no_business_terms += 1
                continue

        # Medium priority: summary/section from other doc types
        elif chunk_type in ("summary", "section"):
            keyword_count = _count_business_keywords(text)
            if keyword_count >= MIN_KEYWORD_MATCHES_FOR_MARGINAL:
                pass  # Include
            else:
                stats.excluded_no_business_terms += 1
                continue

        # Lower priority: small/operation chunks from other types
        elif chunk_type in ("small", "operation"):
            keyword_count = _count_business_keywords(text)
            if keyword_count >= 3:  # Higher threshold for marginal types
                pass  # Include
            else:
                stats.excluded_no_business_terms += 1
                continue

        else:
            # All other chunk types: require strong business signal
            keyword_count = _count_business_keywords(text)
            if keyword_count >= 3:
                pass  # Include
            else:
                stats.excluded_no_business_terms += 1
                continue

        # --- Deduplication ---
        if dedup:
            text_hash = _compute_text_hash(text)
            if text_hash in seen_hashes:
                stats.excluded_duplicate += 1
                continue
            seen_hashes.add(text_hash)

        # --- Accept ---
        selected.append(chunk)

        if len(selected) >= max_candidates:
            break

    # Compute stats
    stats.selected_business_candidates = len(selected)
    stats.selected_by_doc_type = dict(Counter(c["doc_type"] for c in selected))
    stats.selected_by_chunk_type = dict(Counter(c["chunk_type"] for c in selected))
    source_counter = Counter(c["source_path"] for c in selected)
    stats.top_selected_sources = source_counter.most_common(30)

    logger.info(
        f"Business evidence selection: {stats.selected_business_candidates}/{stats.total_evidence_chunks} "
        f"selected ({stats.excluded_sql_dump} SQL dump, {stats.excluded_code_config} code/config, "
        f"{stats.excluded_no_business_terms} no biz terms, {stats.excluded_duplicate} dedup)"
    )

    return selected, stats


def save_candidate_evidence(
    candidates: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Save selected candidate evidence to JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in candidates:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    logger.info(f"Saved {len(candidates)} candidate evidence chunks to {output_path}")
