"""
PathConfig: centralised directory and file path management for the
semantic map workflow pipeline.

All paths are derived from a single ``output_dir`` root so the entire
output tree can be relocated by changing one value.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# PathConfig
# ---------------------------------------------------------------------------

@dataclass
class PathConfig:
    """
    Dataclass that holds all directory paths used by the semantic map pipeline.

    Attributes:
        output_dir:  Root directory for all pipeline outputs.
        tmp_dir:     Scratch / intermediate files.
        prompts_dir: LLM prompt templates.
        raw_llm_dir: Raw LLM responses (JSON/text) before parsing.
    """

    output_dir: Path
    tmp_dir: Path
    prompts_dir: Path
    raw_llm_dir: Path

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_root(
        cls,
        root: str | Path,
        *,
        tmp_subdir: str = "tmp",
        prompts_subdir: str = "prompts",
        raw_llm_subdir: str = "raw_llm",
    ) -> "PathConfig":
        """
        Build a ``PathConfig`` from a single root directory.

        All sub-directories are created relative to *root*::

            root/
            ├── tmp/
            ├── prompts/
            └── raw_llm/

        Args:
            root:            Base directory for all outputs.
            tmp_subdir:      Name of the scratch sub-directory.
            prompts_subdir:  Name of the prompts sub-directory.
            raw_llm_subdir:  Name of the raw LLM output sub-directory.
        """
        root = Path(root)
        return cls(
            output_dir=root,
            tmp_dir=root / tmp_subdir,
            prompts_dir=root / prompts_subdir,
            raw_llm_dir=root / raw_llm_subdir,
        )

    # ------------------------------------------------------------------
    # Stage output directories
    # ------------------------------------------------------------------

    def stage_output_dir(self, stage_num: int | str) -> Path:
        """
        Return the output directory for a given pipeline stage.

        The directory is ``{output_dir}/stage_{stage_num:02d}``.
        Directories are NOT created here; call :meth:`ensure_dirs` or
        create them yourself.

        Args:
            stage_num: Integer or string stage identifier (e.g. ``3`` or
                       ``"03"``).
        """
        if isinstance(stage_num, int):
            label = f"{stage_num:02d}"
        else:
            label = str(stage_num)
        return self.output_dir / f"stage_{label}"

    # ------------------------------------------------------------------
    # Well-known file paths
    # ------------------------------------------------------------------

    def node_registry_path(self) -> Path:
        """
        Path to the persistent node ID registry JSON file.

        Located at ``{output_dir}/node_registry.json``.
        """
        return self.output_dir / "node_registry.json"

    @property
    def nodes_jsonl_path(self) -> Path:
        """
        Path to the master nodes JSONL file (one node dict per line).

        Located at ``{output_dir}/nodes.jsonl``.
        """
        return self.output_dir / "nodes.jsonl"

    @property
    def edges_jsonl_path(self) -> Path:
        """
        Path to the master edges JSONL file (one edge dict per line).

        Located at ``{output_dir}/edges.jsonl``.
        """
        return self.output_dir / "edges.jsonl"

    @property
    def display_graph_path(self) -> Path:
        """
        Path to the display sub-graph JSON file.

        Located at ``{output_dir}/display_graph.json``.
        """
        return self.output_dir / "display_graph.json"

    @property
    def cypher_script_path(self) -> Path:
        """
        Path to the generated Cypher import script.

        Located at ``{output_dir}/import.cypher``.
        """
        return self.output_dir / "import.cypher"

    @property
    def validation_report_path(self) -> Path:
        """
        Path to the validation report JSON file.

        Located at ``{output_dir}/validation_report.json``.
        """
        return self.output_dir / "validation_report.json"

    # ------------------------------------------------------------------
    # Raw LLM output helpers
    # ------------------------------------------------------------------

    def raw_llm_stage_path(self, stage_num: int | str, filename: str) -> Path:
        """
        Return a path inside ``raw_llm_dir`` scoped to a given stage.

        The directory is ``{raw_llm_dir}/stage_{stage_num:02d}/{filename}``.
        """
        if isinstance(stage_num, int):
            label = f"{stage_num:02d}"
        else:
            label = str(stage_num)
        return self.raw_llm_dir / f"stage_{label}" / filename

    # ------------------------------------------------------------------
    # Directory creation
    # ------------------------------------------------------------------

    def ensure_dirs(self) -> None:
        """
        Create all managed directories (and their parents) if they do not
        already exist.

        This is idempotent and safe to call multiple times.
        """
        dirs_to_create: list[Path] = [
            self.output_dir,
            self.tmp_dir,
            self.prompts_dir,
            self.raw_llm_dir,
        ]
        for d in dirs_to_create:
            d.mkdir(parents=True, exist_ok=True)

    def ensure_stage_dir(self, stage_num: int | str) -> Path:
        """
        Create and return the output directory for a pipeline stage.

        Equivalent to::

            path = config.stage_output_dir(stage_num)
            path.mkdir(parents=True, exist_ok=True)
            return path
        """
        path = self.stage_output_dir(stage_num)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_raw_llm_stage_dir(self, stage_num: int | str) -> Path:
        """
        Create and return the raw LLM output directory for a pipeline stage.
        """
        if isinstance(stage_num, int):
            label = f"{stage_num:02d}"
        else:
            label = str(stage_num)
        path = self.raw_llm_dir / f"stage_{label}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"PathConfig("
            f"output_dir={str(self.output_dir)!r}, "
            f"tmp_dir={str(self.tmp_dir)!r}, "
            f"prompts_dir={str(self.prompts_dir)!r}, "
            f"raw_llm_dir={str(self.raw_llm_dir)!r})"
        )
