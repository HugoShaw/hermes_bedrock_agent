#!/usr/bin/env python3
"""Ingest the wb2_flowchart parsed results into the dual-RAG knowledge base.

Reuses the existing pipeline modules but points to the new workbook's data.
"""
import os
import sys
import json
import csv
import hashlib
import re
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.expanduser("~/projects/hermes_bedrock_agent"))

from dotenv import load_dotenv
load_dotenv(os.path.expanduser("~/projects/hermes_bedrock_agent/.env"))

from app.dual_rag.schemas import Chunk
from app.dual_rag.config import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Config for this workbook ──────────────────────────────────────────────────
WORKBOOK_NAME = "M社様_DSSスクリプト改修概要_フローチャート"
S3_EXCEL_PATH = "s3://s3-hulftchina-rd/サンプル20260519/01_基本設計/M社様_DSSスクリプト改修概要_フローチャート.xlsx"
S3_PDF_PREFIX = "s3://s3-hulftchina-rd/outputs/wb2_flowchart/pdf"
PARSED_DIR = Path(os.path.expanduser("~/projects/hermes_bedrock_agent/outputs/wb2_flowchart/vlm_parsed"))
PDF_DIR = Path(os.path.expanduser("~/projects/hermes_bedrock_agent/outputs/wb2_flowchart/pdf"))

SHEET_NAMES = ["概要", "フローチャート"]

# ── Chunking ──────────────────────────────────────────────────────────────────
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)

_CHUNK_TYPE_RULES = [
    ("flowchart", ["flowchart", "フローチャート", "mermaid", "process flow", "decision", "branch"]),
    ("data_condition", ["データ取得条件", "data condition", "条件", "判断"]),
    ("business_rule", ["business rule", "ビジネスルール", "注意", "key findings", "modification"]),
    ("api_spec", ["api", "endpoint", "REST", "HTTP", "GET", "POST", "PUT", "DELETE", "token"]),
    ("mapping_table", ["マッピング", "mapping", "フィールド", "field", "target", "source"]),
    ("overview", ["overview", "概要", "summary", "meta", "content summary", "architecture"]),
]

_SYSTEM_KEYWORDS = ["SAP", "DataSpider", "ANDPAD", "DSS", "CSV", "REST", "工事EDI", "発注", "納品"]


def detect_chunk_type(text: str, heading: str) -> str:
    combined = f"{heading} {text[:500]}".lower()
    for ctype, keywords in _CHUNK_TYPE_RULES:
        if any(kw.lower() in combined for kw in keywords):
            return ctype
    return "overview"


def detect_systems(text: str) -> list[str]:
    return [kw for kw in _SYSTEM_KEYWORDS if kw in text]


def _make_chunk(sheet_idx: int, sheet_name: str, heading: str, content: str) -> Chunk:
    """Create a Chunk matching the exact Pydantic schema."""
    chunk_id = hashlib.md5(f"{WORKBOOK_NAME}:{sheet_idx}:{heading}".encode()).hexdigest()[:12]
    embedding_text = f"{heading}\n{content[:500]}"
    return Chunk(
        chunk_id=f"wb2fc_{chunk_id}",
        workbook_name=WORKBOOK_NAME,
        sheet_index=sheet_idx,
        sheet_name=sheet_name,
        chunk_type=detect_chunk_type(content, heading),
        content=content,
        systems=detect_systems(content),
        source_excel_s3_path=S3_EXCEL_PATH,
        source_pdf_s3_path=f"{S3_PDF_PREFIX}/sheet_{sheet_idx:02d}.pdf",
        source_markdown_s3_path=f"s3://s3-hulftchina-rd/outputs/wb2_flowchart/vlm_parsed/sheet_{sheet_idx:02d}.md",
        embedding_text=embedding_text,
    )


def split_into_chunks(md_text: str, sheet_idx: int, sheet_name: str) -> list[Chunk]:
    """Split a markdown document into semantic chunks at heading boundaries."""
    chunks = []
    
    # Find all headings
    headings = list(_HEADING_RE.finditer(md_text))
    
    if not headings:
        chunks.append(_make_chunk(sheet_idx, sheet_name, sheet_name, md_text.strip()))
        return chunks
    
    # Split at headings
    for i, match in enumerate(headings):
        heading_text = match.group(2).strip()
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(md_text)
        section_text = md_text[start:end].strip()
        
        # Skip very short sections (less than 50 chars of actual content)
        content_only = re.sub(r"^#+\s+.+$", "", section_text, flags=re.MULTILINE).strip()
        if len(content_only) < 50:
            continue
        
        # For very long sections (>3000 chars), split further
        if len(section_text) > 3000:
            sub_chunks = _split_long_section(section_text, sheet_idx, sheet_name, heading_text)
            chunks.extend(sub_chunks)
        else:
            chunks.append(_make_chunk(sheet_idx, sheet_name, heading_text, section_text))
    
    return chunks


def _split_long_section(text: str, sheet_idx: int, sheet_name: str, parent_heading: str) -> list[Chunk]:
    """Split a long section into smaller chunks (~1500 chars each)."""
    chunks = []
    lines = text.split("\n")
    current_lines = []
    current_len = 0
    part = 0
    
    for line in lines:
        current_lines.append(line)
        current_len += len(line) + 1
        
        # Split at blank lines after accumulating enough
        if current_len > 1500 and line.strip() == "":
            part += 1
            chunk_text = "\n".join(current_lines).strip()
            if len(chunk_text) > 50:
                chunks.append(_make_chunk(sheet_idx, sheet_name, f"{parent_heading} (part {part})", chunk_text))
            current_lines = []
            current_len = 0
    
    # Remaining content
    if current_lines:
        chunk_text = "\n".join(current_lines).strip()
        if len(chunk_text) > 50:
            part += 1
            chunks.append(_make_chunk(sheet_idx, sheet_name, f"{parent_heading} (part {part})", chunk_text))
    
    return chunks


def build_chunks() -> list[Chunk]:
    """Build chunks from all parsed sheets."""
    all_chunks = []
    
    for i, sheet_name in enumerate(SHEET_NAMES, 1):
        md_path = PARSED_DIR / f"sheet_{i:02d}.md"
        if not md_path.exists():
            logger.warning(f"Sheet {i:02d} not found: {md_path}")
            continue
        
        md_text = md_path.read_text(encoding="utf-8")
        chunks = split_into_chunks(md_text, i, sheet_name)
        logger.info(f"Sheet {i:02d} ({sheet_name}): {len(chunks)} chunks")
        all_chunks.extend(chunks)
    
    return all_chunks


def save_chunks_jsonl(chunks: list[Chunk], output_path: Path) -> None:
    """Save chunks to JSONL."""
    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.__dict__, ensure_ascii=False) + "\n")
    logger.info(f"Saved {len(chunks)} chunks to {output_path}")


def embed_into_lancedb(chunks: list[Chunk]) -> int:
    """Embed chunks into the existing LanceDB collection."""
    import boto3
    import lancedb
    import pyarrow as pa
    from botocore.config import Config as BotoConfig
    
    # Bedrock Titan Embed V2
    bedrock = boto3.client(
        'bedrock-runtime',
        config=BotoConfig(region_name=os.getenv("AWS_REGION", "ap-northeast-1"))
    )
    embed_model = os.getenv("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
    
    def get_embedding(text: str) -> list[float]:
        resp = bedrock.invoke_model(
            modelId=embed_model,
            body=json.dumps({"inputText": text[:8000], "dimensions": 1024, "normalize": True})
        )
        return json.loads(resp['body'].read())['embedding']
    
    # Open existing DB
    db = lancedb.connect(config.vector_local_store_path)
    table_name = config.vector_collection
    
    if table_name not in db.table_names():
        logger.error(f"Table {table_name} not found! Available: {db.table_names()}")
        return 0
    
    tbl = db.open_table(table_name)
    existing_count = tbl.count_rows()
    logger.info(f"Existing rows in {table_name}: {existing_count}")
    
    # Embed and build rows matching exact schema:
    # id, text, embedding, chunk_type, sheet_index, sheet_name, workbook_name,
    # source_pdf_s3_path, source_excel_s3_path, source_markdown_s3_path,
    # systems, apis, related_sheets
    rows = []
    for i, chunk in enumerate(chunks):
        vec = get_embedding(chunk.embedding_text)
        
        row = {
            "id": chunk.chunk_id,
            "text": chunk.content,
            "embedding": vec,
            "chunk_type": chunk.chunk_type,
            "sheet_index": chunk.sheet_index,
            "sheet_name": chunk.sheet_name,
            "workbook_name": chunk.workbook_name,
            "source_pdf_s3_path": chunk.source_pdf_s3_path,
            "source_excel_s3_path": chunk.source_excel_s3_path,
            "source_markdown_s3_path": chunk.source_markdown_s3_path,
            "systems": "|".join(chunk.systems) if chunk.systems else "",
            "apis": "|".join(chunk.apis) if chunk.apis else "",
            "related_sheets": "|".join(str(s) for s in chunk.related_sheets) if chunk.related_sheets else "",
        }
        rows.append(row)
        
        if (i + 1) % 10 == 0 or (i + 1) == len(chunks):
            logger.info(f"  Embedded {i + 1}/{len(chunks)}")
    
    # Add to table
    tbl.add(rows)
    new_count = tbl.count_rows()
    added = new_count - existing_count
    logger.info(f"Added {added} rows. New total: {new_count}")
    return added


def add_to_neptune_graph(chunks: list[Chunk]) -> dict:
    """Add entities from the flowchart workbook to Neptune graph."""
    from app.dual_rag.graph_builder import build_graph
    
    try:
        stats = build_graph(chunks)
        logger.info(f"Neptune graph: +{stats.get('nodes_created', 0)} nodes, +{stats.get('edges_created', 0)} edges")
        return stats
    except Exception as e:
        logger.warning(f"Neptune graph update skipped: {e}")
        return {"error": str(e)}


def main():
    logger.info(f"=== Ingesting {WORKBOOK_NAME} into dual-RAG KB ===")
    
    # Step 1: Build chunks
    logger.info("\n--- Step 1: Building chunks ---")
    chunks = build_chunks()
    logger.info(f"Total chunks: {len(chunks)}")
    
    # Save JSONL
    output_dir = PARSED_DIR / "dual_rag"
    output_dir.mkdir(exist_ok=True)
    save_chunks_jsonl(chunks, output_dir / "chunks.jsonl")
    
    # Step 2: Embed into LanceDB
    logger.info("\n--- Step 2: Embedding into LanceDB ---")
    added = embed_into_lancedb(chunks)
    
    # Step 3: Add to Neptune graph
    logger.info("\n--- Step 3: Adding to Neptune graph ---")
    graph_stats = add_to_neptune_graph(chunks)
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"INGESTION COMPLETE")
    logger.info(f"  Workbook: {WORKBOOK_NAME}")
    logger.info(f"  Chunks: {len(chunks)}")
    logger.info(f"  LanceDB rows added: {added}")
    logger.info(f"  Neptune: {graph_stats}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
