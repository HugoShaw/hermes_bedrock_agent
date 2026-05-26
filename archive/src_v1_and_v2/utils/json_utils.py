"""JSONL read/write utilities for intermediate artifact storage.

All pipeline stages produce and consume JSONL files. This module
provides type-safe helpers for reading/writing Pydantic models
to/from JSONL format.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def write_jsonl(path: Path | str, records: list[BaseModel], *, append: bool = False) -> int:
    """Write a list of Pydantic models to a JSONL file.

    Args:
        path: Output file path (created if not exists, parents created).
        records: List of Pydantic models to serialize.
        append: If True, append to existing file instead of overwriting.

    Returns:
        Number of records written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"

    with open(path, mode, encoding="utf-8") as f:
        for record in records:
            line = record.model_dump_json()
            f.write(line + "\n")

    return len(records)


def read_jsonl(path: Path | str, model_class: Type[T]) -> list[T]:
    """Read all records from a JSONL file into typed Pydantic models.

    Args:
        path: JSONL file path.
        model_class: Pydantic model class to deserialize into.

    Returns:
        List of model instances.

    Raises:
        FileNotFoundError: If path doesn't exist.
        ValidationError: If a line doesn't match the model schema.
    """
    path = Path(path)
    records: list[T] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            records.append(model_class.model_validate(obj))
    return records


def stream_jsonl(path: Path | str, model_class: Type[T]) -> Generator[T, None, None]:
    """Stream records from a JSONL file (memory-efficient for large files).

    Args:
        path: JSONL file path.
        model_class: Pydantic model class to deserialize into.

    Yields:
        Model instances one at a time.
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            yield model_class.model_validate(obj)


def count_jsonl(path: Path | str) -> int:
    """Count records in a JSONL file without loading them all.

    Args:
        path: JSONL file path.

    Returns:
        Number of non-empty lines.
    """
    path = Path(path)
    if not path.exists():
        return 0
    count = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def merge_jsonl(output_path: Path | str, input_paths: list[Path | str]) -> int:
    """Merge multiple JSONL files into one (preserving order).

    Args:
        output_path: Destination JSONL file.
        input_paths: Source JSONL files to merge.

    Returns:
        Total number of records in merged output.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with open(output_path, "w", encoding="utf-8") as out:
        for input_path in input_paths:
            input_path = Path(input_path)
            if not input_path.exists():
                continue
            with open(input_path, "r", encoding="utf-8") as inp:
                for line in inp:
                    if line.strip():
                        out.write(line if line.endswith("\n") else line + "\n")
                        total += 1
    return total
