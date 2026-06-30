#!/usr/bin/env python3
"""Full embedding + QA validation for both DualRAG projects.

Steps:
1. Build semantic chunks for all workbooks in both projects
2. Embed all chunks into LanceDB (replace per-project)
3. Run QA retrieval validation
"""
import sys
sys.path.insert(0, 'src')

import json
import logging
from pathlib import Path
from hermes_bedrock_agent.knowledge_base.chunker import build_chunks, load_chunks
from hermes_bedrock_agent.knowledge_base.vector_store import load_vector_store, query_vector_store
from hermes_bedrock_agent.config import Config

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

cfg = Config()
print(f"=== DualRAG Embedding & QA Validation ===")
print(f"LanceDB path: {cfg.lancedb_path}")
print(f"Collection: {cfg.vector_collection}")
print(f"Chunk mode: {cfg.chunk_mode}")
print(f"Embed model: {cfg.embed_model_id}")
print()

# ── Project definitions ──────────────────────────────────────────────────────
PROJECTS = {
    "14_債務奉行クラウド": {
        "run_dir": Path("outputs/14_債務奉行クラウド/run_20260602_072107"),
        "s3_prefix": "outputs/14_債務奉行クラウド/run_20260602_072107",
    },
    "サンプル20260519": {
        "run_dir": Path("outputs/サンプル20260519/run_20260602_074637"),
        "s3_prefix": "outputs/サンプル20260519/run_20260602_074637",
    },
}

# ── Phase 1: Build chunks for all workbooks ──────────────────────────────────
all_project_chunks = {}

for project_id, pinfo in PROJECTS.items():
    run_dir = pinfo["run_dir"]
    s3_prefix = pinfo["s3_prefix"]
    project_chunks = []
    
    # Find all vlm_parsed directories
    vlm_dirs = sorted(d for d in run_dir.rglob("vlm_parsed") if d.is_dir() and not d.name.endswith("_tiles"))
    # Filter to only top-level vlm_parsed (not tile subdirs)
    vlm_dirs = [d for d in vlm_dirs if d.parent.parent == run_dir or d.parent == run_dir]
    
    print(f"═══ Project: {project_id} ({len(vlm_dirs)} workbooks) ═══")
    
    for vlm_dir in vlm_dirs:
        workbook_name = vlm_dir.parent.name
        sheets = list(vlm_dir.glob("sheet_*.md"))
        if not sheets:
            continue
        
        output_jsonl = vlm_dir.parent / "dual_rag" / "chunks.jsonl"
        output_jsonl.parent.mkdir(parents=True, exist_ok=True)
        
        s3_excel_key = f"{project_id}/{workbook_name}.xlsx"
        s3_pdf_prefix = f"{s3_prefix}/{workbook_name}/pdf"
        s3_vlm_prefix = f"{s3_prefix}/{workbook_name}/vlm_parsed"
        
        # Check for sheet mapping
        mapping_csv = vlm_dir.parent / "sheet_name_mapping.csv"
        if not mapping_csv.exists():
            mapping_csv = None
        
        chunks = build_chunks(
            vlm_parsed_dir=vlm_dir,
            sheet_name_mapping_csv=mapping_csv,
            workbook_name=workbook_name,
            s3_bucket=cfg.s3_bucket,
            s3_pdf_prefix=s3_pdf_prefix,
            s3_vlm_prefix=s3_vlm_prefix,
            s3_excel_key=s3_excel_key,
            output_path=output_jsonl,
            cfg=cfg,
            project_id=project_id,
        )
        project_chunks.extend(chunks)
        print(f"  {workbook_name}: {len(sheets)} sheets → {len(chunks)} chunks → {output_jsonl}")
    
    all_project_chunks[project_id] = project_chunks
    print(f"  TOTAL: {len(project_chunks)} chunks for {project_id}")
    print()

# ── Phase 2: Embed into LanceDB ──────────────────────────────────────────────
print("═══ Phase 2: Embedding into LanceDB ═══")
total_embedded = 0

for project_id, chunks in all_project_chunks.items():
    print(f"\nEmbedding {project_id}: {len(chunks)} chunks...")
    # First project replaces, subsequent appends (but each project replaces its own rows)
    written = load_vector_store(
        chunks=chunks,
        cfg=cfg,
        project_id=project_id,
        replace_project=True,
        batch_size=25,
    )
    total_embedded += written
    print(f"  ✓ {written}/{len(chunks)} embedded successfully")

print(f"\n  TOTAL EMBEDDED: {total_embedded} chunks across {len(all_project_chunks)} projects")
print(f"  Collection: {cfg.vector_collection}")
print(f"  LanceDB path: {cfg.lancedb_path}")

# ── Phase 3: QA Retrieval Validation ─────────────────────────────────────────
print("\n═══ Phase 3: QA Retrieval Validation ═══")

QA_TESTS = [
    # --- 14_債務奉行クラウド ---
    {
        "project_id": "14_債務奉行クラウド",
        "query": "仕入日付フィールドの桁数と種別は何ですか？",
        "category": "field_definition",
        "expected_hit": "MM4030002",
    },
    {
        "project_id": "14_債務奉行クラウド",
        "query": "MM4030001 伝票区分",
        "category": "field_code",
        "expected_hit": "伝票区分",
    },
    {
        "project_id": "14_債務奉行クラウド",
        "query": "ヘッダー情報セクションにはどんなフィールドがありますか？",
        "category": "section",
        "expected_hit": "ヘッダー情報",
    },
    {
        "project_id": "14_債務奉行クラウド",
        "query": "空白データを受け入れた場合のデフォルト値はどうなりますか？",
        "category": "business_rule",
        "expected_hit": "空白データを受け入れた場合",
    },
    {
        "project_id": "14_債務奉行クラウド",
        "query": "Ver230629の変更内容",
        "category": "change_history",
        "expected_hit": "Ver",
    },
    {
        "project_id": "14_債務奉行クラウド",
        "query": "HULFT Square アプリケーション仕様",
        "category": "overview",
        "expected_hit": "HULFT",
    },
    # --- サンプル20260519 ---
    {
        "project_id": "サンプル20260519",
        "query": "発注情報の登録APIのマッピング定義",
        "category": "mapping_table",
        "expected_hit": "発注",
    },
    {
        "project_id": "サンプル20260519",
        "query": "ANDPAD発注作成のデータ取得条件",
        "category": "data_condition",
        "expected_hit": "ANDPAD",
    },
    {
        "project_id": "サンプル20260519",
        "query": "DataSpider フローチャート スクリプト改修",
        "category": "flowchart",
        "expected_hit": "DataSpider",
    },
    {
        "project_id": "サンプル20260519",
        "query": "SAP発注情報からANDPADへの送信フロー",
        "category": "cross_sheet",
        "expected_hit": "SAP",
    },
]

results = []
for i, test in enumerate(QA_TESTS, 1):
    try:
        hits = query_vector_store(
            query_text=test["query"],
            cfg=cfg,
            top_k=3,
            project_id=test["project_id"],
        )
        
        # Check if expected_hit appears in top results
        hit_found = False
        hit_details = []
        for rank, h in enumerate(hits, 1):
            text_preview = h["text"][:120].replace("\n", " ")
            score = h.get("_distance", 0)
            hit_details.append(f"    [{rank}] score={score:.4f} sheet={h['sheet_name']} type={h['chunk_type']}")
            hit_details.append(f"        {text_preview}...")
            if test["expected_hit"] in h["text"]:
                hit_found = True
        
        status = "✓ PASS" if hit_found else "✗ MISS"
        results.append({"test": test, "passed": hit_found, "hits": hits})
        
        print(f"\n  [{i}] {status} | {test['category']} | project={test['project_id']}")
        print(f"      Q: {test['query']}")
        print(f"      Expected: '{test['expected_hit']}' in top-3")
        for d in hit_details[:4]:  # Show top 2 results
            print(d)
        
        # Show evidence path for first hit
        if hits:
            print(f"      Evidence: {hits[0].get('source_pdf_s3_path', 'N/A')}")
            print(f"      Markdown: {hits[0].get('source_markdown_s3_path', 'N/A')}")
    except Exception as e:
        print(f"\n  [{i}] ✗ ERROR | {test['category']} | {test['project_id']}: {e}")
        results.append({"test": test, "passed": False, "error": str(e)})

# ── Summary ──────────────────────────────────────────────────────────────────
print("\n\n═══ FINAL SUMMARY ═══")
passed = sum(1 for r in results if r["passed"])
print(f"QA Tests: {passed}/{len(results)} passed")
print()
for project_id, chunks in all_project_chunks.items():
    print(f"  {project_id}: {len(chunks)} chunks embedded")
print(f"\n  LanceDB: {cfg.lancedb_path} / {cfg.vector_collection}")
print(f"  Total records: {total_embedded}")
