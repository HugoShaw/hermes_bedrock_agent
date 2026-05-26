"""
Implementation Evidence Selector for Stage 06.

Selects high-quality evidence chunks suitable for Implementation Graph extraction.
Focuses on source code, SQL DDL, API docs, config, and system design content.
Excludes pure SQL data dumps (INSERT rows), binary metadata-only chunks,
and pure business-only content.

Selection strategy:
  1. Include source_code chunks (code, summary from Java/Python/TypeScript)
  2. Include database_doc chunks with DDL (CREATE TABLE, ALTER TABLE)
  3. Include config chunks
  4. Include API/interface doc chunks
  5. Include system design summaries referencing modules/services
  6. Exclude JOURNAL_BASE SQL dump file entirely
  7. Exclude INSERT-heavy data dump chunks
  8. Exclude binary metadata-only chunks
  9. Exclude pure business process chunks with no implementation terms
  10. Deduplicate near-identical chunks
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================================
# Implementation Keyword Sets
# ============================================================================

IMPL_KEYWORDS_JA = [
    "API", "テーブル", "項目", "カラム", "SQL", "バッチ", "ジョブ",
    "連携", "インターフェース", "外部システム", "サービス", "モジュール",
    "画面ID", "機能ID", "エラーコード", "設定", "ファイル", "DB",
    "データベース", "クラス", "メソッド",
]

IMPL_KEYWORDS_ZH = [
    "接口", "表", "字段", "列", "SQL", "批处理", "任务", "作业",
    "外部系统", "服务", "模块", "配置", "文件", "数据库", "错误码",
    "画面ID", "功能ID", "类", "方法", "操作手册", "系统管理",
]

IMPL_KEYWORDS_EN = [
    "api", "endpoint", "table", "column", "field", "sql", "batch",
    "job", "service", "module", "class", "method", "function", "config",
    "database", "schema", "error code", "interface", "external system",
    "file", "dao", "action", "model", "entity", "repository", "import",
    "package", "create table", "alter table", "drop table", "select",
    "insert into", "update", "delete from", "varchar", "number",
    "hibernate", "spring", "struts", "bean", "controller", "servlet",
]

ALL_IMPL_KEYWORDS = IMPL_KEYWORDS_JA + IMPL_KEYWORDS_ZH + IMPL_KEYWORDS_EN

# Compiled pattern for fast matching
_KEYWORD_PATTERN = re.compile(
    "|".join(re.escape(kw) for kw in ALL_IMPL_KEYWORDS),
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

# Patterns for detecting INSERT-heavy content (data dumps)
INSERT_PATTERN = re.compile(r"INSERT\s+INTO", re.IGNORECASE)

# DDL pattern (signals useful schema info)
DDL_PATTERN = re.compile(
    r"(CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|CREATE\s+(UNIQUE\s+)?INDEX)",
    re.IGNORECASE,
)

# Minimum text length for a chunk to be considered useful
MIN_CHUNK_TEXT_LENGTH = 20

# Minimum number of implementation keywords for marginal chunks
MIN_KEYWORD_MATCHES_FOR_MARGINAL = 1


# ============================================================================
# Selection Statistics
# ============================================================================

@dataclass
class ImplSelectionStats:
    """Statistics from the implementation evidence selection process."""
    total_evidence_chunks: int = 0
    selected_impl_candidates: int = 0
    excluded_sql_dump: int = 0
    excluded_insert_heavy: int = 0
    excluded_business_only: int = 0
    excluded_metadata_only: int = 0
    excluded_too_short: int = 0
    excluded_no_impl_terms: int = 0
    excluded_duplicate: int = 0
    selected_by_doc_type: dict[str, int] = field(default_factory=dict)
    selected_by_chunk_type: dict[str, int] = field(default_factory=dict)
    top_selected_sources: list[tuple[str, int]] = field(default_factory=list)
    top_excluded_sources: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_evidence_chunks": self.total_evidence_chunks,
            "selected_impl_candidates": self.selected_impl_candidates,
            "excluded_sql_dump": self.excluded_sql_dump,
            "excluded_insert_heavy": self.excluded_insert_heavy,
            "excluded_business_only": self.excluded_business_only,
            "excluded_metadata_only": self.excluded_metadata_only,
            "excluded_too_short": self.excluded_too_short,
            "excluded_no_impl_terms": self.excluded_no_impl_terms,
            "excluded_duplicate": self.excluded_duplicate,
            "selected_by_doc_type": self.selected_by_doc_type,
            "selected_by_chunk_type": self.selected_by_chunk_type,
            "top_selected_sources": self.top_selected_sources,
            "top_excluded_sources": self.top_excluded_sources,
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


def _has_ddl(text: str) -> bool:
    """Check if text contains DDL statements (CREATE TABLE, ALTER TABLE, etc.)."""
    return bool(DDL_PATTERN.search(text))


def _count_impl_keywords(text: str) -> int:
    """Count the number of implementation keyword matches in text."""
    return len(_KEYWORD_PATTERN.findall(text))


def _compute_text_hash(text: str) -> str:
    """Compute a simple hash for deduplication."""
    normalized = re.sub(r"\s+", " ", text.strip())[:500]
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()


def select_implementation_evidence(
    evidence_chunks: list[dict[str, Any]],
    *,
    max_candidates: int = 5000,
    min_text_length: int = MIN_CHUNK_TEXT_LENGTH,
    dedup: bool = True,
) -> tuple[list[dict[str, Any]], ImplSelectionStats]:
    """Select high-quality evidence chunks for implementation graph extraction.

    Args:
        evidence_chunks: All evidence chunks from Stage 04.
        max_candidates: Maximum number of candidate chunks to return.
        min_text_length: Minimum text length for a chunk to be selected.
        dedup: Whether to deduplicate near-identical chunks.

    Returns:
        (selected_chunks, stats)
    """
    stats = ImplSelectionStats(total_evidence_chunks=len(evidence_chunks))

    selected: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    excluded_sources: Counter = Counter()

    for chunk in evidence_chunks:
        text = chunk.get("text", "")
        chunk_type = chunk.get("chunk_type", "")
        doc_type = chunk.get("doc_type", "")
        source_path = chunk.get("source_path", "")

        # --- Hard Exclusion Rules ---

        # 1. Exclude SQL dump files entirely
        if _is_sql_dump_file(source_path):
            stats.excluded_sql_dump += 1
            excluded_sources[source_path] += 1
            continue

        # 2. Exclude too-short chunks
        if len(text) < min_text_length:
            stats.excluded_too_short += 1
            continue

        # 3. Exclude INSERT-heavy data dump content
        if _is_insert_heavy(text):
            stats.excluded_insert_heavy += 1
            excluded_sources[source_path] += 1
            continue

        # --- Selection by Source Type ---

        # Source code is always high-priority for implementation
        if doc_type == "source_code":
            if chunk_type in ("code", "summary", "small", "section"):
                # Almost all source code chunks are useful
                pass  # Accept
            else:
                # Check for keywords
                if _count_impl_keywords(text) >= 1:
                    pass  # Accept
                else:
                    stats.excluded_no_impl_terms += 1
                    continue

        # Database docs: only DDL or structural content
        elif doc_type == "database_doc":
            if _has_ddl(text):
                pass  # Accept DDL chunks
            elif chunk_type == "summary" and _count_impl_keywords(text) >= 2:
                # Accept summaries with enough impl keywords
                # But exclude those that are just INSERT data
                if "INSERT" in text[:50].upper() and not _has_ddl(text):
                    stats.excluded_insert_heavy += 1
                    excluded_sources[source_path] += 1
                    continue
                pass  # Accept
            elif chunk_type == "sql" and not _is_insert_heavy(text, threshold=2):
                # Accept SQL chunks that are not INSERT-heavy
                if _has_ddl(text) or _count_impl_keywords(text) >= 2:
                    pass  # Accept
                else:
                    stats.excluded_no_impl_terms += 1
                    continue
            else:
                stats.excluded_no_impl_terms += 1
                continue

        # Config docs
        elif doc_type == "config":
            if chunk_type in ("config", "summary", "small", "section"):
                pass  # Accept
            else:
                if _count_impl_keywords(text) >= 1:
                    pass
                else:
                    stats.excluded_no_impl_terms += 1
                    continue

        # Operation docs: only if they describe system/deployment operations
        elif doc_type == "operation_doc":
            kw_count = _count_impl_keywords(text)
            if kw_count >= 2:
                pass  # Accept system-related operation docs
            else:
                stats.excluded_business_only += 1
                continue

        # Unknown/other: require strong implementation signal
        else:
            kw_count = _count_impl_keywords(text)
            if kw_count >= 2:
                pass  # Accept
            else:
                stats.excluded_no_impl_terms += 1
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
    stats.selected_impl_candidates = len(selected)
    stats.selected_by_doc_type = dict(Counter(c["doc_type"] for c in selected))
    stats.selected_by_chunk_type = dict(Counter(c["chunk_type"] for c in selected))
    source_counter = Counter(c["source_path"] for c in selected)
    stats.top_selected_sources = source_counter.most_common(30)
    stats.top_excluded_sources = excluded_sources.most_common(20)

    logger.info(
        f"Implementation evidence selection: {stats.selected_impl_candidates}/{stats.total_evidence_chunks} "
        f"selected ({stats.excluded_sql_dump} SQL dump, {stats.excluded_insert_heavy} INSERT-heavy, "
        f"{stats.excluded_no_impl_terms} no impl terms, {stats.excluded_duplicate} dedup)"
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
