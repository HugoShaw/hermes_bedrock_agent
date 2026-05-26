"""Query Entity Extractor for Graph Retrieval.

Extracts entity mentions from natural language queries (Chinese/Japanese/English)
and normalizes them to graph-searchable terms.

Strategy:
1. Rule-based extraction (regex patterns for technical names, table names, etc.)
2. Alias dictionary lookup (built from entities.jsonl)
3. N-gram matching against known entity names
4. Optional LLM fallback (disabled by default)

Phase 10A implementation — no heavy external dependencies (no jieba/MeCab).
Uses regex + Aho-Corasick-style prefix matching against entity index.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ─── Simplified/Traditional Chinese normalization (common chars only) ─────────
# Covers common characters found in enterprise/IT/financial domain
_SIMPLIFIED_TO_TRADITIONAL = {
    "请": "請", "认": "認", "证": "證", "设": "設", "计": "計",
    "发": "發", "关": "關", "系": "係", "统": "統", "应": "應",
    "处": "處", "理": "理", "报": "報", "单": "單", "导": "導",
    "进": "進", "这": "這", "对": "對", "账": "帳", "结": "結",
    "构": "構", "义": "義", "际": "際", "区": "區", "库": "庫",
    "号": "號", "类": "類", "开": "開", "运": "運", "业": "業",
    "务": "務", "产": "產", "询": "詢", "检": "檢", "记": "記",
    "录": "錄", "权": "權", "审": "審", "核": "核", "付": "付",
    "款": "款", "收": "收", "转": "轉", "汇": "匯", "总": "總",
}
_TRADITIONAL_TO_SIMPLIFIED = {v: k for k, v in _SIMPLIFIED_TO_TRADITIONAL.items()}


def _normalize_cjk_variants(text: str) -> list[str]:
    """Generate simplified and traditional Chinese variants of the text.

    Returns list of unique variants (always includes original).
    """
    variants = {text}

    # Try simplified → traditional
    trad = text
    for s, t in _SIMPLIFIED_TO_TRADITIONAL.items():
        trad = trad.replace(s, t)
    if trad != text:
        variants.add(trad)

    # Try traditional → simplified
    simp = text
    for t, s in _TRADITIONAL_TO_SIMPLIFIED.items():
        simp = simp.replace(t, s)
    if simp != text:
        variants.add(simp)

    return list(variants)


class QueryLanguage(str, Enum):
    """Detected query language."""
    ZH = "zh"
    JA = "ja"
    EN = "en"
    MIXED = "mixed"
    AUTO = "auto"


@dataclass
class EntityMention:
    """An entity mention extracted from the query."""
    surface_form: str  # As it appears in the query
    normalized: str  # Lowercased/normalized form
    source: str  # How it was extracted: "regex", "alias", "ngram", "llm"
    confidence: float = 1.0
    entity_type: Optional[str] = None  # If known from index
    matched_entity_name: Optional[str] = None  # The actual entity name matched


@dataclass
class QueryExtractionResult:
    """Result of query entity extraction."""
    original_question: str
    detected_language: QueryLanguage
    entity_mentions: list[EntityMention] = field(default_factory=list)
    normalized_terms: list[str] = field(default_factory=list)
    expanded_terms: list[str] = field(default_factory=list)
    graph_search_terms: list[str] = field(default_factory=list)


class EntityIndex:
    """In-memory index of known entities for fast lookup.

    Built from entities.jsonl — maps various name forms to canonical names.
    """

    def __init__(self):
        self._by_name: dict[str, dict] = {}  # lowercase name → entity info
        self._by_canonical: dict[str, dict] = {}
        self._aliases: dict[str, str] = {}  # alias → canonical_name
        self._names_sorted: list[str] = []  # For prefix matching
        self._cjk_names: list[tuple[str, str]] = []  # (name, canonical) for CJK
        self._cjk_descriptions: list[tuple[str, str, dict]] = []  # (description, canonical, info)

    def load_from_jsonl(self, path: str | Path) -> int:
        """Load entities from JSONL file.

        Returns:
            Number of entities loaded.
        """
        path = Path(path)
        count = 0

        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                entity = json.loads(line)
                self._index_entity(entity)
                count += 1

        # Sort names for binary search / prefix matching
        self._names_sorted = sorted(self._by_name.keys())
        return count

    def load_i18n_enrichment(self, path: str | Path) -> int:
        """Load i18n enrichment data and merge into the index.

        Expected JSONL format: i18n_entities_enriched.jsonl from Phase 10B.
        Merges display_name_*, aliases_* into existing index entries.

        Returns:
            Number of entities enriched.
        """
        path = Path(path)
        count = 0

        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                enrichment = json.loads(line)
                canonical = enrichment.get("canonical_name", "").lower()
                if not canonical:
                    continue

                # Merge into existing entity
                info = self._by_canonical.get(canonical) or self._by_name.get(canonical)
                if not info:
                    continue

                # Index all new i18n aliases
                for lang in ("zh", "en", "ja"):
                    for alias in enrichment.get(f"aliases_{lang}", []) or []:
                        alias_lower = alias.strip().lower()
                        if alias_lower and alias_lower != canonical:
                            self._aliases[alias_lower] = canonical
                            if _has_cjk(alias):
                                self._cjk_names.append((alias_lower, canonical))

                    # Index display names
                    dname = enrichment.get(f"display_name_{lang}", "") or ""
                    dname_lower = dname.strip().lower()
                    if dname_lower and dname_lower != canonical:
                        self._aliases[dname_lower] = canonical
                        if _has_cjk(dname):
                            self._cjk_names.append((dname_lower, canonical))

                count += 1

        return count

    def load_from_neptune(self, client, run_id: str, dataset: str) -> int:
        """Load entity names directly from Neptune.

        Returns:
            Number of entities loaded.
        """
        result = client.execute_query(
            "MATCH (n {run_id: $run_id, dataset: $dataset}) "
            "RETURN n.name AS name, n.canonical_name AS canonical_name, "
            "n.entity_type AS entity_type, n.entity_id AS entity_id "
            "LIMIT 10000",
            parameters={"run_id": run_id, "dataset": dataset},
        )
        rows = result.get("results", [])
        for row in rows:
            self._index_entity({
                "name": row.get("name", ""),
                "canonical_name": row.get("canonical_name", ""),
                "entity_type": row.get("entity_type", ""),
                "entity_id": row.get("entity_id", ""),
                "aliases": [],
            })

        self._names_sorted = sorted(self._by_name.keys())
        return len(rows)

    def _index_entity(self, entity: dict) -> None:
        """Index a single entity's name forms."""
        name = entity.get("name", "").strip()
        canonical = entity.get("canonical_name", "").strip() or name
        etype = entity.get("entity_type", "")
        eid = entity.get("entity_id", "")

        if not name:
            return

        info = {"name": name, "canonical_name": canonical,
                "entity_type": etype, "entity_id": eid}

        # Index by lowercase name
        name_lower = name.lower()
        self._by_name[name_lower] = info

        # Index by canonical name
        canonical_lower = canonical.lower()
        if canonical_lower != name_lower:
            self._by_canonical[canonical_lower] = info

        # Index aliases
        for alias in entity.get("aliases", []) or []:
            alias_lower = alias.strip().lower()
            if alias_lower:
                self._aliases[alias_lower] = canonical_lower

        # Index i18n aliases (Phase 10B)
        for lang in ("zh", "en", "ja"):
            for alias in entity.get(f"aliases_{lang}", []) or []:
                alias_lower = alias.strip().lower()
                if alias_lower and alias_lower != canonical_lower:
                    self._aliases[alias_lower] = canonical_lower
                    # Also add CJK aliases to cjk_names for substring matching
                    if _has_cjk(alias):
                        self._cjk_names.append((alias_lower, canonical_lower))

        # Index i18n display names (Phase 10B)
        for lang in ("zh", "en", "ja"):
            dname = entity.get(f"display_name_{lang}", "") or ""
            dname_lower = dname.strip().lower()
            if dname_lower and dname_lower != name_lower and dname_lower != canonical_lower:
                self._aliases[dname_lower] = canonical_lower
                if _has_cjk(dname):
                    self._cjk_names.append((dname_lower, canonical_lower))

        # Track CJK names separately for substring matching
        if _has_cjk(name):
            self._cjk_names.append((name_lower, canonical_lower))

        # Also track CJK content in description for semantic matching
        desc = entity.get("description", "") or ""
        if desc and _has_cjk(desc):
            self._cjk_descriptions.append((desc.lower(), canonical_lower, info))

        # Also index without underscores/hyphens for fuzzy matching
        stripped = name_lower.replace("_", "").replace("-", "").replace(".", "")
        if stripped != name_lower and len(stripped) >= 3:
            self._by_name[stripped] = info

    def lookup(self, term: str) -> Optional[dict]:
        """Exact lookup by name (case-insensitive)."""
        term_lower = term.lower().strip()
        return (
            self._by_name.get(term_lower)
            or self._by_canonical.get(term_lower)
            or self._by_name.get(self._aliases.get(term_lower, ""))
        )

    def prefix_match(self, prefix: str, max_results: int = 5) -> list[dict]:
        """Find entities whose name starts with the given prefix."""
        prefix_lower = prefix.lower()
        results = []
        for name in self._names_sorted:
            if name.startswith(prefix_lower):
                results.append(self._by_name[name])
                if len(results) >= max_results:
                    break
        return results

    def substring_match(self, substring: str, max_results: int = 10) -> list[dict]:
        """Find entities whose name contains the substring."""
        sub_lower = substring.lower()
        if len(sub_lower) < 2:
            return []

        results = []
        for name, info in self._by_name.items():
            if sub_lower in name:
                results.append(info)
                if len(results) >= max_results:
                    break
        return results

    def cjk_match(self, text: str, min_len: int = 2, max_results: int = 10) -> list[dict]:
        """Find CJK entities mentioned in the text via substring matching."""
        text_lower = text.lower()
        # Also generate simplified/traditional variants of the input
        text_variants = _normalize_cjk_variants(text_lower)
        results = []
        seen = set()

        # Match CJK entity names that appear in any variant of the text
        for name, canonical in self._cjk_names:
            if len(name) >= min_len:
                if any(name in tv for tv in text_variants):
                    if canonical not in seen:
                        seen.add(canonical)
                        info = (
                            self._by_name.get(name)
                            or self._by_canonical.get(canonical)
                            or self._by_name.get(canonical)
                        )
                        if info:
                            results.append(info)
                            if len(results) >= max_results:
                                break

        # Also check CJK aliases with variants
        if len(results) < max_results:
            for alias, canonical in self._aliases.items():
                if _has_cjk(alias) and len(alias) >= min_len:
                    if any(alias in tv for tv in text_variants):
                        if canonical not in seen:
                            seen.add(canonical)
                            info = (
                                self._by_name.get(canonical)
                                or self._by_canonical.get(canonical)
                                or self._by_name.get(alias)
                            )
                            if info:
                                results.append(info)
                                if len(results) >= max_results:
                                    break

        # If few results, also check CJK descriptions (e.g., "仕訳基礎" in description)
        if len(results) < max_results:
            # Extract CJK substrings from query (4+ chars for description matching)
            cjk_segments = re.findall(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]{2,}', text_lower)
            for segment in cjk_segments:
                if len(segment) < min_len:
                    continue
                # Also try simplified/traditional variants of the segment
                seg_variants = _normalize_cjk_variants(segment)
                for desc, canonical, info in self._cjk_descriptions:
                    if canonical not in seen:
                        if any(sv in desc for sv in seg_variants):
                            seen.add(canonical)
                            results.append(info)
                            if len(results) >= max_results:
                                break
                if len(results) >= max_results:
                    break

        return results

    @property
    def size(self) -> int:
        return len(self._by_name)


class QueryEntityExtractor:
    """Extracts entity mentions from natural language queries.

    Pipeline:
    1. Detect language
    2. Extract technical names (regex)
    3. Match against entity index (alias lookup, substring match)
    4. Normalize and deduplicate
    5. Build final graph search terms
    """

    # Regex patterns for extracting technical entity mentions
    _PATTERNS = {
        # UPPERCASE_TABLE_NAME or UPPERCASE_WITH_NUMBERS
        "uppercase_identifier": re.compile(r'\b([A-Z][A-Z0-9_]{2,})\b'),
        # snake_case identifiers (3+ chars)
        "snake_case": re.compile(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b'),
        # CamelCase identifiers (single hump included: Murata, Oracle)
        "camel_case": re.compile(r'\b([A-Z][a-z]{2,}(?:[A-Z][a-z]+)*)\b'),
        # File names with extensions
        "filename": re.compile(r'\b([\w\-]+\.(?:java|py|xml|csv|sql|json|yaml|properties|jsp|html|js))\b', re.IGNORECASE),
        # Dotted identifiers (package.Class)
        "dotted": re.compile(r'\b([a-zA-Z][\w]*(?:\.[a-zA-Z][\w]*)+)\b'),
        # Table/column names with dots (schema.table)
        "schema_table": re.compile(r'\b([A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*)\b'),
        # Adjacent word+word without space as compound entity (e.g. "Murata PR" → try concatenation)
        "compound_name": re.compile(r'\b([A-Z][a-z]+\s+[A-Z]{2,})\b'),
    }

    # CJK character ranges
    _CJK_RANGE = re.compile(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff\uff66-\uff9f]+')

    def __init__(self, entity_index: Optional[EntityIndex] = None):
        """Initialize with optional pre-built entity index.

        Args:
            entity_index: Pre-built EntityIndex. If None, extraction will
                         rely solely on regex patterns.
        """
        self._index = entity_index

    @property
    def has_index(self) -> bool:
        return self._index is not None and self._index.size > 0

    def extract(
        self,
        question: str,
        lang: QueryLanguage = QueryLanguage.AUTO,
    ) -> QueryExtractionResult:
        """Extract entity mentions from a question.

        Args:
            question: User's natural language question.
            lang: Language hint (auto-detect if AUTO).

        Returns:
            QueryExtractionResult with extracted and normalized terms.
        """
        # Step 1: Detect language
        detected = self._detect_language(question) if lang == QueryLanguage.AUTO else lang

        # Step 2: Extract mentions via regex
        mentions = self._extract_regex(question)

        # Step 3: Extract CJK entity mentions via index
        if self._index and _has_cjk(question):
            cjk_mentions = self._extract_cjk_from_index(question)
            mentions.extend(cjk_mentions)

        # Step 4: Match against entity index for non-CJK terms
        if self._index:
            index_mentions = self._match_against_index(question, mentions)
            mentions.extend(index_mentions)

        # Step 5: Deduplicate mentions
        mentions = self._deduplicate(mentions)

        # Step 6: Normalize terms
        normalized = list(dict.fromkeys(m.normalized for m in mentions))

        # Step 7: Expand aliases
        expanded = self._expand_aliases(normalized)

        # Step 8: Build final graph search terms
        graph_terms = self._build_graph_terms(normalized, expanded)

        return QueryExtractionResult(
            original_question=question,
            detected_language=detected,
            entity_mentions=mentions,
            normalized_terms=normalized,
            expanded_terms=expanded,
            graph_search_terms=graph_terms,
        )

    def _detect_language(self, text: str) -> QueryLanguage:
        """Detect primary language of the query."""
        cjk_count = len(self._CJK_RANGE.findall(text))
        ascii_words = len(re.findall(r'[a-zA-Z]+', text))

        # Check for Japanese-specific characters (hiragana/katakana)
        has_jp = bool(re.search(r'[\u3040-\u309f\u30a0-\u30ff]', text))
        has_zh = bool(re.search(r'[\u4e00-\u9fff]', text))

        if has_jp:
            if ascii_words > cjk_count:
                return QueryLanguage.MIXED
            return QueryLanguage.JA
        elif has_zh:
            if ascii_words > cjk_count:
                return QueryLanguage.MIXED
            return QueryLanguage.ZH
        elif ascii_words > 0:
            return QueryLanguage.EN
        return QueryLanguage.MIXED

    def _extract_regex(self, text: str) -> list[EntityMention]:
        """Extract technical names via regex patterns."""
        mentions = []
        seen_surfaces = set()

        for pattern_name, pattern in self._PATTERNS.items():
            for match in pattern.finditer(text):
                surface = match.group(1)
                if surface.lower() in seen_surfaces:
                    continue
                if len(surface) < 3:
                    continue
                # Skip common words
                if surface.lower() in _STOPWORDS:
                    continue

                seen_surfaces.add(surface.lower())
                normalized = surface.lower().strip()

                # For compound names ("Murata PR"), also try concatenated form
                if pattern_name == "compound_name":
                    concat = re.sub(r'\s+', '', surface).lower()
                    if concat not in seen_surfaces:
                        seen_surfaces.add(concat)
                        normalized = concat

                mention = EntityMention(
                    surface_form=surface,
                    normalized=normalized,
                    source=f"regex:{pattern_name}",
                    confidence=0.9 if pattern_name in ("uppercase_identifier", "filename") else 0.7,
                )

                # Check if it matches a known entity
                if self._index:
                    info = self._index.lookup(normalized)
                    if info:
                        mention.confidence = 1.0
                        mention.entity_type = info.get("entity_type")
                        mention.matched_entity_name = info.get("name")
                    elif pattern_name == "compound_name":
                        # Try concat form
                        concat = re.sub(r'\s+', '', surface).lower()
                        info = self._index.lookup(concat)
                        if info:
                            mention.confidence = 1.0
                            mention.normalized = concat
                            mention.entity_type = info.get("entity_type")
                            mention.matched_entity_name = info.get("name")

                mentions.append(mention)

        return mentions

    def _extract_cjk_from_index(self, text: str) -> list[EntityMention]:
        """Extract CJK entity mentions by matching against index."""
        if not self._index:
            return []

        matches = self._index.cjk_match(text, min_len=2, max_results=10)
        mentions = []

        for info in matches:
            name = info.get("name", "")
            mentions.append(EntityMention(
                surface_form=name,
                normalized=name.lower(),
                source="index:cjk_match",
                confidence=0.95,
                entity_type=info.get("entity_type"),
                matched_entity_name=name,
            ))

        return mentions

    def _match_against_index(
        self, question: str, existing_mentions: list[EntityMention]
    ) -> list[EntityMention]:
        """Try to match existing mentions against the entity index."""
        if not self._index:
            return []

        additional = []
        existing_normalized = {m.normalized for m in existing_mentions}

        for mention in existing_mentions:
            # Try prefix match for partial names
            if mention.matched_entity_name is None:
                results = self._index.prefix_match(mention.normalized, max_results=3)
                for info in results:
                    canon = info.get("canonical_name", "").lower()
                    if canon and canon not in existing_normalized:
                        existing_normalized.add(canon)
                        additional.append(EntityMention(
                            surface_form=info.get("name", ""),
                            normalized=canon,
                            source="index:prefix",
                            confidence=0.8,
                            entity_type=info.get("entity_type"),
                            matched_entity_name=info.get("name"),
                        ))

        return additional

    def _deduplicate(self, mentions: list[EntityMention]) -> list[EntityMention]:
        """Deduplicate mentions, keeping highest confidence."""
        by_normalized: dict[str, EntityMention] = {}

        for m in mentions:
            key = m.normalized
            if key not in by_normalized or m.confidence > by_normalized[key].confidence:
                by_normalized[key] = m

        # Sort by confidence desc
        return sorted(by_normalized.values(), key=lambda x: -x.confidence)

    def _expand_aliases(self, terms: list[str]) -> list[str]:
        """Expand terms with known aliases."""
        if not self._index:
            return terms

        expanded = set(terms)
        for term in terms:
            # Look up entity and add its other name forms
            info = self._index.lookup(term)
            if info:
                name = info.get("name", "").lower()
                canonical = info.get("canonical_name", "").lower()
                expanded.add(name)
                expanded.add(canonical)

                # Also add without underscores for substring matching
                stripped = name.replace("_", "").replace("-", "")
                if len(stripped) >= 3:
                    expanded.add(stripped)

        return sorted(expanded)

    def _build_graph_terms(
        self, normalized: list[str], expanded: list[str]
    ) -> list[str]:
        """Build final graph search terms for Neptune queries.

        Priority:
        1. Exact entity names (from index match)
        2. Expanded aliases/canonical forms
        3. Normalized extracted terms

        Limit to top 10 terms to avoid expensive queries.
        """
        # Priority terms: those that matched the index
        priority = []
        secondary = []

        for term in expanded:
            if self._index and self._index.lookup(term):
                priority.append(term)
            else:
                secondary.append(term)

        # Combine: priority first, then secondary, max 10
        result = list(dict.fromkeys(priority + secondary))[:10]

        # If nothing extracted, fall back to splitting the question into tokens
        if not result:
            result = self._fallback_tokenize(normalized)

        return result

    def _fallback_tokenize(self, normalized: list[str]) -> list[str]:
        """Last-resort: return whatever we have."""
        return normalized[:5] if normalized else []


def build_graph_search_terms(
    question: str,
    entity_index: Optional[EntityIndex] = None,
    lang: QueryLanguage = QueryLanguage.AUTO,
) -> list[str]:
    """Convenience function: extract → normalize → expand → return search terms.

    Args:
        question: User's question.
        entity_index: Pre-built entity index (optional but recommended).
        lang: Language hint.

    Returns:
        List of graph search terms suitable for Neptune entity queries.
    """
    extractor = QueryEntityExtractor(entity_index)
    result = extractor.extract(question, lang=lang)
    return result.graph_search_terms


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _has_cjk(text: str) -> bool:
    """Check if text contains CJK characters."""
    return bool(re.search(r'[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]', text))


# Common stopwords to filter out (Japanese particles, Chinese function words, English common)
_STOPWORDS = frozenset({
    # English
    "the", "what", "which", "where", "when", "how", "who", "why",
    "are", "was", "were", "have", "has", "had", "does", "did",
    "from", "with", "that", "this", "these", "those",
    "use", "used", "using", "uses", "call", "calls",
    "and", "for", "not", "but", "all", "any",
    "table", "tables", "module", "modules", "system", "service",
    # Short common terms
    "csv", "sql", "xml", "api",
})
