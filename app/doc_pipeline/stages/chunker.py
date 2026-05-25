"""Stage 6: Semantic chunking — split markdown into Chunk objects with metadata.

Ported from app/dual_rag/dataset_builder.py with generalised workbook parameters.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Optional

from ..config import PipelineConfig, config as _default_config
from ..models import Chunk, ParseResult

logger = logging.getLogger(__name__)

# ── Chunk-type detection ──────────────────────────────────────────────────────

_CHUNK_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("flowchart", ["flowchart", "フローチャート", "API呼出順序", "api call", "sequence", "flow", "mermaid"]),
    ("data_condition", ["データ取得条件", "data condition", "取得条件", "where clause", "抽出条件", "判断"]),
    ("business_rule", ["business rule", "ビジネスルール", "条件", "注意事項", "補足", "special", "注記", "key findings", "modification"]),
    ("api_spec", ["api", "endpoint", "REST", "HTTP", "GET", "POST", "PUT", "DELETE", "request", "response", "token"]),
    ("mapping_table", ["マッピング", "mapping", "フィールド", "field", "項目名", "送信元", "送信先", "target", "source"]),
    ("overview", ["overview", "概要", "document", "change history", "変更履歴", "summary", "一覧", "meta", "architecture"]),
]

_SYSTEM_KEYWORDS = [
    "SAP", "DataSpider", "ANDPAD", "S4/HANA", "S4HANA", "NTT DATA",
    "中間F", "中間ファイル", "DSS", "CSV", "REST", "工事EDI", "発注", "納品",
]
_API_PATTERN = re.compile(
    r"(?:発注作成|発注変更|発注取消|発注一覧取得|発注明細|発注ステータス変更"
    r"|納品一覧取得|納品明細|納品のデータ編集|納品のキャンセル|納品キャンセル"
    r"|請負済の取り下げ|請負済のデータ編集|発注情報登録|SAP_EDI_\w+)"
)


def _infer_chunk_type(text: str, sheet_name: str = "") -> str:
    combined = (text + " " + sheet_name).lower()
    for ctype, keywords in _CHUNK_TYPE_RULES:
        if any(kw.lower() in combined for kw in keywords):
            return ctype
    return "overview"


def _extract_systems(text: str) -> list[str]:
    found: list[str] = []
    for kw in _SYSTEM_KEYWORDS:
        if kw in text and kw not in found:
            found.append(kw)
    return found


def _extract_apis(text: str) -> list[str]:
    return list(dict.fromkeys(_API_PATTERN.findall(text)))


# ── Splitting logic (ported from dataset_builder.py) ─────────────────────────

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
            chunks.append(merged.strip() if len(merged) <= max_size * 1.5 else last)
            if len(merged) > max_size * 1.5 and len(remainder) >= min_size:
                chunks.append(remainder)
        elif len(remainder) >= min_size:
            chunks.append(remainder)

    return chunks


def _split_markdown(markdown: str, max_size: int, min_size: int) -> list[str]:
    """Split markdown at ## headings; keep tables intact; respect size limits."""
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


# ── Public API ────────────────────────────────────────────────────────────────

def chunk_parse_result(
    result: ParseResult,
    workbook_name: str,
    source_excel_s3_path: str,
    source_pdf_s3_prefix: str,
    source_md_s3_prefix: str,
    cfg: Optional[PipelineConfig] = None,
) -> list[Chunk]:
    """Convert a ParseResult into a list of Chunk objects ready for embedding."""
    cfg = cfg or _default_config
    sheet_idx = result.sheet_info.index
    sheet_name = result.sheet_info.name
    nn = f"{sheet_idx:02d}"

    text_chunks = _split_markdown(result.markdown, cfg.chunk_max_chars, cfg.chunk_min_chars)

    chunks: list[Chunk] = []
    for i, chunk_text in enumerate(text_chunks):
        chunk_type = _infer_chunk_type(chunk_text, sheet_name)
        systems = _extract_systems(chunk_text)
        apis = _extract_apis(chunk_text)

        content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:12]
        chunk_id = f"sheet{nn}_chunk{i:03d}_{content_hash}"

        systems_str = ", ".join(systems) if systems else "SAP, DataSpider, ANDPAD"
        embedding_text = (
            f"シート: {sheet_name} | タイプ: {chunk_type} | システム: {systems_str}\n\n"
            + chunk_text
        )

        chunks.append(
            Chunk(
                id=chunk_id,
                text=chunk_text,
                embedding_text=embedding_text,
                chunk_type=chunk_type,
                sheet_index=sheet_idx,
                sheet_name=sheet_name,
                workbook_name=workbook_name,
                source_pdf_s3_path=f"{source_pdf_s3_prefix}/sheet_{nn}.pdf",
                source_excel_s3_path=source_excel_s3_path,
                source_markdown_s3_path=f"{source_md_s3_prefix}/sheet_{nn}.md",
                systems="|".join(systems),
                apis="|".join(apis),
                related_sheets="",
            )
        )

    return chunks


def chunk_all_results(
    results: list[ParseResult],
    workbook_name: str,
    source_excel_s3_path: str,
    source_pdf_s3_prefix: str,
    source_md_s3_prefix: str,
    cfg: Optional[PipelineConfig] = None,
) -> list[Chunk]:
    """Chunk all ParseResults for a workbook."""
    cfg = cfg or _default_config
    all_chunks: list[Chunk] = []

    for result in results:
        chunks = chunk_parse_result(
            result,
            workbook_name=workbook_name,
            source_excel_s3_path=source_excel_s3_path,
            source_pdf_s3_prefix=source_pdf_s3_prefix,
            source_md_s3_prefix=source_md_s3_prefix,
            cfg=cfg,
        )
        logger.info(
            "  Sheet %02d (%s): %d chunks",
            result.sheet_info.index, result.sheet_info.name, len(chunks),
        )
        all_chunks.extend(chunks)

    return all_chunks
