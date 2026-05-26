"""File registry - tracks processed files for incremental sync."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from hermes_bedrock_agent.s3_graph_etl.schemas import FileRecord

logger = logging.getLogger(__name__)

DEFAULT_REGISTRY_PATH = Path("data/registry/file_registry.jsonl")


class FileRegistry:
    """Persistent registry of processed files for incremental updates."""

    def __init__(self, registry_path: Path | None = None) -> None:
        self.path = registry_path or DEFAULT_REGISTRY_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, FileRecord] = {}
        self._load()

    def _load(self) -> None:
        """Load existing registry from disk."""
        if not self.path.exists():
            return
        try:
            with open(self.path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    data = json.loads(line)
                    record = FileRecord(**data)
                    self._records[record.uri] = record
            logger.info("Loaded %d records from registry", len(self._records))
        except Exception as exc:
            logger.warning("Failed to load registry: %s", exc)

    def save(self) -> None:
        """Persist registry to disk."""
        with open(self.path, "w") as f:
            for record in self._records.values():
                f.write(record.model_dump_json() + "\n")

    def get(self, uri: str) -> FileRecord | None:
        return self._records.get(uri)

    def upsert(self, record: FileRecord) -> None:
        self._records[record.uri] = record

    def needs_processing(self, record: FileRecord) -> bool:
        """Check if a file needs (re)processing based on etag/size."""
        existing = self._records.get(record.uri)
        if existing is None:
            return True
        if existing.status == "failed":
            return True
        if existing.etag != record.etag:
            return True
        return False

    def mark_done(self, uri: str, chunk_count: int = 0) -> None:
        record = self._records.get(uri)
        if record:
            self._records[uri] = record.model_copy(update={"status": "done", "chunk_count": chunk_count})

    def mark_failed(self, uri: str, error: str) -> None:
        record = self._records.get(uri)
        if record:
            self._records[uri] = record.model_copy(update={"status": "failed", "error_message": error})

    @property
    def total(self) -> int:
        return len(self._records)

    @property
    def done_count(self) -> int:
        return sum(1 for r in self._records.values() if r.status == "done")

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self._records.values() if r.status == "failed")
