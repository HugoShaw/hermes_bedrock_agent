"""
Similarity computation utilities for the semantic map workflow.

Provides cosine similarity for dense vectors, Jaccard similarity for sets,
token-overlap scoring, and a composite name-similarity function.  The
:func:`find_similar_entities` function combines embedding-based and
lexical similarity with a configurable threshold.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from semantic_map.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional difflib for edit-distance ratio
# ---------------------------------------------------------------------------
import difflib  # part of stdlib – always available

# Optional: janome or jieba for CJK tokenisation
try:
    import jieba  # type: ignore
    _JIEBA_AVAILABLE = True
except ImportError:
    _JIEBA_AVAILABLE = False

# CJK Unicode ranges (BMP only – sufficient for most practical use)
_CJK_RE = re.compile(
    r"[　-〿"    # CJK symbols & punctuation
    r"぀-ゟ"    # Hiragana
    r"゠-ヿ"    # Katakana
    r"一-鿿"    # CJK Unified Ideographs
    r"ꀀ-꒏"    # Yi Syllables
    r"가-힯"    # Hangul
    r"豈-﫿"    # CJK Compatibility Ideographs
    r"]"
)

_PUNCT_RE = re.compile(r"[^\w\s　-鿿가-힯]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# Core similarity primitives
# ---------------------------------------------------------------------------

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Return the cosine similarity between two dense vectors.

    Returns ``0.0`` when either vector is empty or has zero magnitude.

    Parameters
    ----------
    v1, v2:
        Dense float vectors of the same dimensionality.

    Returns
    -------
    float
        Cosine similarity in ``[0.0, 1.0]`` (assuming non-negative vectors,
        as produced by Titan Embeddings).
    """
    if not v1 or not v2:
        return 0.0
    if len(v1) != len(v2):
        logger.warning(
            "cosine_similarity: dimension mismatch (%d vs %d)", len(v1), len(v2)
        )
        return 0.0

    dot = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))

    if mag1 == 0.0 or mag2 == 0.0:
        return 0.0

    # Clamp to [0, 1] to absorb floating-point noise
    return max(0.0, min(1.0, dot / (mag1 * mag2)))


def jaccard_similarity(set1: set, set2: set) -> float:
    """Return the Jaccard similarity between two sets.

    ``|set1 ∩ set2| / |set1 ∪ set2|``

    Returns ``0.0`` when both sets are empty.

    Parameters
    ----------
    set1, set2:
        Any two Python sets (elements must be hashable).

    Returns
    -------
    float
        Jaccard score in ``[0.0, 1.0]``.
    """
    if not set1 and not set2:
        return 0.0
    intersection = len(set1 & set2)
    union = len(set1 | set2)
    return intersection / union if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Name tokenisation & normalisation
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Normalise an entity name for comparison.

    Steps applied:
    1. Unicode NFKC normalisation.
    2. Lower-case.
    3. Split camelCase / PascalCase tokens.
    4. Remove punctuation (preserving CJK characters and whitespace).
    5. Collapse whitespace.

    Parameters
    ----------
    name:
        Raw entity name (may contain CJK characters, camelCase, etc.).

    Returns
    -------
    str
        Normalised string.
    """
    # NFKC: full-width -> half-width, compatibility decomposition
    text = unicodedata.normalize("NFKC", name)

    # Split camelCase: "getUserName" -> "get User Name"
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    # Split on underscores / hyphens
    text = re.sub(r"[_\-]", " ", text)

    text = text.lower()
    # Remove punctuation while preserving CJK ranges
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _tokenize(name: str) -> list[str]:
    """Tokenise a normalised name into a list of string tokens.

    Uses jieba for CJK text when available, otherwise splits on whitespace.
    """
    normalised = normalize_name(name)
    if not normalised:
        return []

    has_cjk = bool(_CJK_RE.search(normalised))
    if has_cjk and _JIEBA_AVAILABLE:
        tokens = list(jieba.cut(normalised, cut_all=False))
        return [t.strip() for t in tokens if t.strip()]

    return normalised.split()


def name_similarity(name1: str, name2: str) -> float:
    """Compute a composite similarity score between two entity names.

    The score is a weighted combination of:
    - Jaccard similarity on token sets (weight 0.5)
    - SequenceMatcher edit-distance ratio on normalised strings (weight 0.5)

    Parameters
    ----------
    name1, name2:
        Entity name strings (may include CJK characters).

    Returns
    -------
    float
        Similarity in ``[0.0, 1.0]``.
    """
    if not name1 or not name2:
        return 0.0

    n1 = normalize_name(name1)
    n2 = normalize_name(name2)

    if n1 == n2:
        return 1.0

    # Jaccard on token sets
    tokens1 = set(_tokenize(name1))
    tokens2 = set(_tokenize(name2))
    j_score = jaccard_similarity(tokens1, tokens2)

    # Edit-distance ratio (SequenceMatcher)
    edit_ratio = difflib.SequenceMatcher(None, n1, n2).ratio()

    return 0.5 * j_score + 0.5 * edit_ratio


# ---------------------------------------------------------------------------
# Token overlap
# ---------------------------------------------------------------------------

def token_overlap(text1: str, text2: str) -> float:
    """Return the normalised token overlap ratio between two texts.

    The overlap is defined as:
    ``2 * |tokens1 ∩ tokens2| / (|tokens1| + |tokens2|)``
    (Sørensen–Dice coefficient on token multisets reduced to sets).

    Parameters
    ----------
    text1, text2:
        Arbitrary text strings.

    Returns
    -------
    float
        Score in ``[0.0, 1.0]``.
    """
    tokens1 = set(_tokenize(text1))
    tokens2 = set(_tokenize(text2))

    if not tokens1 and not tokens2:
        return 0.0

    intersection = len(tokens1 & tokens2)
    denominator = len(tokens1) + len(tokens2)
    return (2 * intersection) / denominator if denominator > 0 else 0.0


# ---------------------------------------------------------------------------
# Entity matching
# ---------------------------------------------------------------------------

def find_similar_entities(
    target: dict,
    candidates: list[dict],
    threshold: float = 0.7,
    embedding_client: Optional["EmbeddingClient"] = None,
    name_key: str = "name",
    embedding_key: str = "embedding",
) -> list[tuple[dict, float]]:
    """Find candidates that are similar to *target*.

    The similarity strategy is:

    1. **Embedding-based** – if *embedding_client* is provided and both
       *target* and *candidate* have no pre-computed ``embedding`` field,
       embeddings are fetched on demand.  If the ``embedding`` field is already
       present on both dicts it is used directly.
    2. **Name-based fallback** – when embeddings are unavailable or yield
       ``0.0``, :func:`name_similarity` is used.

    Parameters
    ----------
    target:
        The entity to match against.  Should contain at minimum a ``name`` key
        (configurable via *name_key*).
    candidates:
        List of candidate entity dicts.
    threshold:
        Minimum similarity score for inclusion in results.
    embedding_client:
        Optional :class:`~embedding_client.EmbeddingClient` instance.  When
        provided, used to embed names on-the-fly if ``embedding`` is absent.
    name_key:
        Dict key holding the entity name (default ``"name"``).
    embedding_key:
        Dict key holding a pre-computed embedding vector (default
        ``"embedding"``).

    Returns
    -------
    list[tuple[dict, float]]
        List of ``(candidate, score)`` tuples where ``score >= threshold``,
        sorted by score descending.
    """
    target_name: str = target.get(name_key, "")
    target_embedding: list[float] = target.get(embedding_key, [])

    # Optionally fetch target embedding
    if not target_embedding and embedding_client is not None and target_name:
        try:
            target_embedding = embedding_client.embed(target_name)
        except Exception as exc:
            logger.warning("find_similar_entities: embed(target) failed: %s", exc)

    results: list[tuple[dict, float]] = []

    for candidate in candidates:
        cand_name: str = candidate.get(name_key, "")
        score = _score_pair(
            target_name=target_name,
            target_embedding=target_embedding,
            cand_name=cand_name,
            cand_embedding=candidate.get(embedding_key, []),
            embedding_client=embedding_client,
        )
        if score >= threshold:
            results.append((candidate, score))

    results.sort(key=lambda t: t[1], reverse=True)
    logger.debug(
        "find_similar_entities: %d/%d candidates above threshold %.2f for %r",
        len(results),
        len(candidates),
        threshold,
        target_name,
    )
    return results


def _score_pair(
    target_name: str,
    target_embedding: list[float],
    cand_name: str,
    cand_embedding: list[float],
    embedding_client: Optional["EmbeddingClient"],
) -> float:
    """Compute a combined similarity score for a (target, candidate) pair."""
    # Try embedding similarity first
    if target_embedding:
        if not cand_embedding and embedding_client is not None and cand_name:
            try:
                cand_embedding = embedding_client.embed(cand_name)
            except Exception:
                pass

        if cand_embedding:
            emb_score = cosine_similarity(target_embedding, cand_embedding)
            if emb_score > 0.0:
                return emb_score

    # Fall back to name similarity
    if target_name and cand_name:
        return name_similarity(target_name, cand_name)

    return 0.0
