"""
ID registry and generation utilities for the semantic map workflow.

Thread-safe ID tracking, node ID construction, and snake_case normalization.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from pathlib import Path
from typing import Optional

from .constants import NODE_PREFIXES


# ---------------------------------------------------------------------------
# snake_case normalization
# ---------------------------------------------------------------------------

# Characters that should become word separators
_SEP_RE = re.compile(r"[\s\-./\\:@#$%^&*()\[\]{}<>|+=~`!?,;\"']+")

# CamelCase split: insert underscore before uppercase letters following
# lowercase letters or digits (handles camelCase and PascalCase)
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def snake_case(s: str) -> str:
    """
    Normalize *s* to lowercase snake_case.

    Handles:
    - ASCII camelCase / PascalCase splitting
    - Unicode normalization (NFC)
    - CJK and other non-ASCII characters are kept as-is (they do not
      transliterate cleanly without an external library) and are separated
      from adjacent ASCII segments by underscores
    - Runs of separators collapse to a single underscore
    - Leading / trailing underscores are stripped

    Examples::

        snake_case("PaymentRequest")  -> "payment_request"
        snake_case("GET /api/v1/foo") -> "get_api_v1_foo"
        snake_case("TB_PAYMENT")      -> "tb_payment"
    """
    if not s:
        return ""

    # Unicode NFC normalisation keeps composed characters intact
    s = unicodedata.normalize("NFC", s)

    # Split camelCase / PascalCase (ASCII only)
    s = _CAMEL_RE.sub("_", s)

    # Replace separator characters with underscores
    s = _SEP_RE.sub("_", s)

    # Lowercase everything
    s = s.lower()

    # Collapse multiple underscores
    s = re.sub(r"_+", "_", s)

    # Strip leading/trailing underscores
    s = s.strip("_")

    return s


# ---------------------------------------------------------------------------
# Node ID construction
# ---------------------------------------------------------------------------

def make_node_id(prefix: str, name: str) -> str:
    """
    Construct a canonical node ID.

    Special cases:
    - prefix == "method": ID is ``method:{ClassName}.{methodName}``
      Caller must pass ``name`` already in ``ClassName.methodName`` form.
    - prefix == "column": ID is ``column:{TABLE_NAME}.{COLUMN_NAME}``
      Caller must pass ``name`` already in ``TABLE_NAME.COLUMN_NAME`` form.

    For all other prefixes the ID is ``{prefix}:{snake_case(name)}``.

    Raises ``ValueError`` if *prefix* is not in NODE_PREFIXES.
    """
    if not validate_prefix(prefix):
        raise ValueError(
            f"Unknown node prefix {prefix!r}. "
            f"Allowed prefixes: {sorted(NODE_PREFIXES)}"
        )

    if prefix in ("method", "column"):
        # Preserve the dot separator; normalise each segment separately
        if "." in name:
            left, _, right = name.partition(".")
            return f"{prefix}:{snake_case(left)}.{snake_case(right)}"
        # Fallback: no dot provided, treat as plain name
        return f"{prefix}:{snake_case(name)}"

    return f"{prefix}:{snake_case(name)}"


def validate_prefix(prefix: str) -> bool:
    """Return True if *prefix* is a known node prefix."""
    return prefix in NODE_PREFIXES


# ---------------------------------------------------------------------------
# IDRegistry
# ---------------------------------------------------------------------------

class IDRegistry:
    """
    Thread-safe registry that tracks all assigned node IDs and auto-generates
    monotonically increasing edge IDs.

    Node IDs are arbitrary strings (e.g. ``process:payment_request``).
    Edge IDs follow the pattern ``rel:NNNNNN`` (zero-padded to 6 digits).
    """

    _EDGE_PREFIX = "rel"
    _EDGE_PAD = 6

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._node_ids: set[str] = set()
        self._edge_counter: int = 0

    # ------------------------------------------------------------------
    # Node registration
    # ------------------------------------------------------------------

    def register_node(self, id_str: str) -> None:
        """
        Register a node ID.

        Raises ``ValueError`` if *id_str* is already registered.
        """
        if not id_str or not isinstance(id_str, str):
            raise ValueError("Node ID must be a non-empty string")

        with self._lock:
            if id_str in self._node_ids:
                raise ValueError(f"Duplicate node ID: {id_str!r}")
            self._node_ids.add(id_str)

    # ------------------------------------------------------------------
    # Edge registration
    # ------------------------------------------------------------------

    def register_edge(self) -> str:
        """
        Allocate and return the next edge ID (e.g. ``rel:000001``).

        Thread-safe; the counter increments atomically.
        """
        with self._lock:
            self._edge_counter += 1
            return (
                f"{self._EDGE_PREFIX}:"
                f"{self._edge_counter:0{self._EDGE_PAD}d}"
            )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def exists(self, id_str: str) -> bool:
        """Return True if *id_str* is already registered as a node ID."""
        with self._lock:
            return id_str in self._node_ids

    def all_ids(self) -> set[str]:
        """Return a snapshot copy of all registered node IDs."""
        with self._lock:
            return set(self._node_ids)

    @property
    def edge_counter(self) -> int:
        """Current value of the edge counter (number of edges registered)."""
        with self._lock:
            return self._edge_counter

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """
        Persist the registry to a JSON file at *path*.

        The JSON structure is::

            {
                "node_ids": ["id1", "id2", ...],
                "edge_counter": 42
            }
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            data = {
                "node_ids": sorted(self._node_ids),
                "edge_counter": self._edge_counter,
            }

        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    def load(self, path: str | Path) -> None:
        """
        Load registry state from a JSON file previously created by :meth:`save`.

        Merges with any existing in-memory state; duplicate node IDs are
        silently skipped (they were already registered).

        Raises ``FileNotFoundError`` if *path* does not exist.
        Raises ``ValueError`` if the file contains unexpected structure.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Registry file not found: {path}")

        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        if not isinstance(data, dict):
            raise ValueError(f"Registry file {path} must contain a JSON object")

        node_ids = data.get("node_ids", [])
        edge_counter = data.get("edge_counter", 0)

        if not isinstance(node_ids, list):
            raise ValueError("'node_ids' must be a JSON array")
        if not isinstance(edge_counter, int):
            raise ValueError("'edge_counter' must be a JSON integer")

        with self._lock:
            for nid in node_ids:
                if isinstance(nid, str) and nid:
                    self._node_ids.add(nid)
            # Take the maximum so we never reuse an ID from a prior run
            if edge_counter > self._edge_counter:
                self._edge_counter = edge_counter

    @classmethod
    def from_file(cls, path: str | Path) -> "IDRegistry":
        """
        Convenience constructor: create a new registry and load state from *path*.
        """
        registry = cls()
        registry.load(path)
        return registry

    def __len__(self) -> int:
        """Return the number of registered node IDs."""
        with self._lock:
            return len(self._node_ids)

    def __repr__(self) -> str:
        with self._lock:
            return (
                f"IDRegistry(nodes={len(self._node_ids)}, "
                f"edges={self._edge_counter})"
            )
