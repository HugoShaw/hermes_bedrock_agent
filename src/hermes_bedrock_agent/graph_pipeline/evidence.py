"""Phase 1: Split markdown files into evidence units (sections, tables, mermaid blocks)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ._utils import normalize_id

logger = logging.getLogger(__name__)


def split_evidence_units(inventory: list[dict], project_id: str, project_name: str) -> list[dict]:
    """Split each markdown file into evidence units by section/table/mermaid block."""
    evidence_units = []

    for file_rec in inventory:
        if file_rec["read_status"] != "success":
            continue

        try:
            content = Path(file_rec["file_path"]).read_text(encoding="utf-8")
        except Exception:
            continue

        lines = content.split("\n")
        sections: list[dict] = []
        current: dict = {"title": "preamble", "start": 0, "lines": []}

        for i, line in enumerate(lines):
            if re.match(r"^#{1,4}\s+", line):
                if current["lines"]:
                    current["end"] = i - 1
                    sections.append(current)
                current = {"title": line.lstrip("#").strip(), "start": i, "lines": [line]}
            else:
                current["lines"].append(line)

        if current["lines"]:
            current["end"] = len(lines) - 1
            sections.append(current)

        for section in sections:
            section_text = "\n".join(section["lines"])
            if not section_text.strip():
                continue

            section_key = normalize_id(section["title"])[:40]
            evidence_id = (
                f"evidence:{project_id}"
                f":{normalize_id(file_rec['workbook_name'])}"
                f":{normalize_id(file_rec['sheet_name'])}"
                f":{section_key}"
            )

            if "```mermaid" in section_text:
                ev_type = "mermaid"
            elif "|" in section_text and section_text.count("|") > 4:
                ev_type = "table"
            else:
                ev_type = "section"

            evidence_units.append({
                "project_name": project_name,
                "project_id": project_id,
                "evidence_id": evidence_id,
                "source_file": file_rec["file_path"],
                "source_dir": str(Path(file_rec["file_path"]).parent),
                "document_group": file_rec["document_group"],
                "workbook_name": file_rec["workbook_name"],
                "sheet_name": file_rec["sheet_name"],
                "sheet_index": file_rec["sheet_index"],
                "sheet_type": file_rec["sheet_type"],
                "section_title": section["title"],
                "evidence_type": ev_type,
                "evidence_text": section_text[:2000],
                "markdown_anchor": f"#{section_key}",
                "line_start": section["start"],
                "line_end": section.get("end", section["start"]),
                "confidence": 1.0,
            })

    return evidence_units
