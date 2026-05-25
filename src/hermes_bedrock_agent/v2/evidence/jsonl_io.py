"""
JSONL read/write utilities for the V2 evidence pipeline.

All output uses ensure_ascii=False so CJK characters are preserved verbatim.
Pydantic models are serialised via their .to_jsonl() method; plain dicts
are JSON-dumped directly.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator, Union

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def ensure_parent_dir(path: Union[str, Path]) -> Path:
    """Create all parent directories for *path* if they do not already exist."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def write_jsonl(
    path: Union[str, Path],
    records: list[Union[BaseModel, dict[str, Any]]],
    *,
    overwrite: bool = True,
) -> int:
    """Write *records* to a JSONL file, one record per line.

    Args:
        path: Destination file path.
        records: List of Pydantic models or plain dicts.
        overwrite: If True (default), truncate any existing file.

    Returns:
        Number of records written.
    """
    p = ensure_parent_dir(path)
    mode = "w" if overwrite else "a"
    written = 0
    with p.open(mode, encoding="utf-8") as fh:
        for rec in records:
            line = _to_json_line(rec)
            fh.write(line + "\n")
            written += 1
    logger.debug("Wrote %d records to %s", written, p)
    return written


def append_jsonl(
    path: Union[str, Path],
    records: list[Union[BaseModel, dict[str, Any]]],
) -> int:
    """Append *records* to an existing (or new) JSONL file."""
    return write_jsonl(path, records, overwrite=False)


def read_jsonl(
    path: Union[str, Path],
    *,
    skip_errors: bool = True,
) -> Iterator[dict[str, Any]]:
    """Iterate over records in a JSONL file.

    Yields plain dicts. Use the schema's ``from_jsonl()`` to reconstruct
    typed models when needed.

    Args:
        path: Source file path.
        skip_errors: If True, log and skip malformed lines rather than raising.
    """
    p = Path(path)
    if not p.exists():
        logger.warning("JSONL file not found: %s", p)
        return
    with p.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError as exc:
                if skip_errors:
                    logger.warning("Skipping malformed JSONL line %d in %s: %s", lineno, p, exc)
                else:
                    raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_json_line(record: Union[BaseModel, dict[str, Any]]) -> str:
    if isinstance(record, BaseModel):
        # Prefer the schema's own serialiser so field aliases / validators run
        if hasattr(record, "to_jsonl"):
            return record.to_jsonl()  # type: ignore[return-value]
        return json.dumps(record.model_dump(), ensure_ascii=False)
    return json.dumps(record, ensure_ascii=False)
