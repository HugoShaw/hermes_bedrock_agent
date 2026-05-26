#!/usr/bin/env python3
"""
Murata Knowledge Graph Builder
================================
Steps:
  1. Load manifest + extracted text
  2. Rule-based entity extraction (project / component / person / tech-spec)
  3. Cross-doc relationship inference (section hierarchy + content similarity)
  4. Triple generation  (Subject) -[Predicate]-> (Object)
  5. Bedrock titan-embed-text-v2:0 embedding per document
  6. Persist graph_data.json

Output: ~/hermes_graph_project/data/graph_data.json
"""

import json
import re
import time
import hashlib
import logging
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import boto3
import botocore

# ── config ────────────────────────────────────────────────────────────────────
MANIFEST_PATH  = Path.home() / "hermes_graph_project/data/manifest.json"
EXTRACTED_DIR  = Path.home() / "hermes_graph_project/data/extracted"
OUTPUT_PATH    = Path.home() / "hermes_graph_project/data/graph_data.json"
BEDROCK_REGION = "ap-northeast-1"
EMBED_MODEL    = "amazon.titan-embed-text-v2:0"
EMBED_DIM      = 256
MAX_EMBED_CHARS = 7000      # Titan v2 token window ~8192; ~1 token per char safe limit
BATCH_SLEEP     = 0.3       # seconds between Bedrock calls to avoid throttle

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── domain vocabulary for entity classification ───────────────────────────────
PROJECT_KEYWORDS = re.compile(
    r"(murata|muratapr|MDW|村田|支払依頼|payment\s*request|iMaps|hulft|HDS|Baiwangda|百望达)",
    re.IGNORECASE,
)
COMPONENT_KEYWORDS = re.compile(
    r"(PaymentReq|PaymentReceiving|JournalBase|ReceivingList|VAllTableView"
    r"|BaseAction|BaseService|BaseDao|DWR|Struts|Hibernate|Spring"
    r"|PAYMENT_REQ|PAYMENT_RECEIVING|V_BASE_LIST_JOURNAL|V_PAYMENT"
    r"|servlet|ehcache|log4j|pom\.xml|web\.xml|struts\.xml|dwr\.xml"
    r"|spring-hibernate|spring-cxf|spring-ehcache)",
    re.IGNORECASE,
)
PERSON_KEYWORDS = re.compile(
    r"(@author|作成者|担当者|作者|Author|owner|assignee)",
    re.IGNORECASE,
)
TECH_SPEC_KEYWORDS = re.compile(
    r"(SQL|DDL|CREATE\s+TABLE|ALTER\s+TABLE|INSERT\s+INTO|SELECT\s+.+FROM"
    r"|API|REST|HTTP|HTTPS|JSON|XML|JSP|MVC|DAO|Service|Action"
    r"|画面|仕様|specification|requirement|テーブル|table\s+definition"
    r"|index|primary\s+key|foreign\s+key|trigger|view|procedure)",
    re.IGNORECASE,
)
# doc category mapping by extension / path fragment
CATEGORY_MAP = {
    ".java":       "source_code",
    ".jsp":        "web_view",
    ".sql":        "database",
    ".SQL":        "database",
    ".CSV":        "database",
    ".csv":        "database",
    ".xml":        "configuration",
    ".properties": "configuration",
    ".iml":        "project_config",
    ".docx":       "manual",
    ".xlsx":       "specification",
    ".xls":        "specification",
    ".pptx":       "presentation",
    ".md":         "documentation",
    ".mmd":        "diagram",
    ".txt":        "script_or_notes",
    ".json":       "data",
    ".css":        "web_view",
    ".mf":         "project_config",
    "(none)":      "config_or_misc",
}
# cross-doc relationship seeds: (path_pattern_A, rel, path_pattern_B, evidence)
CROSS_DOC_RULES = [
    # manual → source code
    (r"操作手册",             "DOCUMENTS",      r"\.java$",             "manual describes Java code"),
    (r"操作手册",             "REFERENCES_DB",  r"\.sql$",              "manual references DB schema"),
    # DB DDL → Java model
    (r"PAYMENT_REQ\.sql",    "DEFINES_TABLE_FOR", r"PaymentReq\.java", "DDL defines model fields"),
    (r"PAYMENT_RECEIVING",   "DEFINES_TABLE_FOR", r"PaymentReceiving\.java","DDL defines model fields"),
    (r"V_PAYMENT_RECEIVING", "DEFINES_VIEW_FOR",  r"VPaymantReceiving\.java","view defines VO"),
    (r"V_PAYMENT_REQ_FILE",  "DEFINES_VIEW_FOR",  r"VPaymentReqFile\.java",  "view defines VO"),
    (r"V_BASE_LIST_JOURNAL", "DEFINES_VIEW_FOR",  r"JournalBase\.java",      "view defines VO"),
    # Action → Service → Dao layering
    (r"Action\.java",        "DELEGATES_TO",   r"ServiceImpl\.java",   "MVC Action calls Service"),
    (r"ServiceImpl\.java",   "DELEGATES_TO",   r"DaoImpl\.java",       "Service calls DAO"),
    (r"ServiceImpl\.java",   "IMPLEMENTS",     r"Service\.java",       "impl/interface pair"),
    (r"Action\.java",        "DELEGATES_TO",   r"ServiceI\.java",      "Action uses Service interface"),
    # Config wires everything
    (r"spring-hibernate\.xml","CONFIGURES",    r"DaoImpl\.java",       "Spring configures DAO bean"),
    (r"struts\.xml",          "ROUTES_TO",     r"Action\.java",        "Struts maps URL to Action"),
    (r"dwr\.xml",             "EXPOSES",       r"Action\.java",        "DWR exposes Action as JS"),
    # pptx / xlsx specs → JSP views
    (r"MDW支払依頼",           "SPECIFIES",     r"payment_req",         "PPTX spec for payment UI"),
    (r"MV0008",                "SPECIFIES",     r"payment_req",         "screen spec MV0008"),
    (r"MV0016",                "SPECIFIES",     r"receiving_list",      "screen spec MV0016"),
    (r"MV0039",                "SPECIFIES",     r"receiving_confirm",   "screen spec MV0039"),
    # HDS SQL scripts → journal table
    (r"HDS之SQL脚本",          "UPDATES",       r"JOURNAL_BASE",        "HDS scripts update journal"),
    # semantic outputs reference source
    (r"semantic_map",          "DERIVED_FROM",  r"操作手册",             "semantic analysis of manual"),
    (r"semantic_map",          "DERIVED_FROM",  r"PAYMENT_REQ",         "semantic analysis of DDL"),
]


# ── helpers ───────────────────────────────────────────────────────────────────

def node_id(text: str) -> str:
    return "n_" + hashlib.md5(text.encode()).hexdigest()[:12]


def read_extracted(rec: dict) -> str:
    ep = Path(rec["extracted_to"])
    if ep.exists():
        return ep.read_text(encoding="utf-8", errors="replace")
    return ""


def classify_category(rec: dict) -> str:
    ext = rec.get("extension", "(none)")
    rel = rec.get("relative_path", "")
    if "操作手册" in rel:  return "manual"
    if "数据库设计" in rel: return "database"
    if "代码_muratapr" in rel:
        return CATEGORY_MAP.get(ext, "source_code")
    if "文档" in rel:
        return CATEGORY_MAP.get(ext, "specification")
    if "HDS之SQL" in rel: return "db_script"
    if "semantic_map" in rel: return "analysis_output"
    return CATEGORY_MAP.get(ext, "misc")


def extract_entities(text: str, rec: dict) -> list[dict]:
    entities = []
    seen_labels = set()

    def add(label: str, etype: str, evidence: str):
        if label in seen_labels or not label.strip():
            return
        seen_labels.add(label)
        entities.append({
            "id":       node_id(label),
            "label":    label,
            "type":     etype,
            "evidence": evidence[:120],
            "source_file": rec["file_name"],
        })

    # project names
    for m in PROJECT_KEYWORDS.finditer(text[:5000]):
        add(m.group(0).strip(), "Project", f"found at char {m.start()}")

    # components (class / table / config names)
    for m in COMPONENT_KEYWORDS.finditer(text[:8000]):
        add(m.group(0).strip(), "Component", f"found at char {m.start()}")

    # persons (author lines)
    for line in text.split("\n")[:60]:
        if PERSON_KEYWORDS.search(line):
            name = re.sub(r"[@\*\/\s]*(author|作成者|担当者|作者|owner|assignee)\s*[=:：]?\s*", "",
                          line, flags=re.IGNORECASE).strip()
            if name:
                add(name[:40], "Person", line.strip()[:80])

    # tech-specs (SQL tables, API terms)
    for m in TECH_SPEC_KEYWORDS.finditer(text[:6000]):
        add(m.group(0).strip(), "TechSpec", f"found at char {m.start()}")

    # document itself as node
    doc_label = rec["file_name"]
    add(doc_label, "Document", f"category={classify_category(rec)}")

    return entities


def extract_section_hierarchy(text: str, file_name: str) -> list[dict]:
    """Return triples from Markdown/DOCX section headings."""
    triples = []
    heading_re = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)
    matches = list(heading_re.finditer(text))
    stack: list[tuple[int, str]] = []  # (level, title)
    for m in matches:
        level = len(m.group(1))
        title = m.group(2).strip()[:80]
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            parent = stack[-1][1]
            triples.append({
                "subject":   f"{file_name}::{parent}",
                "predicate": "HAS_SUBSECTION",
                "object":    f"{file_name}::{title}",
                "evidence":  "markdown heading hierarchy",
            })
        stack.append((level, title))
    return triples


def match_cross_doc(rel_a: str, rel_b: str) -> list[dict]:
    """Apply CROSS_DOC_RULES between two doc relative paths."""
    results = []
    for (pat_a, pred, pat_b, ev) in CROSS_DOC_RULES:
        if re.search(pat_a, rel_a, re.IGNORECASE) and re.search(pat_b, rel_b, re.IGNORECASE):
            results.append({"predicate": pred, "evidence": ev})
    return results


# ── embedding ─────────────────────────────────────────────────────────────────

class Embedder:
    def __init__(self):
        self.client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        self._calls = 0

    def embed(self, text: str) -> list[float]:
        snippet = text[:MAX_EMBED_CHARS].replace("\x00", " ")
        if not snippet.strip():
            return [0.0] * EMBED_DIM
        payload = json.dumps({"inputText": snippet, "dimensions": EMBED_DIM, "normalize": True})
        for attempt in range(3):
            try:
                resp = self.client.invoke_model(
                    modelId=EMBED_MODEL,
                    body=payload,
                    contentType="application/json",
                    accept="application/json",
                )
                result = json.loads(resp["body"].read())
                self._calls += 1
                time.sleep(BATCH_SLEEP)
                return result["embedding"]
            except botocore.exceptions.ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "ThrottlingException":
                    wait = 2 ** attempt * 2
                    log.warning(f"Throttled, sleeping {wait}s ...")
                    time.sleep(wait)
                else:
                    log.error(f"Bedrock error: {e}")
                    return [0.0] * EMBED_DIM
        return [0.0] * EMBED_DIM


# ── main ──────────────────────────────────────────────────────────────────────

def build():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    files = [f for f in manifest["files"] if not f["is_empty"]]
    log.info(f"Processing {len(files)} non-empty files from manifest")

    embedder = Embedder()

    # ── pass 1: per-doc nodes, entities, section triples ─────────────────────
    nodes: dict[str, dict]  = {}   # id -> node
    triples: list[dict]     = []
    doc_nodes: list[dict]   = []   # ordered doc nodes for cross-doc pass

    for i, rec in enumerate(files):
        text    = read_extracted(rec)
        cat     = classify_category(rec)
        doc_id  = node_id(rec["file_name"] + rec["relative_path"])

        log.info(f"[{i+1}/{len(files)}] {rec['file_name']}  ({cat})")

        # Document node
        doc_node = {
            "id":            doc_id,
            "label":         rec["file_name"],
            "type":          "Document",
            "category":      cat,
            "s3_path":       rec["s3_path"],
            "relative_path": rec["relative_path"],
            "size_kb":       rec["size_kb"],
            "modified_utc":  rec["modified_utc"],
            "char_count":    rec["char_count"],
            "extractor":     rec["extractor"],
            "embedding":     [],   # filled in pass 2
        }

        # entity extraction
        entities = extract_entities(text, rec)
        doc_node["entities"] = [
            {"id": e["id"], "label": e["label"], "type": e["type"]}
            for e in entities
        ]

        # add entity nodes
        for ent in entities:
            if ent["id"] not in nodes:
                nodes[ent["id"]] = {
                    "id":    ent["id"],
                    "label": ent["label"],
                    "type":  ent["type"],
                }
            # triple: doc CONTAINS entity
            triples.append({
                "subject":   doc_id,
                "predicate": "CONTAINS_ENTITY",
                "object":    ent["id"],
                "evidence":  ent["evidence"],
            })

        # section hierarchy (md / docx)
        if rec["extension"] in (".md", ".docx", ".txt"):
            for t in extract_section_hierarchy(text, rec["file_name"]):
                triples.append(t)

        nodes[doc_id] = doc_node
        doc_nodes.append(doc_node)

    log.info(f"Pass 1 done — {len(nodes)} nodes, {len(triples)} triples so far")

    # ── pass 2: cross-doc relationships ──────────────────────────────────────
    cross_count = 0
    for i, na in enumerate(doc_nodes):
        for nb in doc_nodes[i+1:]:
            rels = match_cross_doc(na["relative_path"], nb["relative_path"])
            for r in rels:
                triples.append({
                    "subject":   na["id"],
                    "predicate": r["predicate"],
                    "object":    nb["id"],
                    "evidence":  r["evidence"],
                })
                cross_count += 1

    log.info(f"Pass 2 done — {cross_count} cross-doc triples added, total {len(triples)}")

    # ── pass 3: embeddings ────────────────────────────────────────────────────
    log.info("Pass 3: generating embeddings via Bedrock ...")
    for i, doc_node in enumerate(doc_nodes):
        rec  = files[i]
        text = read_extracted(rec)
        # build a rich snippet: filename + category + first 6000 chars
        snippet = (
            f"File: {rec['file_name']}\n"
            f"Category: {doc_node['category']}\n"
            f"Path: {rec['relative_path']}\n\n"
            + text
        )
        doc_node["embedding"] = embedder.embed(snippet)
        if (i + 1) % 20 == 0:
            log.info(f"  ... {i+1}/{len(doc_nodes)} embedded")

    log.info(f"Pass 3 done — {embedder._calls} Bedrock calls")

    # ── assemble graph_data.json ──────────────────────────────────────────────
    # de-duplicate triples
    seen_triples: set[tuple] = set()
    unique_triples: list[dict] = []
    for t in triples:
        key = (t["subject"], t["predicate"], t["object"])
        if key not in seen_triples:
            seen_triples.add(key)
            unique_triples.append(t)

    # triple stats
    pred_counts: dict[str, int] = defaultdict(int)
    for t in unique_triples:
        pred_counts[t["predicate"]] += 1

    graph = {
        "meta": {
            "generated_at":   datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source_bucket":  "s3://s3-hulftchina-rd/Murata/",
            "embed_model":    EMBED_MODEL,
            "embed_dim":      EMBED_DIM,
            "bedrock_region": BEDROCK_REGION,
            "total_nodes":    len(nodes),
            "total_triples":  len(unique_triples),
            "bedrock_calls":  embedder._calls,
        },
        "statistics": {
            "nodes_by_type":      {},
            "triples_by_predicate": dict(sorted(pred_counts.items(), key=lambda x: -x[1])),
        },
        "nodes":   list(nodes.values()),
        "triples": unique_triples,
    }

    # nodes by type
    type_counts: dict[str, int] = defaultdict(int)
    for n in nodes.values():
        type_counts[n["type"]] += 1
    graph["statistics"]["nodes_by_type"] = dict(sorted(type_counts.items(), key=lambda x: -x[1]))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    log.info(f"graph_data.json written to {OUTPUT_PATH}")

    # ── console summary ───────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print(" GRAPH BUILD COMPLETE")
    print("=" * 60)
    print(f"  Output file       : {OUTPUT_PATH}")
    print(f"  Total nodes       : {len(nodes)}")
    print(f"  Total triples     : {len(unique_triples)}")
    print(f"  Bedrock API calls : {embedder._calls}")
    print()
    print("  Nodes by type:")
    for t, c in graph["statistics"]["nodes_by_type"].items():
        print(f"    {t:20s}  {c:4d}")
    print()
    print("  Top predicates:")
    for p, c in list(graph["statistics"]["triples_by_predicate"].items())[:12]:
        print(f"    {p:30s}  {c:4d}")
    print("=" * 60)


if __name__ == "__main__":
    build()
