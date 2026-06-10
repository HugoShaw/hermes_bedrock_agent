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
    r"|請負済の取り下げ|請負済のデータ編集|発注情報登録|SAP_EDI_\w+)")
_FIELD_PATTERN = re.compile(r"\|\s*(\d+)\s*\|\s*([^\|]{3,50}?)\s*\|")
_FIELD_CODE_PATTERN = re.compile(r"^### .+?\(`([A-Z]{2}\d{7})`\)", re.MULTILINE)
_RE_SECTION = re.compile(r"^## .+")
_RE_FIELD = re.compile(r"^### .+")
_RE_VERSION = re.compile(r"^## Ver.+変更", re.IGNORECASE)
_RE_TABLE = re.compile(r"^\|.+\|")
_RE_FENCE = re.compile(r"^```")
_RE_QUOTE = re.compile(r"^> ")
_RE_META = re.compile(r"^\*\*.+\*\*")
_STRUCTURE_RES = [re.compile(r"^# .+"), _RE_SECTION, _RE_FIELD, _RE_TABLE, _RE_FENCE, _RE_QUOTE]


def _extract_systems(text: str) -> list[str]:
    lower = text.lower()
    return [kw for kw in _SYSTEM_KEYWORDS if kw.lower() in lower]

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
    if not seen:
        for m in _FIELD_CODE_PATTERN.finditer(text):
            code = m.group(1)
            if code not in seen:
                seen.append(code)
            if len(seen) >= 20:
                break
    return seen

def _extract_field_codes(text: str) -> list[str]:
    """Extract field codes in backtick format: ### Name (`CODE`)."""
    return list(dict.fromkeys(_FIELD_CODE_PATTERN.findall(text)))

def _extract_section_name(text: str) -> str:
    """Extract the first ## section heading from chunk text."""
    m = _RE_SECTION.search(text)
    return m.group(0).lstrip("# ").strip() if m else ""

def _infer_chunk_type(text: str, sheet_name: str = "") -> str:
    combined = (text + " " + sheet_name).lower()
    for ctype, keywords in _CHUNK_TYPE_RULES:
        if any(kw.lower() in combined for kw in keywords):
            return ctype
    return "overview"

def _parse_semantic_blocks(markdown: str) -> list[dict]:
    """Parse markdown into semantic blocks (type, content, level)."""
    lines, blocks = markdown.split("\n"), []
    i, n, first_section = 0, len(lines), False
    while i < n:
        line = lines[i]
        if _RE_FENCE.match(line):
            bl = [line]; i += 1
            while i < n and not _RE_FENCE.match(lines[i]):
                bl.append(lines[i]); i += 1
            if i < n:
                bl.append(lines[i]); i += 1
            blocks.append({"type": "code", "content": "\n".join(bl), "level": 2}); continue
        if re.match(r"^# .+", line) and not first_section:
            blocks.append({"type": "title", "content": line, "level": 0}); i += 1; continue
        if _RE_VERSION.match(line):
            first_section = True; bl = [line]; i += 1
            while i < n and not _RE_SECTION.match(lines[i]) and not re.match(r"^# ", lines[i]):
                bl.append(lines[i]); i += 1
            blocks.append({"type": "version", "content": "\n".join(bl), "level": 1}); continue
        if _RE_SECTION.match(line):
            first_section = True
            blocks.append({"type": "section", "content": line, "level": 1}); i += 1; continue
        if _RE_FIELD.match(line):
            bl = [line]; i += 1
            while i < n and not _RE_FIELD.match(lines[i]) and not _RE_SECTION.match(lines[i]) and not re.match(r"^# ", lines[i]):
                bl.append(lines[i]); i += 1
            blocks.append({"type": "field", "content": "\n".join(bl), "level": 2}); continue
        if _RE_TABLE.match(line):
            bl = [line]; i += 1
            while i < n and _RE_TABLE.match(lines[i]):
                bl.append(lines[i]); i += 1
            blocks.append({"type": "table", "content": "\n".join(bl), "level": 2}); continue
        if _RE_QUOTE.match(line):
            bl = [line]; i += 1
            while i < n and _RE_QUOTE.match(lines[i]):
                bl.append(lines[i]); i += 1
            blocks.append({"type": "blockquote", "content": "\n".join(bl), "level": 2}); continue
        if _RE_META.match(line) and not first_section:
            blocks.append({"type": "metadata", "content": line, "level": 0}); i += 1; continue
        if line.strip():
            bl = [line]; i += 1
            while i < n:
                l = lines[i]
                if not l.strip():
                    i += 1; break
                if any(r.match(l) for r in _STRUCTURE_RES) or (_RE_META.match(l) and not first_section):
                    break
                bl.append(l); i += 1
            blocks.append({"type": "text", "content": "\n".join(bl), "level": 2}); continue
        i += 1
    return blocks


def _split_oversized(text: str, max_size: int, min_size: int, header: str) -> list[str]:
    """Split oversized block at paragraph boundaries, falling back to line breaks."""
    prefix = (header + "\n\n") if header else ""
    plen = len(prefix)

    def _emit(parts: list[str], joiner: str) -> str:
        ct = (prefix + joiner.join(parts)) if prefix and not parts[0].startswith("## ") else joiner.join(parts)
        return ct.strip()

    paragraphs = re.split(r"\n\n+", text)
    use_lines = len(paragraphs) <= 2 and len(text) > max_size
    items = text.split("\n") if use_lines else [p.strip() for p in paragraphs if p.strip()]
    joiner = "\n" if use_lines else "\n\n"

    chunks: list[str] = []
    cur: list[str] = []
    cur_size = plen if use_lines else 0
    for item in items:
        isz = len(item) + (1 if use_lines else 2)
        limit = max_size if use_lines else (max_size - plen)
        if cur and (cur_size + isz) > limit:
            result = _emit(cur, joiner)
            if len(result) >= min_size:
                chunks.append(result)
            cur, cur_size = [item], (plen + isz) if use_lines else isz
        else:
            cur.append(item); cur_size += isz
    if cur:
        result = _emit(cur, joiner)
        if len(result) >= min_size:
            chunks.append(result)
    return chunks


def _split_semantic(markdown: str, max_size: int, min_size: int, target: int = 0) -> list[str]:
    """Split markdown respecting semantic block boundaries."""
    blocks = _parse_semantic_blocks(markdown)
    if not blocks:
        return [markdown.strip()] if len(markdown.strip()) >= min_size else []
    sem_max = max_size
    target = target or max_size // 2
    chunks: list[str] = []
    section_hdr, buf, buf_size = "", [], 0

    def flush():
        nonlocal buf, buf_size
        if buf:
            text = "\n\n".join(buf).strip()
            if len(text) >= min_size:
                chunks.append(text)
        buf.clear(); buf_size = 0

    def add(content: str):
        nonlocal buf, buf_size
        if section_hdr and not buf and not content.startswith(("## ", "# ")):
            buf.append(section_hdr); buf_size = len(section_hdr) + 2
        if buf and (buf_size + len(content) + 2) > target:
            flush()
            if section_hdr and not content.startswith(("## ", "# ")):
                buf.append(section_hdr); buf_size = len(section_hdr) + 2
        buf.append(content); buf_size += len(content) + 2

    for block in blocks:
        content = block["content"].strip()
        if not content:
            continue
        bt = block["type"]
        if bt == "section":
            flush(); section_hdr = content; buf.append(content); buf_size = len(content) + 2
        elif bt == "version":
            flush()
            if len(content) > sem_max:
                chunks.extend(_split_oversized(content, sem_max, min_size, ""))
            elif len(content) >= min_size:
                chunks.append(content)
        elif bt in ("table", "code", "blockquote") and len(content) > sem_max:
            flush(); chunks.extend(_split_oversized(content, sem_max, min_size, section_hdr))
        else:
            add(content)
    flush()

    # Fallback: if no chunks passed min_size but whole doc does, emit as single chunk
    if not chunks and len(markdown.strip()) >= min_size:
        chunks = [markdown.strip()]

    return chunks


def _split_fixed(markdown: str, max_size: int, min_size: int) -> list[str]:
    """Original fixed-size chunking — splits by headers and merges by char limits."""
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
    lines, chunks, current_lines, in_table = text.split("\n"), [], [], False
    def flush():
        block = "\n".join(current_lines).strip()
        if len(block) >= min_size:
            chunks.append(block)
        current_lines.clear()
    for line in lines:
        is_tbl = line.lstrip().startswith("|")
        if is_tbl: in_table = True
        elif in_table and not is_tbl: in_table = False
        current_lines.append(line)
        if not in_table and len("\n".join(current_lines)) >= max_size and line.strip() == "":
            flush()
    remainder = "\n".join(current_lines).strip()
    if remainder:
        if chunks and len(remainder) < min_size:
            last = chunks.pop()
            merged = last + "\n\n" + remainder
            if len(merged) <= max_size * 1.5: chunks.append(merged.strip())
            else:
                chunks.append(last)
                if len(remainder) >= min_size: chunks.append(remainder)
        elif len(remainder) >= min_size:
            chunks.append(remainder)
    return chunks

def _split_into_chunks(markdown: str, max_size: int, min_size: int, mode: str = "fixed", target: int = 0) -> list[str]:
    """Dispatch to semantic or fixed chunking based on mode."""
    if mode == "semantic":
        return _split_semantic(markdown, max_size, min_size, target=target)
    return _split_fixed(markdown, max_size, min_size)


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

    sheet_mapping: dict[int, dict[str, str]] = {}
    if sheet_name_mapping_csv and sheet_name_mapping_csv.exists():
        with open(sheet_name_mapping_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                idx_0 = int(row["sheet_index"])
                sheet_mapping[idx_0 + 1] = {
                    "original_sheet_name": row["original_sheet_name"],
                    "safe_pdf_filename": row.get("safe_pdf_filename", ""),
                }

    cross_path = vlm_parsed_dir / "cross_sheet_summary.md"
    cross_text = cross_path.read_text(encoding="utf-8") if cross_path.exists() else ""
    related_index = _build_related_sheet_index(cross_text)

    all_chunks: list[Chunk] = []
    mode = cfg.chunk_mode
    max_chars = cfg.chunk_semantic_max_chars if mode == "semantic" else cfg.chunk_max_chars
    min_chars = cfg.chunk_min_chars
    target_chars = cfg.chunk_semantic_group_target

    sheet_indices: list[int] = []
    for sf in sorted(vlm_parsed_dir.glob("sheet_*.md")):
        m = re.match(r"sheet_(\d+)\.md$", sf.name)
        if m:
            sheet_indices.append(int(m.group(1)))

    for sheet_1 in sheet_indices:
        nn = f"{sheet_1:02d}"
        md_path = vlm_parsed_dir / f"sheet_{nn}.md"
        if not md_path.exists():
            continue
        sheet_name = sheet_mapping.get(sheet_1, {}).get("original_sheet_name", f"sheet_{nn}")
        markdown = md_path.read_text(encoding="utf-8")
        if not markdown.strip():
            continue

        text_chunks = _split_into_chunks(markdown, max_chars, min_chars, mode=mode, target=target_chars)
        related = related_index.get(sheet_1, [])

        for i, chunk_text in enumerate(text_chunks):
            chunk_type = _infer_chunk_type(chunk_text, sheet_name)
            systems = _extract_systems(chunk_text)
            apis = _extract_apis(chunk_text)
            fields = _extract_fields(chunk_text)
            field_codes = _extract_field_codes(chunk_text)
            section_name = _extract_section_name(chunk_text)
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:12]
            chunk_id = f"sheet{nn}_chunk{i:03d}_{content_hash}"
            systems_str = ", ".join(systems) if systems else ""
            embedding_text = f"シート: {sheet_name} | タイプ: {chunk_type} | システム: {systems_str}\n\n{chunk_text}"
            all_chunks.append(Chunk(
                chunk_id=chunk_id, content=chunk_text, chunk_type=chunk_type,
                sheet_index=sheet_1, sheet_name=sheet_name, workbook_name=workbook_name,
                source_pdf_s3_path=f"s3://{s3_bucket}/{s3_pdf_prefix}/sheet_{nn}.pdf",
                source_excel_s3_path=f"s3://{s3_bucket}/{s3_excel_key}",
                source_markdown_s3_path=f"s3://{s3_bucket}/{s3_vlm_prefix}/sheet_{nn}.md",
                related_sheets=related, systems=systems, apis=apis, fields=fields,
                embedding_text=embedding_text, project_id=project_id,
                content_hash=content_hash, source_markdown_file=str(md_path),
                chunk_mode=mode, section_name=section_name, field_codes=field_codes,
            ))
        logger.info("Sheet %s (%s): %d chunks", nn, sheet_name, len(text_chunks))

    if cross_text.strip():
        cross_chunks = _split_into_chunks(cross_text, max_chars, min_chars, mode=mode, target=target_chars)
        for i, chunk_text in enumerate(cross_chunks):
            content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:12]
            chunk_id = f"cross_chunk{i:03d}_{content_hash}"
            systems = _extract_systems(chunk_text)
            apis = _extract_apis(chunk_text)
            field_codes = _extract_field_codes(chunk_text)
            section_name = _extract_section_name(chunk_text)
            embedding_text = (
                f"シート: クロスシートサマリー | タイプ: cross_sheet_summary | "
                f"システム: {', '.join(systems) if systems else ''}\n\n{chunk_text}"
            )
            all_chunks.append(Chunk(
                chunk_id=chunk_id, content=chunk_text, chunk_type="cross_sheet_summary",
                sheet_index=0, sheet_name="cross_sheet_summary", workbook_name=workbook_name,
                source_pdf_s3_path="",
                source_excel_s3_path=f"s3://{s3_bucket}/{s3_excel_key}",
                source_markdown_s3_path=f"s3://{s3_bucket}/{s3_vlm_prefix}/cross_sheet_summary.md",
                related_sheets=sheet_indices, systems=systems, apis=apis, fields=[],
                embedding_text=embedding_text, project_id=project_id,
                content_hash=content_hash, source_markdown_file=str(cross_path),
                chunk_mode=mode, section_name=section_name, field_codes=field_codes,
            ))
        logger.info("cross_sheet_summary: %d chunks", len(cross_chunks))

    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in all_chunks:
            f.write(chunk.model_dump_json() + "\n")
    logger.info("Dataset built: %d total chunks → %s", len(all_chunks), output_path)
    return all_chunks


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from markdown."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end > 0:
            import yaml
            fm = yaml.safe_load(text[4:end])
            body = text[end + 5:].lstrip("\n")
            return fm or {}, body
    return {}, text


_SINGLE_CHUNK_TYPES = {"images", "mermaid"}


def build_chunks_from_parsed_dir(
    parsed_dir: Path,
    project_id: str = "",
    output_path: Optional[Path] = None,
    cfg: Optional[Config] = None,
) -> list[Chunk]:
    """Build chunks from the new standardized parsed/ directory.

    Scans parsed/docs/, parsed/csv/, parsed/images/, parsed/code/,
    parsed/excel/, parsed/mermaid/ subdirectories.
    Reads YAML frontmatter for metadata. Applies semantic chunking to all types.
    """
    cfg = cfg or _default_config
    all_chunks: list[Chunk] = []
    mode = cfg.chunk_mode
    max_chars = cfg.chunk_semantic_max_chars if mode == "semantic" else cfg.chunk_max_chars
    min_chars = cfg.chunk_min_chars
    target_chars = cfg.chunk_semantic_group_target

    for subdir in sorted(parsed_dir.iterdir()):
        if not subdir.is_dir():
            continue
        type_name = subdir.name

        for md_file in sorted(subdir.rglob("*.md")):
            text = md_file.read_text(encoding="utf-8")
            if not text.strip():
                continue

            frontmatter, body = _parse_frontmatter(text)
            if not body.strip():
                continue

            source_file = frontmatter.get("source_file", "")
            source_type = frontmatter.get("source_type", type_name)
            parser_type = frontmatter.get("parser_type", "")
            document_role = frontmatter.get("document_role", "")
            content_hash_fm = frontmatter.get("content_hash", "")

            if type_name in _SINGLE_CHUNK_TYPES:
                text_chunks = [body.strip()]
            else:
                text_chunks = _split_into_chunks(body, max_chars, min_chars, mode=mode, target=target_chars)

            for i, chunk_text in enumerate(text_chunks):
                chunk_type = _infer_chunk_type(chunk_text)
                systems = _extract_systems(chunk_text)
                apis = _extract_apis(chunk_text)
                fields = _extract_fields(chunk_text)
                field_codes = _extract_field_codes(chunk_text)
                section_name = _extract_section_name(chunk_text)
                content_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:12]
                chunk_id = f"{type_name}_{md_file.stem}_chunk{i:03d}_{content_hash}"
                systems_str = ", ".join(systems) if systems else ""
                embedding_text = (
                    f"ソース: {source_file or md_file.stem} | タイプ: {chunk_type} | "
                    f"システム: {systems_str}\n\n{chunk_text}"
                )
                all_chunks.append(Chunk(
                    chunk_id=chunk_id,
                    content=chunk_text,
                    chunk_type=chunk_type,
                    source_file=source_file,
                    source_type=source_type,
                    parser_type=parser_type,
                    document_role=document_role,
                    project_id=project_id,
                    content_hash=content_hash,
                    source_markdown_file=str(md_file),
                    chunk_mode=mode,
                    section_name=section_name,
                    workbook_name=type_name,
                    systems=systems,
                    apis=apis,
                    fields=fields,
                    field_codes=field_codes,
                    embedding_text=embedding_text,
                ))

        logger.info("parsed/%s: %d chunks",
                    type_name,
                    sum(1 for c in all_chunks if c.workbook_name == type_name))

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for chunk in all_chunks:
                f.write(chunk.model_dump_json() + "\n")

    logger.info("build_chunks_from_parsed_dir: %d total chunks from %s", len(all_chunks), parsed_dir)
    return all_chunks


def load_chunks(path: Path) -> list[Chunk]:
    chunks = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(Chunk.model_validate_json(line))
    return chunks
