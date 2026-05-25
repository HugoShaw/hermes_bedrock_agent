"""Stage 5: Markdown post-processing — merge tile results, inject ground-truth Mermaid."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from ..models import ParseResult

logger = logging.getLogger(__name__)

# Matches ```mermaid ... ``` blocks
_MERMAID_FENCE_RE = re.compile(r"```mermaid\n.*?```", re.DOTALL)


def _validate_mermaid(mmd_text: str) -> bool:
    """Basic syntactic sanity check — just confirms it starts with a diagram type."""
    first_line = mmd_text.strip().splitlines()[0].strip().lower() if mmd_text.strip() else ""
    known_types = (
        "flowchart", "graph", "sequencediagram", "classDiagram",
        "statediagram", "erdiagram", "gantt", "pie", "gitgraph",
    )
    return any(first_line.startswith(t.lower()) for t in known_types)


def inject_ground_truth_mermaid(markdown: str, mermaid_path: str) -> str:
    """Replace any VLM-generated Mermaid block with the authoritative .mmd file.

    If the markdown has no existing mermaid block, appends it as a new section.
    """
    mmd_text = Path(mermaid_path).read_text(encoding="utf-8").strip()

    if not _validate_mermaid(mmd_text):
        logger.warning("Ground-truth Mermaid file has unexpected format — skipping injection")
        return markdown

    replacement = f"```mermaid\n{mmd_text}\n```"

    if _MERMAID_FENCE_RE.search(markdown):
        updated = _MERMAID_FENCE_RE.sub(replacement, markdown, count=1)
        logger.info("  Replaced VLM-generated Mermaid with ground-truth")
        return updated

    # Append after the first H1 or at end
    h1_match = re.search(r"^# .+$", markdown, re.MULTILINE)
    insert_pos = h1_match.end() if h1_match else len(markdown)
    updated = (
        markdown[:insert_pos]
        + f"\n\n## Flowchart (Ground Truth)\n\n{replacement}\n"
        + markdown[insert_pos:]
    )
    logger.info("  Appended ground-truth Mermaid (no existing block found)")
    return updated


def structure_markdown(markdown: str, sheet_name: str) -> str:
    """Ensure the markdown starts with a top-level H1 for the sheet."""
    stripped = markdown.strip()
    if not stripped.startswith("# "):
        return f"# Sheet: {sheet_name}\n\n{stripped}"
    return stripped


def post_process(
    result: ParseResult,
    ground_truth_mmd: Optional[str] = None,
) -> ParseResult:
    """Apply post-processing to a single ParseResult.

    - Optionally inject ground-truth Mermaid
    - Ensure H1 title
    """
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
    """Post-process all parse results.

    ground_truth_map: sheet_name → path to .mmd file (optional).
    """
    ground_truth_map = ground_truth_map or {}
    processed: list[ParseResult] = []
    for r in results:
        mmd_path = ground_truth_map.get(r.sheet_info.name)
        processed.append(post_process(r, ground_truth_mmd=mmd_path))
    return processed
