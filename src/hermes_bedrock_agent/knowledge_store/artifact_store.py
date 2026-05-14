"""Artifact store — manages JSONL/Cypher intermediate products by stage.

Provides a structured directory layout for all pipeline artifacts:
  data/processed/<run_id>/  — per-run artifacts
  data/artifacts/           — latest/consolidated artifacts
  data/registry/            — document registry snapshots

Supports:
- Artifact path resolution by name
- Run-based organization (optional run_id or date)
- Existence checking
- Listing available artifacts
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from hermes_bedrock_agent.configs.logging import get_logger

logger = get_logger(__name__)


class ArtifactType(str, Enum):
    """Known pipeline artifact names."""

    # Ingestion stage
    DOCUMENTS = "documents.jsonl"
    NORMALIZED_DOCUMENTS = "normalized_documents.jsonl"
    VISUAL_BLOCKS = "visual_blocks.jsonl"

    # Chunking stage
    CHUNKS = "chunks.jsonl"

    # Embedding stage
    EMBEDDINGS = "embeddings.jsonl"

    # Graph extraction stage
    RAW_ENTITIES = "raw_entities.jsonl"
    RAW_RELATIONS = "raw_relations.jsonl"
    RAW_EVIDENCE = "raw_evidence.jsonl"

    # Graph normalization stage
    ENTITIES = "entities.jsonl"
    RELATIONS = "relations.jsonl"
    EVIDENCE = "evidence.jsonl"

    # Loading stage
    OPENSEARCH_BULK = "opensearch_bulk.jsonl"
    NEPTUNE_IMPORT = "neptune_import.cypher"


class ArtifactStoreConfig(BaseModel):
    """Configuration for the artifact store."""

    base_dir: Path = Field(default=Path("data"), description="Root data directory")
    use_run_id: bool = Field(default=True, description="Organize by run_id")
    persist_inline_image_base64: bool = Field(
        default=False,
        description="If False, strip image_base64 from persisted VisualBlocks",
    )


class ArtifactStore:
    """Manages pipeline artifact files organized by stage and run.

    Directory layout:
        {base_dir}/processed/{run_id}/{artifact_name}
        {base_dir}/artifacts/{artifact_name}       (latest consolidated)
        {base_dir}/registry/document_registry.jsonl
    """

    def __init__(
        self,
        config: Optional[ArtifactStoreConfig] = None,
        base_dir: Optional[Path | str] = None,
        run_id: Optional[str] = None,
    ):
        self._config = config or ArtifactStoreConfig()
        if base_dir:
            self._config.base_dir = Path(base_dir)

        self._run_id = run_id or self._generate_run_id()
        self._base_dir = self._config.base_dir

        # Ensure directories exist
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _generate_run_id() -> str:
        """Generate a timestamp-based run ID."""
        return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def processed_dir(self) -> Path:
        """Per-run processed artifacts directory."""
        if self._config.use_run_id:
            return self._base_dir / "processed" / self._run_id
        return self._base_dir / "processed"

    @property
    def artifacts_dir(self) -> Path:
        """Latest/consolidated artifacts directory."""
        return self._base_dir / "artifacts"

    @property
    def registry_dir(self) -> Path:
        """Document registry directory."""
        return self._base_dir / "registry"

    @property
    def persist_inline_image_base64(self) -> bool:
        """Whether to persist image_base64 in JSONL output."""
        return self._config.persist_inline_image_base64

    def get_path(
        self,
        artifact: ArtifactType | str,
        *,
        use_run: bool = True,
    ) -> Path:
        """Get the file path for a named artifact.

        Args:
            artifact: Artifact type or filename string.
            use_run: If True, use the per-run processed dir.
                     If False, use the consolidated artifacts dir.

        Returns:
            Full path to the artifact file.
        """
        name = artifact.value if isinstance(artifact, ArtifactType) else artifact
        if use_run:
            return self.processed_dir / name
        return self.artifacts_dir / name

    def get_registry_path(self, name: str = "document_registry.jsonl") -> Path:
        """Get path to a registry file."""
        return self.registry_dir / name

    def exists(self, artifact: ArtifactType | str, *, use_run: bool = True) -> bool:
        """Check if an artifact file exists."""
        return self.get_path(artifact, use_run=use_run).exists()

    def artifact_size(self, artifact: ArtifactType | str, *, use_run: bool = True) -> int:
        """Get artifact file size in bytes (0 if not exists)."""
        p = self.get_path(artifact, use_run=use_run)
        return p.stat().st_size if p.exists() else 0

    def list_run_artifacts(self) -> list[str]:
        """List all artifact files in the current run directory."""
        if not self.processed_dir.exists():
            return []
        return sorted(f.name for f in self.processed_dir.iterdir() if f.is_file())

    def list_runs(self) -> list[str]:
        """List all available run IDs (sorted by date desc)."""
        processed_root = self._base_dir / "processed"
        if not processed_root.exists():
            return []
        return sorted(
            (d.name for d in processed_root.iterdir() if d.is_dir()),
            reverse=True,
        )

    def get_latest_run(self) -> Optional[str]:
        """Get the most recent run_id."""
        runs = self.list_runs()
        return runs[0] if runs else None

    def summary(self) -> dict[str, any]:
        """Return summary of current run's artifacts."""
        artifacts = {}
        for art in ArtifactType:
            p = self.get_path(art)
            if p.exists():
                artifacts[art.value] = {
                    "exists": True,
                    "size_bytes": p.stat().st_size,
                }
            else:
                artifacts[art.value] = {"exists": False}

        return {
            "run_id": self._run_id,
            "base_dir": str(self._base_dir),
            "processed_dir": str(self.processed_dir),
            "artifacts": artifacts,
        }
