"""JSONL storage — read, write, append, iterate Pydantic models as JSONL.

Core I/O layer for all intermediate artifacts in the pipeline.
Supports Pydantic BaseModel (auto model_dump) and plain dicts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator, Optional, Type, TypeVar

from pydantic import BaseModel

from hermes_bedrock_agent.configs.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# Fields to exclude from JSONL output by default (large binary data)
_DEFAULT_EXCLUDE_FIELDS: set[str] = {"image_base64"}


def ensure_parent_dir(path: Path | str) -> Path:
    """Ensure parent directory exists for a file path."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _serialize_record(
    record: BaseModel | dict[str, Any],
    exclude_fields: Optional[set[str]] = None,
    persist_inline_image_base64: bool = False,
) -> str:
    """Serialize a single record to a JSON line.

    Args:
        record: Pydantic model or dict.
        exclude_fields: Fields to exclude from output.
        persist_inline_image_base64: If False (default), exclude image_base64.
    """
    effective_exclude = set(exclude_fields or set())
    if not persist_inline_image_base64:
        effective_exclude.add("image_base64")

    if isinstance(record, BaseModel):
        data = record.model_dump(mode="json", exclude=effective_exclude or None)
    elif isinstance(record, dict):
        data = {k: v for k, v in record.items() if k not in effective_exclude}
    else:
        raise TypeError(f"Expected BaseModel or dict, got {type(record)}")

    return json.dumps(data, ensure_ascii=False, default=str)


def write_jsonl(
    records: list[BaseModel | dict[str, Any]],
    path: Path | str,
    *,
    exclude_fields: Optional[set[str]] = None,
    persist_inline_image_base64: bool = False,
    dry_run: bool = False,
) -> int:
    """Write records to a JSONL file (overwrite).

    Args:
        records: List of Pydantic models or dicts.
        path: Target file path.
        exclude_fields: Extra fields to exclude.
        persist_inline_image_base64: If False, strip image_base64 from output.
        dry_run: If True, compute but do not write.

    Returns:
        Number of records written (or would-be-written in dry_run).
    """
    if dry_run:
        logger.info(f"[dry-run] Would write {len(records)} records to {path}")
        return len(records)

    p = ensure_parent_dir(path)
    lines_written = 0
    with open(p, "w", encoding="utf-8") as f:
        for record in records:
            line = _serialize_record(record, exclude_fields, persist_inline_image_base64)
            f.write(line + "\n")
            lines_written += 1

    logger.info(f"Wrote {lines_written} records to {p}")
    return lines_written


def append_jsonl(
    records: list[BaseModel | dict[str, Any]],
    path: Path | str,
    *,
    exclude_fields: Optional[set[str]] = None,
    persist_inline_image_base64: bool = False,
    dry_run: bool = False,
) -> int:
    """Append records to a JSONL file.

    Creates the file if it doesn't exist.

    Returns:
        Number of records appended.
    """
    if dry_run:
        logger.info(f"[dry-run] Would append {len(records)} records to {path}")
        return len(records)

    p = ensure_parent_dir(path)
    lines_written = 0
    with open(p, "a", encoding="utf-8") as f:
        for record in records:
            line = _serialize_record(record, exclude_fields, persist_inline_image_base64)
            f.write(line + "\n")
            lines_written += 1

    logger.debug(f"Appended {lines_written} records to {p}")
    return lines_written


def read_jsonl(
    path: Path | str,
    model: Optional[Type[T]] = None,
) -> list[T] | list[dict[str, Any]]:
    """Read all records from a JSONL file.

    Args:
        path: Source file path.
        model: Optional Pydantic model class for validation.

    Returns:
        List of model instances (if model provided) or dicts.
    """
    p = Path(path)
    if not p.exists():
        return []

    results: list[Any] = []
    with open(p, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if model:
                    results.append(model.model_validate(data))
                else:
                    results.append(data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Skipped malformed line {line_num} in {p}: {e}")
                continue

    return results


def iter_jsonl(
    path: Path | str,
    model: Optional[Type[T]] = None,
) -> Generator[T | dict[str, Any], None, None]:
    """Lazily iterate records from a JSONL file.

    Memory-efficient for large files. Same interface as read_jsonl but yields.
    """
    p = Path(path)
    if not p.exists():
        return

    with open(p, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                if model:
                    yield model.model_validate(data)
                else:
                    yield data
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Skipped malformed line {line_num} in {p}: {e}")
                continue


def count_jsonl(path: Path | str) -> int:
    """Count records in a JSONL file without loading into memory."""
    p = Path(path)
    if not p.exists():
        return 0
    count = 0
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count
