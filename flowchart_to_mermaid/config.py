"""Configuration for the flowchart-to-mermaid pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ConvertConfig:
    """Configuration for a single conversion run."""
    input_path: Path = field(default_factory=lambda: Path("input.pdf"))
    output_dir: Path = field(default_factory=lambda: Path("output"))
    lang: str = "ja"
    render_zoom: int = 3
    use_ocr: str = "auto"  # true, false, auto
    use_llm_repair: bool = False
    direction: str = "auto"  # TD, LR, auto
    render_svg: bool = True
    svg_required: bool = True

    @property
    def pages_dir(self) -> Path:
        return self.output_dir / "pages"

    @property
    def crops_dir(self) -> Path:
        return self.output_dir / "crops"

    @property
    def debug_dir(self) -> Path:
        return self.output_dir / "debug"

    def ensure_dirs(self) -> None:
        """Create all output directories."""
        self.pages_dir.mkdir(parents=True, exist_ok=True)
        self.crops_dir.mkdir(parents=True, exist_ok=True)
        self.debug_dir.mkdir(parents=True, exist_ok=True)
