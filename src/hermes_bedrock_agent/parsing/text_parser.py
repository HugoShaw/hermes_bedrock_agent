"""Markdown post-processing — inject ground-truth Mermaid, ensure H1 title."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from .models import ParseResult

logger = logging.getLogger(__name__)

_MERMAID_FENCE_RE = re.compile(r"```mermaid\n.*?```", re.DOTALL)


def _validate_mermaid(mmd_text: str) -> bool:
    first_line = mmd_text.strip().splitlines()[0].strip().lower() if mmd_text.strip() else ""
    known_types = ("flowchart", "graph", "sequencediagram", "classdiagram",
                   "statediagram", "erdiagram", "gantt", "pie", "gitgraph")
    return any(first_line.startswith(t) for t in known_types)


def inject_ground_truth_mermaid(markdown: str, mermaid_path: str) -> str:
    mmd_text = Path(mermaid_path).read_text(encoding="utf-8").strip()
    if not _validate_mermaid(mmd_text):
        logger.warning("Ground-truth Mermaid file has unexpected format — skipping injection")
        return markdown

    replacement = f"```mermaid\n{mmd_text}\n```"
    if _MERMAID_FENCE_RE.search(markdown):
        return _MERMAID_FENCE_RE.sub(replacement, markdown, count=1)

    h1_match = re.search(r"^# .+$", markdown, re.MULTILINE)
    insert_pos = h1_match.end() if h1_match else len(markdown)
    return (
        markdown[:insert_pos]
        + f"\n\n## Flowchart (Ground Truth)\n\n{replacement}\n"
        + markdown[insert_pos:]
    )


def structure_markdown(markdown: str, sheet_name: str) -> str:
    stripped = markdown.strip()
    if not stripped.startswith("# "):
        return f"# Sheet: {sheet_name}\n\n{stripped}"
    return stripped


def post_process(result: ParseResult, ground_truth_mmd: Optional[str] = None) -> ParseResult:
    markdown = result.markdown
    if ground_truth_mmd and Path(ground_truth_mmd).exists():
        markdown = inject_ground_truth_mermaid(markdown, ground_truth_mmd)
    markdown = structure_markdown(markdown, result.sheet_info.name)

    mermaid = None
    m = _MERMAID_FENCE_RE.search(markdown)
    if m:
        inner = m.group(0)
        mermaid = inner.replace("```mermaid\n", "").rstrip("`").rstrip()

    return result.model_copy(update={"markdown": markdown, "mermaid": mermaid})


def post_process_all(
    results: list[ParseResult],
    ground_truth_map: Optional[dict[str, str]] = None,
) -> list[ParseResult]:
    ground_truth_map = ground_truth_map or {}
    return [post_process(r, ground_truth_mmd=ground_truth_map.get(r.sheet_info.name)) for r in results]
