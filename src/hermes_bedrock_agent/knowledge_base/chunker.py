"""Split parsed markdown into semantic chunks with metadata enrichment."""

from __future__ import annotations

import csv
import hashlib
import logging
import re
from pathlib import Path
from typing import Optional

from ..config import Config, config as _default_config
from .schemas import Chunk

logger = logging.getLogger(__name__)

_CHUNK_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("flowchart", ["flowchart", "フローチャート", "API呼出順序", "api call", "sequence", "flow"]),
    ("data_condition", ["データ取得条件", "data condition", "取得条件", "where clause", "抽出条件"]),
    ("business_rule", ["business rule", "ビジネスルール", "条件", "注意事項", "補足", "special", "注記"]),
    ("api_spec", ["api", "endpoint", "REST", "HTTP", "GET", "POST", "PUT", "DELETE", "request", "response"]),
    ("mapping_table", ["マッピング", "mapping", "フィールド", "field", "項目名", "送信元", "送信先"]),
    ("overview", ["overview", "概要", "document", "change history", "変更履歴", "summary", "一覧"]),
]

_SYSTEM_KEYWORDS = ["SAP", "DataSpider", "ANDPAD", "S4/HANA", "S4HANA", "NTT DATA", "中間F", "中間ファイル"]
_API_PATTERN = re.compile(
    r"(?:発注作成|発注変更|発注取消|発注一覧取得|発注明細|発注ステータス変更"
    r"|納品一覧取得|納品明細|納品のデータ編集|納品のキャンセル|納品キャンセル"
    r"|請負済の取り下げ|請負済のデータ編集|発注情報登録|SAP_EDI_\w+)"
)
_FIELD_PATTERN = re.compile(r"\|\s*(\d+)\s*\|\s*([^\|]{3,50}?)\s*\|")


def _extract_systems(text: str) -> list[str]:
    found = []
    for kw in _SYSTEM_KEYWORDS:
        if kw.lower() in text.lower() and kw not in found:
            found.append(kw)
    return found


def _extract_apis(text: str) -> list[str]:
    return list(dict.fromkeys(_API_PATTERN.findall(text)))


def _extract_fields(text: str) -> list[str]:
    seen: list[str] = []
    for _, name in _FIELD_PATTERN.findall(text):
        name = name.strip()
        if name and name not in seen and not name.startswith("-") and len(name) > 1:
            seen.append(name)
        if len(seen) >= 20:
            break
    return seen


def _infer_chunk_type(text: str, sheet_name: str = "") -> str:
    combined = (text + " " + sheet_name).lower()
    for ctype, keywords in _CHUNK_TYPE_RULES:
        if any(kw.lower() in combined for kw in keywords):
            return ctype
    return "overview"


def _split_into_chunks(markdown: str, max_size: int, min_size: int) -> list[str]:
    raw_sections = re.split(r"(?m)^(#{1,3} .+)", markdown)
    sections: list[str] = []
    current = ""
    for part in raw_sections:
        if re.match(r"^#{1,3} ", part):
            if current.strip():
                sections.append(current.strip())
            current = part + "\n"
        else:
            current += part
    if current.strip():
        sections.append(current.strip())

    chunks: list[str] = []
    for section in sections:
        if len(section) <= max_size:
            if len(section) >= min_size:
                chunks.append(section)
        else:
            chunks.extend(_split_large_section(section, max_size, min_size))
    return chunks


def _split_large_section(text: str, max_size: int, min_size: int) -> list[str]:
    lines = text.split("\n")
    chunks: list[str] = []
    current_lines: list[str] = []
    in_table = False

    def flush() -> None:
        block = "\n".join(current_lines).strip()
        if len(block) >= min_size:
            chunks.append(block)
        current_lines.clear()

    for line in lines:
        is_table_line = line.lstrip().startswith("|")
        if is_table_line:
            in_table = True
        elif in_table and not is_table_line:
            in_table = False
        current_lines.append(line)
        current_text = "\n".join(current_lines)
        if not in_table and len(current_text) >= max_size and line.strip() == "":
            flush()

    remainder = "\n".join(current_lines).strip()
    if remainder:
        if chunks and len(remainder) < min_size:
            last = chunks.pop()
            merged = last + "\n\n" + remainder
            if len(merged) <= max_size * 1.5:
                chunks.append(merged.strip())
            else:
                chunks.append(last)
                if len(remainder) >= min_size:
                    chunks.append(remainder)
        elif len(remainder) >= min_size:
            chunks.append(remainder)
    return chunks


def _build_related_sheet_index(cross_summary: str) -> dict[int, list[int]]:
    index: dict[int, list[int]] = {}
    for para in cross_summary.split("\n\n"):
        refs = list(set(int(r) for r in re.findall(r"[Ss]heet[_\s]?(\d{2})", para)))
        for s in refs:
            existing = index.get(s, [])
            for other in refs:
                if other != s and other not in existing:
                    existing.append(other)
            index[s] = existing
    return index


def build_chunks(
    vlm_parsed_dir: Path,
    sheet_name_mapping_csv: Optional[Path],
    workbook_name: str,
    s3_bucket: str,
    s3_pdf_prefix: str,
    s3_vlm_prefix: str,
    s3_excel_key: str,
    output_path: Path,
    cfg: Optional[Config] = None,
    project_id: str = "",
) -> list[Chunk]:
    """Read all parsed markdown files, split into chunks, write chunks.jsonl."""
    cfg = cfg or _default_config
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load sheet name mapping
    sheet_mapping: dict[int, dict[str, str]] = {}
    if sheet_name_mapping_csv and sheet_name_mapping_csv.exists():
        with open(sheet_name_mapping_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                idx_0 = int(row["sheet_index"])
                sheet_mapping[idx_0 + 1] = {
                    "original_sheet_name": row["original_sheet_name"],
                    "safe_pdf_filename": row.get("safe_pdf_filename", ""),
                }

    cross_path = vlm_parsed_dir / "cross_sheet_summary.md"
    cross_text = cross_path.read_text(encoding="utf-8") if cross_path.exists() else ""
    related_index = _build_related_sheet_index(cross_text)

    all_chunks: list[Chunk] = []

    for sheet_1 in range(1, 28):
        nn = f"{sheet_1:02d}"
        md_path = vlm_parsed_dir / f"sheet_{nn}.md"
        if not md_path.exists():
            continue
        sheet_name = sheet_mapping.get(sheet_1, {}).get("original_sheet_name", f"sheet_{nn}")
        markdown = md_path.read_text(encoding="utf-8")
        if not markdown.strip():
            continue

        text_chunks = _split_into_chunks(markdown, cfg.chunk_max_chars, cfg.chunk_min_chars)
        related = related_index.get(sheet_1, [])

        for i, chunk_text in enumerate(text_chunks):
            chunk_type = _infer_chunk_type(chunk_text, sheet_name)
            systems = _extract_systems(chunk_text)
            apis = _extract_apis(chunk_text)
            fields = _extract_fields(chunk_text)
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:12]
            chunk_id = f"sheet{nn}_chunk{i:03d}_{content_hash}"
            systems_str = ", ".join(systems) if systems else "SAP, DataSpider, ANDPAD"
            embedding_text = f"シート: {sheet_name} | タイプ: {chunk_type} | システム: {systems_str}\n\n{chunk_text}"

            all_chunks.append(Chunk(
                chunk_id=chunk_id,
                content=chunk_text,
                chunk_type=chunk_type,
                sheet_index=sheet_1,
                sheet_name=sheet_name,
                workbook_name=workbook_name,
                source_pdf_s3_path=f"s3://{s3_bucket}/{s3_pdf_prefix}/sheet_{nn}.pdf",
                source_excel_s3_path=f"s3://{s3_bucket}/{s3_excel_key}",
                source_markdown_s3_path=f"s3://{s3_bucket}/{s3_vlm_prefix}/sheet_{nn}.md",
                related_sheets=related,
                systems=systems,
                apis=apis,
                fields=fields,
                embedding_text=embedding_text,
                project_id=project_id,
            ))

        logger.info("Sheet %s (%s): %d chunks", nn, sheet_name, len(text_chunks))

    if cross_text.strip():
        cross_chunks = _split_into_chunks(cross_text, cfg.chunk_max_chars, cfg.chunk_min_chars)
        for i, chunk_text in enumerate(cross_chunks):
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:12]
            chunk_id = f"cross_chunk{i:03d}_{content_hash}"
            systems = _extract_systems(chunk_text)
            apis = _extract_apis(chunk_text)
            embedding_text = (
                f"シート: クロスシートサマリー | タイプ: cross_sheet_summary | "
                f"システム: {', '.join(systems) if systems else 'SAP, DataSpider, ANDPAD'}\n\n{chunk_text}"
            )
            all_chunks.append(Chunk(
                chunk_id=chunk_id, content=chunk_text, chunk_type="cross_sheet_summary",
                sheet_index=0, sheet_name="cross_sheet_summary", workbook_name=workbook_name,
                source_pdf_s3_path="",
                source_excel_s3_path=f"s3://{s3_bucket}/{s3_excel_key}",
                source_markdown_s3_path=f"s3://{s3_bucket}/{s3_vlm_prefix}/cross_sheet_summary.md",
                related_sheets=list(range(1, 28)),
                systems=systems, apis=apis, fields=[],
                embedding_text=embedding_text,
                project_id=project_id,
            ))
        logger.info("cross_sheet_summary: %d chunks", len(cross_chunks))

    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(chunk.model_dump_json() + "\n")

    logger.info("Dataset built: %d total chunks → %s", len(all_chunks), output_path)
    return all_chunks


def load_chunks(path: Path) -> list[Chunk]:
    chunks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(Chunk.model_validate_json(line))
    return chunks
