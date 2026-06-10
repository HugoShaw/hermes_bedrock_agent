"""V2 MermaidParser — wraps parsing.mermaid_parser for the v2 registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .mermaid_parser import parse_mermaid_file, MermaidParseResult
from .base_parser import BaseParser


class MermaidParser(BaseParser):
    """Parse .mmd and .mermaid files into structured documents."""

    @property
    def name(self) -> str:
        return "mermaid"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.MERMAID or path.suffix.lower() in (".mmd", ".mermaid")

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result: MermaidParseResult = parse_mermaid_file(str(path), tmp_dir)

        rel = relative_path or path.name
        doc_id = generate_doc_id(project_id, rel)
        title = result.title or f"Mermaid: {path.stem}"

        metadata = {
            "diagram_type": result.diagram_type,
            "nodes": len(result.nodes),
            "edges": len(result.edges),
            "subgraphs": len(result.subgraphs),
        }

        return [
            ParsedDocument(
                doc_id=doc_id,
                project_id=project_id,
                source_path=str(path),
                source_type=SourceType.MERMAID,
                title=title,
                content_markdown=result.markdown_summary,
                metadata=metadata,
                evidence_paths=[str(path)],
                parse_method="mermaid_regex",
            )
        ]

    def estimated_cost(self, path: Path) -> dict[str, Any]:
        size = path.stat().st_size if path.exists() else 0
        return {
            "parser": self.name,
            "file_size_bytes": size,
            "estimated_tokens": size // 4,
            "needs_api": False,
        }
