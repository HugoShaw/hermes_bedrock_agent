"""CSV parser: read CSV/TSV with encoding detection, output as structured markdown.

Designed for enterprise API specification CSVs (e.g., 奉行クラウドAPI data format sheets)
that contain structured field definitions grouped by sections.

Output is optimized for:
  - Semantic chunking (sections split by ## headers → natural chunk boundaries)
  - Vector embedding (field descriptions as readable prose → better similarity search)
  - Graph extraction (explicit field→property relationships → clean node/edge extraction)
  - LLM understanding (structured but readable → good context for RAG answers)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import chardet
import pandas as pd

from ..models.document import ParsedDocument, SourceType, generate_doc_id
from .base_parser import BaseParser

logger = logging.getLogger(__name__)

ENCODINGS_TO_TRY = ["utf-8", "utf-8-sig", "shift_jis", "cp932", "GB18030", "gbk", "gb2312", "euc-jp", "latin-1"]

# Section header pattern: 【...】
_SECTION_HEADER_RE = re.compile(r"^【(.+?)】$")

# Known header keywords for detecting the column header row
_HEADER_KEYWORDS = {"項目名", "項目記号", "桁数", "種別", "必須", "受入", "出力", "名称出力", "抽出", "並び順", "備考"}

# Headers for table-of-contents / change-history sheets
_TOC_KEYWORDS = {"ページ", "項目名", "変更内容"}


class CsvParser(BaseParser):
    """Parse CSV/TSV files with encoding detection and semantic structure extraction."""

    @property
    def name(self) -> str:
        return "csv_parser"

    def can_handle(self, path: Path, source_type: SourceType) -> bool:
        return source_type == SourceType.CSV

    def parse(
        self,
        path: Path,
        project_id: str,
        config: dict[str, Any] | None = None,
        relative_path: str = "",
    ) -> list[ParsedDocument]:
        logger.info("Parsing CSV: %s", path.name)

        encoding = self._detect_encoding(path)
        separator = "\t" if path.suffix.lower() == ".tsv" else ","

        df = self._read_csv_robust(path, encoding, separator)

        rel = relative_path or path.name

        if df is None or df.empty:
            return [ParsedDocument(
                doc_id=generate_doc_id(project_id, rel),
                project_id=project_id,
                source_path=str(path),
                source_type=SourceType.CSV,
                title=path.stem,
                content_markdown="*Empty or unreadable CSV file*",
                metadata={"error": "empty_or_unreadable", "encoding_detected": encoding},
                parse_method="csv_structured",
            )]

        # Detect structure and produce semantic markdown
        content, detected_title = self._structured_to_markdown(df, path.stem)

        metadata: dict[str, Any] = {
            "encoding": encoding,
            "rows": len(df),
            "columns": len(df.columns),
            "separator": separator,
            "parse_strategy": "structured_sections",
        }

        return [ParsedDocument(
            doc_id=generate_doc_id(project_id, rel),
            project_id=project_id,
            source_path=str(path),
            source_type=SourceType.CSV,
            title=detected_title or path.stem,
            content_markdown=content,
            metadata=metadata,
            language=_detect_language(df),
            parse_method="csv_structured",
        )]

    # ─────────────────────────────────────────────────────────────────────
    # Encoding detection with improved fallback for Japanese CSVs
    # ─────────────────────────────────────────────────────────────────────

    def _detect_encoding(self, path: Path) -> str:
        raw = path.read_bytes()[:10000]
        result = chardet.detect(raw)
        detected = result.get("encoding", "utf-8") or "utf-8"
        confidence = result.get("confidence", 0)
        logger.debug("Chardet: %s (confidence=%.2f)", detected, confidence)

        normalized = detected.lower().replace("-", "").replace("_", "")

        # High-confidence mappings
        if normalized in ("shiftjis", "shift_jis"):
            return "shift_jis"
        if normalized in ("gb2312", "gbk", "gb18030"):
            return "GB18030"
        if "utf" in normalized and "8" in normalized:
            return "utf-8-sig"

        # Low-confidence or mis-detected encodings (common with Japanese Excel exports)
        # chardet often misdetects Japanese CSVs as cp1256/windows-1256/ISO-8859-6
        if confidence < 0.8 or normalized in ("cp1256", "windows1256", "iso88596", "ascii"):
            # Try GB18030 which is a superset that handles most CJK content
            try:
                raw_full = path.read_bytes()
                raw_full.decode("GB18030")
                logger.info("Low-confidence detection (%s/%.2f), falling back to GB18030", detected, confidence)
                return "GB18030"
            except (UnicodeDecodeError, LookupError):
                pass

        return detected

    def _read_csv_robust(self, path: Path, encoding: str, separator: str) -> pd.DataFrame | None:
        """Read CSV with robust encoding fallback. Always returns header=None, dtype=str."""
        try:
            df = pd.read_csv(path, encoding=encoding, sep=separator, header=None,
                             dtype=str, on_bad_lines="skip")
            df = df.fillna("")
            return df
        except (UnicodeDecodeError, UnicodeError, Exception) as e:
            logger.warning("Failed with encoding %s: %s — trying fallback chain", encoding, e)

        for enc in ENCODINGS_TO_TRY:
            try:
                df = pd.read_csv(path, encoding=enc, sep=separator, header=None,
                                 dtype=str, on_bad_lines="skip")
                df = df.fillna("")
                logger.info("Fallback encoding succeeded: %s", enc)
                return df
            except (UnicodeDecodeError, UnicodeError):
                continue
        return None

    # ─────────────────────────────────────────────────────────────────────
    # Structure detection and semantic markdown conversion
    # ─────────────────────────────────────────────────────────────────────

    def _structured_to_markdown(self, df: pd.DataFrame, filename: str) -> tuple[str, str]:
        """Convert DataFrame to semantically structured markdown.

        Returns (markdown_content, detected_title).

        Strategy:
        1. Find the title row (first non-empty single-value row in first 5 rows)
        2. Find the column header row (contains known keywords like 項目名, 項目記号)
        3. Split data into sections by 【...】 headers
        4. Convert each field row into a prose-style description block
        """
        # Step 1: Find title
        title = filename
        title_row_idx = -1
        for idx in range(min(5, len(df))):
            vals = [str(v).strip() for v in df.iloc[idx].values if str(v).strip()]
            if vals and len(vals) == 1 and len(vals[0]) > 2 and not vals[0].startswith("【"):
                title = vals[0]
                title_row_idx = idx
                break

        # Step 2: Find column header row
        header_row_idx = self._find_header_row(df)

        # Step 3: Determine output strategy
        if header_row_idx is not None:
            headers = [str(v).strip() for v in df.iloc[header_row_idx].values]
            # Check if this is an API spec sheet (has 項目記号/桁数/種別 etc.)
            header_set = set(h for h in headers if h)
            if header_set & {"項目記号", "桁数", "種別"}:
                return self._render_api_spec_sheet(df, title, header_row_idx, headers)
            elif header_set & _TOC_KEYWORDS and len(header_set & _TOC_KEYWORDS) >= 2:
                return self._render_change_history_sheet(df, title, header_row_idx, headers)
            else:
                return self._render_generic_structured_sheet(df, title, header_row_idx, headers)
        else:
            # No structured header found — use generic prose conversion
            return self._render_freeform_sheet(df, title, title_row_idx)

    def _find_header_row(self, df: pd.DataFrame) -> int | None:
        """Find the row that contains column headers."""
        for idx in range(min(20, len(df))):
            vals = set(str(v).strip() for v in df.iloc[idx].values if str(v).strip())
            # API spec headers
            if len(vals & _HEADER_KEYWORDS) >= 3:
                return idx
            # TOC/change history headers
            if len(vals & _TOC_KEYWORDS) >= 2:
                return idx
        return None

    # ─────────────────────────────────────────────────────────────────────
    # Rendering: API Specification Sheets (main use case)
    # ─────────────────────────────────────────────────────────────────────

    def _render_api_spec_sheet(
        self, df: pd.DataFrame, title: str, header_row_idx: int, headers: list[str]
    ) -> tuple[str, str]:
        """Render API data format specification sheets with section-based structure.

        Output format:
            # <title>
            <description note>

            ## 【Section Name】

            ### <field_name> (item_code)
            - 桁数: ...
            - 種別: ...
            - 必須: ...
            - 受入/出力/名称出力/抽出/並び順: ...
            - 備考: ...
        """
        parts: list[str] = []
        parts.append(f"# {title}")
        parts.append("")

        # Collect pre-header notes (description lines between title and header)
        for idx in range(header_row_idx):
            vals = [str(v).strip() for v in df.iloc[idx].values if str(v).strip()]
            if vals and len(vals) == 1:
                text = vals[0]
                if text != title and not text.startswith("【"):
                    parts.append(f"> {text}")
                    parts.append("")

        # Map column indices to header names
        col_map = {}
        for i, h in enumerate(headers):
            if h.strip():
                col_map[h.strip()] = i

        # Key column indices
        name_idx = col_map.get("項目名", 0)
        code_idx = col_map.get("項目記号", 1)
        digits_idx = col_map.get("桁数")
        type_idx = col_map.get("種別")
        required_idx = col_map.get("必須")
        import_idx = col_map.get("受入")
        export_idx = col_map.get("出力")
        name_output_idx = col_map.get("名称出力(_N)") or col_map.get("名称出力")
        extract_idx = col_map.get("抽出")
        sort_idx = col_map.get("並び順")
        remarks_idx = col_map.get("備考")

        current_section = None
        field_count = 0

        for idx in range(header_row_idx + 1, len(df)):
            row = [str(v).strip() for v in df.iloc[idx].values]

            # Skip entirely empty rows
            if not any(row):
                continue

            # Check for section header
            first_val = row[name_idx] if name_idx < len(row) else ""
            section_match = _SECTION_HEADER_RE.match(first_val)
            if section_match:
                current_section = section_match.group(1)
                parts.append(f"\n## 【{current_section}】\n")
                continue

            # Check if this is a field entry (has item name or item code)
            field_name = row[name_idx] if name_idx < len(row) else ""
            item_code = row[code_idx] if code_idx < len(row) else ""

            if not field_name and not item_code:
                # Continuation row — might have remarks only
                remarks = row[remarks_idx] if remarks_idx is not None and remarks_idx < len(row) else ""
                if remarks:
                    # Append to previous field's remarks
                    parts.append(f"  {remarks}")
                continue

            # This is a field definition row — render as structured entry
            field_count += 1

            # Build the field heading
            if item_code:
                parts.append(f"### {field_name} (`{item_code}`)")
            elif field_name:
                parts.append(f"### {field_name}")
            parts.append("")

            # Build property list
            props = []
            if digits_idx is not None and digits_idx < len(row) and row[digits_idx]:
                props.append(f"桁数: {row[digits_idx]}")
            if type_idx is not None and type_idx < len(row) and row[type_idx]:
                props.append(f"種別: {row[type_idx]}")
            if required_idx is not None and required_idx < len(row) and row[required_idx]:
                props.append(f"必須: {row[required_idx]}")

            # API capabilities as inline list
            caps = []
            if import_idx is not None and import_idx < len(row) and row[import_idx] == "○":
                caps.append("受入")
            if export_idx is not None and export_idx < len(row) and row[export_idx] == "○":
                caps.append("出力")
            if name_output_idx is not None and name_output_idx < len(row) and row[name_output_idx] == "○":
                caps.append("名称出力")
            if extract_idx is not None and extract_idx < len(row) and row[extract_idx] == "○":
                caps.append("抽出")
            if sort_idx is not None and sort_idx < len(row) and row[sort_idx] == "○":
                caps.append("並び順")
            if caps:
                props.append(f"対応操作: {', '.join(caps)}")

            for p in props:
                parts.append(f"- {p}")

            # Remarks (may contain embedded newlines from the CSV)
            if remarks_idx is not None and remarks_idx < len(row) and row[remarks_idx]:
                remarks_text = row[remarks_idx].replace("\\n", "\n  ")
                parts.append(f"- 備考: {remarks_text}")

            parts.append("")

        # Add summary at top
        summary_line = f"**データ項目数:** {field_count}"
        parts.insert(2, summary_line)
        parts.insert(3, "")

        return "\n".join(parts), title

    # ─────────────────────────────────────────────────────────────────────
    # Rendering: Change History / TOC Sheets
    # ─────────────────────────────────────────────────────────────────────

    def _render_change_history_sheet(
        self, df: pd.DataFrame, title: str, header_row_idx: int, headers: list[str]
    ) -> tuple[str, str]:
        """Render change history or table-of-contents sheets."""
        parts: list[str] = []
        parts.append(f"# {title}")
        parts.append("")

        # Map columns
        col_map = {}
        for i, h in enumerate(headers):
            if h.strip():
                col_map[h.strip()] = i

        page_idx = col_map.get("ページ", 0)
        item_idx = col_map.get("項目名", 1)
        change_idx = col_map.get("変更内容", 2)

        current_version = None

        for idx in range(header_row_idx + 1, len(df)):
            row = [str(v).strip() for v in df.iloc[idx].values]
            if not any(row):
                continue

            page_val = row[page_idx] if page_idx < len(row) else ""
            item_val = row[item_idx] if item_idx < len(row) else ""
            change_val = row[change_idx] if change_idx < len(row) else ""

            # Detect version headers (e.g., "Ver240328　変更内容")
            if page_val and "Ver" in page_val and "変更" in page_val:
                current_version = page_val.strip()
                parts.append(f"\n## {current_version}\n")
                continue

            # Regular entry
            if page_val or item_val or change_val:
                entry_parts = []
                if page_val:
                    entry_parts.append(f"**{page_val}**")
                if item_val:
                    entry_parts.append(item_val)
                if change_val:
                    change_text = change_val.replace("\\n", " ")
                    entry_parts.append(f"— {change_text}")
                if entry_parts:
                    parts.append(f"- {' / '.join(entry_parts)}")

        return "\n".join(parts), title

    # ─────────────────────────────────────────────────────────────────────
    # Rendering: Generic Structured Sheets (with identified headers)
    # ─────────────────────────────────────────────────────────────────────

    def _render_generic_structured_sheet(
        self, df: pd.DataFrame, title: str, header_row_idx: int, headers: list[str]
    ) -> tuple[str, str]:
        """Render sheets with recognized headers but not matching API spec pattern."""
        parts: list[str] = []
        parts.append(f"# {title}")
        parts.append("")

        # Use the header row as column names
        col_names = [h if h.strip() else f"col_{i}" for i, h in enumerate(headers)]

        for idx in range(header_row_idx + 1, len(df)):
            row = [str(v).strip() for v in df.iloc[idx].values]
            if not any(row):
                continue

            # Check for section header
            first_val = row[0] if row else ""
            section_match = _SECTION_HEADER_RE.match(first_val)
            if section_match:
                parts.append(f"\n## 【{section_match.group(1)}】\n")
                continue

            # Render as key-value pairs
            entries = []
            for i, val in enumerate(row):
                if val and i < len(col_names):
                    entries.append(f"{col_names[i]}: {val}")
            if entries:
                parts.append(f"- {' | '.join(entries)}")

        return "\n".join(parts), title

    # ─────────────────────────────────────────────────────────────────────
    # Rendering: Freeform / Cover Page Sheets
    # ─────────────────────────────────────────────────────────────────────

    def _render_freeform_sheet(
        self, df: pd.DataFrame, title: str, title_row_idx: int
    ) -> tuple[str, str]:
        """Render sheets without structured headers as flowing prose with sections."""
        parts: list[str] = []
        parts.append(f"# {title}")
        parts.append("")

        start_row = (title_row_idx + 1) if title_row_idx >= 0 else 0

        for idx in range(start_row, len(df)):
            row = [str(v).strip() for v in df.iloc[idx].values if str(v).strip()]
            if not row:
                continue

            first_val = row[0]

            # Detect section markers 【...】
            section_match = _SECTION_HEADER_RE.match(first_val)
            if section_match:
                parts.append(f"\n## 【{section_match.group(1)}】\n")
                continue

            # Detect bullet-style markers (●) — may be in first cell alone or merged
            if first_val == "●" and len(row) > 1:
                # ● is separate cell, next cell has the title
                heading_text = row[1]
                parts.append(f"\n### {heading_text}\n")
                continue
            elif first_val.startswith("●"):
                parts.append(f"\n### {first_val[1:].strip()}\n")
                continue

            # Skip rows that just repeat the title
            if len(row) == 1 and row[0] == title:
                continue

            # Regular content — join non-empty cells with space separator
            # Use " | " only when multiple cells have substantial content
            if len(row) > 1:
                text = " | ".join(row)
            else:
                text = row[0]
            parts.append(text)

        return "\n".join(parts), title


def _detect_language(df: pd.DataFrame) -> str:
    """Detect language from content sample."""
    sample_text = ""
    # Sample from first 20 rows, all columns
    for idx in range(min(20, len(df))):
        for val in df.iloc[idx].values:
            s = str(val)
            if s and s != "nan":
                sample_text += s + " "
                if len(sample_text) > 500:
                    break
        if len(sample_text) > 500:
            break

    jp_chars = sum(1 for c in sample_text if "\u3040" <= c <= "\u30FF")  # Hiragana + Katakana
    cjk_chars = sum(1 for c in sample_text if "\u4E00" <= c <= "\u9FFF")  # CJK Unified
    total = len(sample_text) if sample_text else 1

    if jp_chars / total > 0.02:
        return "ja"
    elif cjk_chars / total > 0.05:
        return "zh"
    return "en"
