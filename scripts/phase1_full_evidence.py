#!/usr/bin/env python3
"""
Phase 1: Deep Text Analysis & Evidence Extraction
===================================================
Scans all extracted documents (user manuals, DDL, SQL, Java source, XML configs,
XLSX specs, PPTX design docs) and produces:
  - entities with evidence (source_doc, original_sentence, page_context)
  - relations with evidence
  - Cross-system data flow chains

Output: ~/projects/data/output/phase1_evidence.json
"""

import json, re, hashlib, os, sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

DATA_DIR   = Path.home() / "projects/data"
MANIFEST   = DATA_DIR / "output/manifest.json"
OUTPUT     = DATA_DIR / "output/phase1_evidence.json"

# ── Helpers ────────────────────────────────────────────────────────────

def node_id(text: str) -> str:
    return "n_" + hashlib.md5(text.encode()).hexdigest()[:12]

def edge_id(src, rel, tgt) -> str:
    return "e_" + hashlib.md5(f"{src}:{rel}:{tgt}".encode()).hexdigest()[:12]

def safe_text(t, mx=50):
    """Truncate to core fragment, strip newlines."""
    if not isinstance(t, str): t = str(t)
    t = re.sub(r'[\n\r\t]+', ' ', t).strip()
    return t[:mx]

def ctx_window(text, pos, window=200):
    """Extract context window around a match position."""
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    return re.sub(r'[\n\r\t]+', ' ', text[start:end]).strip()

def read_extracted(path_str):
    """Read extracted text with encoding cascade."""
    p = Path(path_str)
    if not p.exists():
        return ""
    for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
        try:
            return p.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return ""

MAX_TEXT = 200_000  # Cap per-file for regex safety

# ── Regex Patterns ─────────────────────────────────────────────────────

# Oracle DDL with quoted identifiers
RE_CREATE_TABLE = re.compile(
    r'CREATE\s+TABLE\s+(?:"?\w+"?\.)?\"?(\w+)\"?\s*\(', re.I)
RE_CREATE_VIEW = re.compile(
    r'CREATE\s+(?:OR\s+REPLACE\s+)?(?:FORCE\s+)?VIEW\s+(?:"?\w+"?\.)?\"?(\w+)\"?\s', re.I)
RE_COMMENT_COL = re.compile(
    r"COMMENT\s+ON\s+COLUMN\s+\"?\w+\"?\.\"?(\w+)\"?\.\"?(\w+)\"?\s+IS\s+'([^']*)'", re.I)
RE_COMMENT_TBL = re.compile(
    r"COMMENT\s+ON\s+TABLE\s+\"?\w+\"?\.\"?(\w+)\"?\s+IS\s+'([^']*)'", re.I)
# Java patterns
RE_JAVA_CLASS = re.compile(r'public\s+(?:abstract\s+)?class\s+(\w+)', re.I)
RE_JAVA_IFACE = re.compile(r'public\s+interface\s+(\w+)', re.I)
RE_JAVA_EXTENDS = re.compile(r'class\s+(\w+)\s+extends\s+(\w+)', re.I)
RE_JAVA_IMPLEMENTS = re.compile(r'class\s+(\w+)\s+implements\s+([\w,\s]+)', re.I)
RE_AUTOWIRED = re.compile(r'@Autowired.*?(?:private|protected|public)\s+(\w+)\s+(\w+)', re.S)
RE_IMPORT = re.compile(r'import\s+([\w.]+);')
# SQL data flow
RE_INSERT_SELECT = re.compile(r'INSERT\s+INTO\s+\"?(\w+)\"?\s*.*?\bSELECT\b.*?\bFROM\b\s+\"?(\w+)\"?', re.I | re.S)
RE_SELECT_FROM = re.compile(r'\bFROM\b\s+\"?\w*\"?\.?\"?(\w+)\"?', re.I)
RE_JOIN = re.compile(r'\bJOIN\b\s+\"?\w*\"?\.?\"?(\w+)\"?', re.I)
# Struts/Spring XML
RE_STRUTS_ACTION = re.compile(r'<action\s+[^>]*name="([^"]*)"[^>]*class="([^"]*)"', re.I)
RE_SPRING_BEAN = re.compile(r'<bean\s+[^>]*id="([^"]*)"[^>]*class="([^"]*)"', re.I)
# System references
RE_SYSTEM_REF = re.compile(r'\b(iMaps|HULFT|HDS|MDW|SUN|ERP|SAP|Oracle)\b', re.I)
# JSP form action
RE_JSP_ACTION = re.compile(r'action="([^"]*)"', re.I)
# Business rules (status patterns in column comments)
RE_STATUS_RULE = re.compile(r'(STATUS|FLG|FLAG|DEL_FLG|区分|状態|ステータス)\b', re.I)

# ── Entity Extraction ──────────────────────────────────────────────────

def extract_entities_from_file(entry, text):
    """Extract entities from a single file with full evidence."""
    entities = []
    relations = []
    fname = entry["file_name"]
    ext = entry.get("extension", "").lower()

    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT]

    # --- Always create a Document entity ---
    doc_id = node_id(f"Document:{entry['relative_path']}")
    doc_evidence = safe_text(text[:100], 50)
    entities.append({
        "id": doc_id,
        "name": fname,
        "type": "Document",
        "source_doc": fname,
        "original_sentence": doc_evidence,
        "page_context": f"File: {entry['relative_path']}",
        "category": classify_file(ext, entry.get("relative_path", "")),
        "s3_path": entry.get("s3_path", ""),
        "relative_path": entry.get("relative_path", ""),
    })

    # --- SQL/DDL extraction ---
    if ext in (".sql", ".txt") and any(kw in text.upper() for kw in ("CREATE TABLE", "INSERT INTO", "COMMENT ON")):
        # Tables
        for m in RE_CREATE_TABLE.finditer(text):
            tname = m.group(1).upper()
            evidence = ctx_window(text, m.start(), 150)
            tid = node_id(f"Table:{tname}")
            entities.append({
                "id": tid,
                "name": tname,
                "type": "Table",
                "source_doc": fname,
                "original_sentence": safe_text(evidence, 50),
                "page_context": f"CREATE TABLE in {fname}",
            })
            relations.append({
                "from": doc_id, "to": tid, "type": "DEFINES",
                "source_doc": fname,
                "original_sentence": safe_text(f"CREATE TABLE {tname}", 50),
            })

        # Table comments
        for m in RE_COMMENT_TBL.finditer(text):
            tname = m.group(1).upper()
            comment = m.group(2)
            tid = node_id(f"Table:{tname}")
            # Update table name with comment if exists
            for e in entities:
                if e["id"] == tid:
                    e["description"] = comment
                    break

        # Views
        for m in RE_CREATE_VIEW.finditer(text):
            vname = m.group(1).upper()
            evidence = ctx_window(text, m.start(), 200)
            vid = node_id(f"View:{vname}")
            entities.append({
                "id": vid,
                "name": vname,
                "type": "View",
                "source_doc": fname,
                "original_sentence": safe_text(evidence, 50),
                "page_context": f"CREATE VIEW in {fname}",
            })
            relations.append({
                "from": doc_id, "to": vid, "type": "DEFINES",
                "source_doc": fname,
                "original_sentence": safe_text(f"CREATE VIEW {vname}", 50),
            })
            # View aggregates tables (from the SELECT body)
            view_body = text[m.start():m.start()+2000]
            for t in RE_SELECT_FROM.finditer(view_body):
                src_table = t.group(1).upper()
                stid = node_id(f"Table:{src_table}")
                relations.append({
                    "from": vid, "to": stid, "type": "AGGREGATES",
                    "source_doc": fname,
                    "original_sentence": safe_text(f"VIEW {vname} SELECT FROM {src_table}", 50),
                })
            for t in RE_JOIN.finditer(view_body):
                src_table = t.group(1).upper()
                stid = node_id(f"Table:{src_table}")
                relations.append({
                    "from": vid, "to": stid, "type": "AGGREGATES",
                    "source_doc": fname,
                    "original_sentence": safe_text(f"VIEW {vname} JOIN {src_table}", 50),
                })

        # Column comments -> business rules
        for m in RE_COMMENT_COL.finditer(text):
            tname = m.group(1).upper()
            cname = m.group(2).upper()
            comment = m.group(3)
            tid = node_id(f"Table:{tname}")

            # Check for status/flag business rules
            if RE_STATUS_RULE.search(cname) or re.search(r'[：:]\s*\d', comment):
                br_name = f"{tname}.{cname}_Rule"
                br_id = node_id(f"BusinessRule:{br_name}")
                entities.append({
                    "id": br_id,
                    "name": br_name,
                    "type": "BusinessRule",
                    "source_doc": fname,
                    "original_sentence": safe_text(f"{cname}: {comment}", 50),
                    "page_context": f"COMMENT ON COLUMN {tname}.{cname}",
                    "description": comment,
                })
                relations.append({
                    "from": br_id, "to": tid, "type": "GOVERNS",
                    "source_doc": fname,
                    "original_sentence": safe_text(f"Rule {cname} governs {tname}", 50),
                })

        # INSERT INTO ... SELECT FROM (data flow)
        if len(text) < 500_000:  # Skip for huge files
            for m in RE_INSERT_SELECT.finditer(text[:100_000]):
                target = m.group(1).upper()
                source = m.group(2).upper()
                if target != source:
                    src_id = node_id(f"Table:{source}")
                    tgt_id = node_id(f"Table:{target}")
                    relations.append({
                        "from": src_id, "to": tgt_id, "type": "FLOWS_TO",
                        "source_doc": fname,
                        "original_sentence": safe_text(f"INSERT INTO {target} SELECT FROM {source}", 50),
                    })

    # --- Java source extraction ---
    if ext == ".java":
        # Classes
        for m in RE_JAVA_CLASS.finditer(text):
            cname = m.group(1)
            evidence = ctx_window(text, m.start(), 100)
            ctype = classify_java_class(cname)
            cid = node_id(f"{ctype}:{cname}")
            entities.append({
                "id": cid,
                "name": cname,
                "type": ctype,
                "source_doc": fname,
                "original_sentence": safe_text(evidence, 50),
                "page_context": f"class {cname} in {fname}",
            })
            relations.append({
                "from": doc_id, "to": cid, "type": "CONTAINS",
                "source_doc": fname,
                "original_sentence": safe_text(f"File {fname} defines {cname}", 50),
            })

            # Extends
            ext_m = RE_JAVA_EXTENDS.search(text)
            if ext_m and ext_m.group(1) == cname:
                parent = ext_m.group(2)
                pid = node_id(f"{classify_java_class(parent)}:{parent}")
                relations.append({
                    "from": cid, "to": pid, "type": "EXTENDS",
                    "source_doc": fname,
                    "original_sentence": safe_text(f"class {cname} extends {parent}", 50),
                })

            # Implements
            impl_m = RE_JAVA_IMPLEMENTS.search(text)
            if impl_m and impl_m.group(1) == cname:
                for iface in impl_m.group(2).split(","):
                    iface = iface.strip()
                    if iface:
                        iid = node_id(f"Interface:{iface}")
                        relations.append({
                            "from": cid, "to": iid, "type": "IMPLEMENTS",
                            "source_doc": fname,
                            "original_sentence": safe_text(f"{cname} implements {iface}", 50),
                        })

        # Interfaces
        for m in RE_JAVA_IFACE.finditer(text):
            iname = m.group(1)
            evidence = ctx_window(text, m.start(), 100)
            iid = node_id(f"Interface:{iname}")
            entities.append({
                "id": iid,
                "name": iname,
                "type": "Interface",
                "source_doc": fname,
                "original_sentence": safe_text(evidence, 50),
                "page_context": f"interface {iname} in {fname}",
            })
            relations.append({
                "from": doc_id, "to": iid, "type": "CONTAINS",
                "source_doc": fname,
                "original_sentence": safe_text(f"File {fname} defines {iname}", 50),
            })

        # @Autowired -> service dependencies
        for m in RE_AUTOWIRED.finditer(text):
            dep_type = m.group(1)
            dep_name = m.group(2)
            # Find the owning class
            class_m = RE_JAVA_CLASS.search(text)
            if class_m:
                owner = class_m.group(1)
                owner_type = classify_java_class(owner)
                owner_id = node_id(f"{owner_type}:{owner}")
                dep_id = node_id(f"{classify_java_class(dep_type)}:{dep_type}")
                relations.append({
                    "from": owner_id, "to": dep_id, "type": "DEPENDS_ON",
                    "source_doc": fname,
                    "original_sentence": safe_text(f"@Autowired {dep_type} {dep_name}", 50),
                })

        # Table access patterns in Java (DAO/Service)
        table_refs = re.findall(r'["\'](\w{3,}_\w{3,})["\']', text)
        class_m = RE_JAVA_CLASS.search(text)
        if class_m:
            owner = class_m.group(1)
            owner_id = node_id(f"{classify_java_class(owner)}:{owner}")
            seen_tables = set()
            for tref in table_refs:
                tref_upper = tref.upper()
                # Heuristic: table names are UPPER_CASE with underscores
                if tref_upper == tref and len(tref) > 5 and '_' in tref and tref not in seen_tables:
                    seen_tables.add(tref)
                    tid = node_id(f"Table:{tref_upper}")
                    relations.append({
                        "from": owner_id, "to": tid, "type": "ACCESSES",
                        "source_doc": fname,
                        "original_sentence": safe_text(f"{owner} references {tref_upper}", 50),
                    })

    # --- XML config extraction ---
    if ext == ".xml":
        # Struts actions
        for m in RE_STRUTS_ACTION.finditer(text):
            action_name = m.group(1)
            action_class = m.group(2).split(".")[-1]
            evidence = ctx_window(text, m.start(), 150)
            aid = node_id(f"JavaClass:{action_class}")
            relations.append({
                "from": doc_id, "to": aid, "type": "ROUTES_TO",
                "source_doc": fname,
                "original_sentence": safe_text(f"struts action {action_name} -> {action_class}", 50),
            })

        # Spring beans
        for m in RE_SPRING_BEAN.finditer(text):
            bean_id_str = m.group(1)
            bean_class = m.group(2).split(".")[-1]
            evidence = ctx_window(text, m.start(), 150)
            bid = node_id(f"JavaClass:{bean_class}")
            relations.append({
                "from": doc_id, "to": bid, "type": "CONFIGURES",
                "source_doc": fname,
                "original_sentence": safe_text(f"spring bean {bean_id_str} = {bean_class}", 50),
            })

    # --- JSP extraction ---
    if ext == ".jsp":
        for m in RE_JSP_ACTION.finditer(text):
            action_url = m.group(1)
            evidence = ctx_window(text, m.start(), 100)
            # Try to match to an Action class
            action_parts = action_url.strip("/").split("/")
            if action_parts:
                last_part = action_parts[-1].replace(".action", "")
                entities.append({
                    "id": node_id(f"UIAction:{last_part}"),
                    "name": last_part,
                    "type": "UIAction",
                    "source_doc": fname,
                    "original_sentence": safe_text(f"JSP form action={action_url}", 50),
                    "page_context": f"JSP form in {fname}",
                })

    # --- System references across all files ---
    seen_systems = set()
    for m in RE_SYSTEM_REF.finditer(text):
        sys_name = m.group(1).upper()
        if sys_name == "ORACLE":
            sys_name = "Oracle"
        if sys_name not in seen_systems:
            seen_systems.add(sys_name)
            sid = node_id(f"System:{sys_name}")
            entities.append({
                "id": sid,
                "name": sys_name,
                "type": "System",
                "source_doc": fname,
                "original_sentence": safe_text(ctx_window(text, m.start(), 80), 50),
                "page_context": f"System reference in {fname}",
            })

    return entities, relations


def classify_file(ext, path):
    """Classify a file into a category."""
    if ext in (".sql", ".txt") and ("DDL" in path or "SQL" in path or "数据库" in path or "HDS" in path):
        return "database"
    if ext == ".java":
        return "source_code"
    if ext in (".xml",):
        return "config"
    if ext == ".jsp":
        return "ui"
    if ext in (".docx", ".pptx", ".xlsx", ".xls"):
        return "document"
    if ext == ".csv":
        return "data"
    return "other"


def classify_java_class(name):
    """Classify a Java class by naming convention."""
    if name.endswith("Action"):
        return "Controller"
    if name.endswith("ServiceImpl"):
        return "Service"
    if name.endswith("DaoImpl"):
        return "DataAccess"
    if name.endswith("Service") or name.endswith("ServiceI"):
        return "Interface"
    if name.endswith("DaoI") or name.endswith("Dao"):
        return "Interface"
    if name.endswith("Entity") or name.endswith("Model"):
        return "Entity"
    return "JavaClass"


# ── Cross-Document MVC Linking ─────────────────────────────────────────

def cross_doc_mvc_links(entries):
    """Link Action -> ServiceImpl -> DaoImpl by naming convention."""
    relations = []
    idx = {}
    for e in entries:
        fn = e["file_name"]
        for sfx in ["Action.java", "ServiceImpl.java", "DaoImpl.java",
                     "ServiceI.java", "DaoI.java", "Service.java"]:
            if fn.endswith(sfx):
                base = fn[:-len(sfx)]
                idx.setdefault(base, {})[sfx] = fn

    RULES = [
        ("Action.java",       "DELEGATES_TO",  "ServiceImpl.java"),
        ("ServiceImpl.java",  "CALLS_DAO",     "DaoImpl.java"),
        ("ServiceImpl.java",  "IMPLEMENTS",    "ServiceI.java"),
        ("ServiceImpl.java",  "IMPLEMENTS",    "Service.java"),
        ("DaoImpl.java",      "IMPLEMENTS",    "DaoI.java"),
    ]
    for base, members in idx.items():
        for sfxA, pred, sfxB in RULES:
            a = members.get(sfxA)
            b = members.get(sfxB)
            if a and b:
                a_cls = a.replace(".java", "")
                b_cls = b.replace(".java", "")
                a_type = classify_java_class(a_cls)
                b_type = classify_java_class(b_cls)
                a_id = node_id(f"{a_type}:{a_cls}")
                b_id = node_id(f"{b_type}:{b_cls}")
                relations.append({
                    "from": a_id, "to": b_id, "type": pred,
                    "source_doc": f"{a} -> {b}",
                    "original_sentence": safe_text(f"MVC: {a_cls} {pred} {b_cls}", 50),
                })
    return relations


# ── Cross-Document System Flow Links ──────────────────────────────────

def cross_doc_system_flows(all_entities, all_relations, entries):
    """Infer system-level data flows from HDS scripts and naming patterns."""
    relations = []

    # System entities
    systems = {e["name"]: e["id"] for e in all_entities if e["type"] == "System"}

    # Known architecture: iMaps -> HULFT -> HDS -> MDW -> SUN
    ARCH_FLOWS = [
        ("IMAPS", "HULFT", "iMaps transmits data via HULFT file transfer"),
        ("HULFT", "HDS",   "HULFT transfers files to HDS staging area"),
        ("HDS",   "MDW",   "HDS ETL scripts load data into MDW via DB_Link"),
        ("MDW",   "SUN",   "MDW sends accounting data to SUN system"),
    ]
    for src_sys, tgt_sys, evidence in ARCH_FLOWS:
        sid = systems.get(src_sys) or node_id(f"System:{src_sys}")
        tid = systems.get(tgt_sys) or node_id(f"System:{tgt_sys}")
        if sid != tid:
            relations.append({
                "from": sid, "to": tid, "type": "FLOWS_TO",
                "source_doc": "Architecture inference",
                "original_sentence": safe_text(evidence, 50),
            })

    # Table -> System ownership by schema/naming
    tables = {e["name"]: e["id"] for e in all_entities if e["type"] == "Table"}
    mdw_id = systems.get("MDW") or node_id("System:MDW")
    for tname, tid in tables.items():
        # Most tables belong to MDW schema
        relations.append({
            "from": tid, "to": mdw_id, "type": "BELONGS_TO",
            "source_doc": "Schema inference",
            "original_sentence": safe_text(f"Table {tname} in MDW schema", 50),
        })
        # SUN tables
        if "SUN" in tname:
            sun_id = systems.get("SUN") or node_id("System:SUN")
            relations.append({
                "from": tid, "to": sun_id, "type": "TRANSFERS_VIA",
                "source_doc": "Naming convention",
                "original_sentence": safe_text(f"Table {tname} transfers to SUN", 50),
            })

    return relations


# ── Document -> Business Module Mapping ───────────────────────────────

def extract_business_modules(all_entities, entries):
    """Extract business modules from document names and content."""
    entities = []
    relations = []

    # Module inference from doc structure
    modules = {
        "PaymentRequest": {"name": "支払依頼(Payment Request)", "files": ["PaymentReq", "payment_req"]},
        "Receiving":      {"name": "受入(Receiving)", "files": ["Receiving", "receiving"]},
        "Inspection":     {"name": "受入検査(Inspection)", "files": ["Inspection", "inspection"]},
        "JournalEntry":   {"name": "仕訳(Journal Entry)", "files": ["Journal", "journal"]},
        "AccountCode":    {"name": "勘定科目(Account Code)", "files": ["Account", "AC_DESC"]},
        "SystemAdmin":    {"name": "システム管理(System Admin)", "files": ["Admin", "管理"]},
    }

    for mod_key, mod_info in modules.items():
        mid = node_id(f"BusinessModule:{mod_key}")
        entities.append({
            "id": mid,
            "name": mod_info["name"],
            "type": "BusinessModule",
            "source_doc": "Module inference",
            "original_sentence": safe_text(f"Module {mod_key} inferred from naming", 50),
            "page_context": "Business module extraction",
        })

        # Link tables to modules
        for ent in all_entities:
            if ent["type"] == "Table":
                for pattern in mod_info["files"]:
                    if pattern.upper() in ent["name"].upper():
                        relations.append({
                            "from": ent["id"], "to": mid, "type": "PART_OF",
                            "source_doc": ent.get("source_doc", ""),
                            "original_sentence": safe_text(f"{ent['name']} part of {mod_key}", 50),
                        })
                        break

        # Link Java classes to modules
        for ent in all_entities:
            if ent["type"] in ("Controller", "Service", "DataAccess", "JavaClass"):
                for pattern in mod_info["files"]:
                    if pattern in ent["name"]:
                        relations.append({
                            "from": ent["id"], "to": mid, "type": "PART_OF",
                            "source_doc": ent.get("source_doc", ""),
                            "original_sentence": safe_text(f"{ent['name']} part of {mod_key}", 50),
                        })
                        break

    return entities, relations


# ── Main Pipeline ─────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 1: Deep Text Analysis & Evidence Extraction")
    print("=" * 60)

    # Load manifest
    manifest = json.load(open(MANIFEST))
    entries = manifest.get("files", manifest.get("entries", []))
    print(f"\nManifest: {len(entries)} files")

    all_entities = []
    all_relations = []
    file_stats = defaultdict(int)

    for i, entry in enumerate(entries):
        fname = entry["file_name"]
        ext_path = entry.get("extracted_to", "")
        text = read_extracted(ext_path) if ext_path else ""

        if not text.strip():
            file_stats["empty"] += 1
            continue

        file_stats[entry.get("extension", "unknown")] += 1

        entities, relations = extract_entities_from_file(entry, text)
        all_entities.extend(entities)
        all_relations.extend(relations)

        if (i + 1) % 30 == 0:
            print(f"  Processed {i+1}/{len(entries)} files...")

    print(f"\nPer-file extraction: {len(all_entities)} entities, {len(all_relations)} relations")

    # Cross-document MVC links
    mvc_rels = cross_doc_mvc_links(entries)
    all_relations.extend(mvc_rels)
    print(f"MVC cross-doc links: +{len(mvc_rels)} relations")

    # System flow links
    sys_rels = cross_doc_system_flows(all_entities, all_relations, entries)
    all_relations.extend(sys_rels)
    print(f"System flow links: +{len(sys_rels)} relations")

    # Business module extraction
    mod_entities, mod_relations = extract_business_modules(all_entities, entries)
    all_entities.extend(mod_entities)
    all_relations.extend(mod_relations)
    print(f"Business modules: +{len(mod_entities)} entities, +{len(mod_relations)} relations")

    # ── Deduplication ──────────────────────────────────────────────────
    # Deduplicate entities by ID (keep first occurrence)
    seen_ids = set()
    deduped_entities = []
    for e in all_entities:
        if e["id"] not in seen_ids:
            seen_ids.add(e["id"])
            deduped_entities.append(e)

    # Deduplicate relations by (from, type, to)
    seen_rels = set()
    deduped_relations = []
    for r in all_relations:
        key = (r["from"], r["type"], r["to"])
        if key not in seen_rels:
            seen_rels.add(key)
            deduped_relations.append(r)

    # Remove relations with dangling endpoints
    valid_ids = {e["id"] for e in deduped_entities}
    valid_relations = [r for r in deduped_relations if r["from"] in valid_ids and r["to"] in valid_ids]
    dangling = len(deduped_relations) - len(valid_relations)

    print(f"\n{'='*60}")
    print(f"After dedup: {len(deduped_entities)} entities, {len(valid_relations)} relations")
    print(f"Removed: {dangling} dangling relations")

    # ── Statistics ─────────────────────────────────────────────────────
    by_type = defaultdict(int)
    for e in deduped_entities:
        by_type[e["type"]] += 1

    by_rel = defaultdict(int)
    for r in valid_relations:
        by_rel[r["type"]] += 1

    print(f"\nEntity types:")
    for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t:20s} {c:4d}")

    print(f"\nRelation types:")
    for t, c in sorted(by_rel.items(), key=lambda x: -x[1]):
        print(f"  {t:20s} {c:4d}")

    # ── Save Output ────────────────────────────────────────────────────
    output = {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "total_entities": len(deduped_entities),
            "total_relations": len(valid_relations),
            "source_files": len(entries),
            "entity_types": dict(by_type),
            "relation_types": dict(by_rel),
        },
        "entities": deduped_entities,
        "relations": valid_relations,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {OUTPUT} ({OUTPUT.stat().st_size / 1024:.1f} KB)")

    # ── Evidence Samples ──────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("Evidence Trace Samples (3 entities + 3 relations):")
    print(f"{'='*60}")

    for e in deduped_entities[:3]:
        print(f"\n  Entity: {e['name']} ({e['type']})")
        print(f"  source_doc: {e['source_doc']}")
        print(f"  original_sentence: {e['original_sentence']}")
        print(f"  page_context: {e.get('page_context', 'N/A')}")

    for r in valid_relations[:3]:
        src_name = next((e["name"] for e in deduped_entities if e["id"] == r["from"]), r["from"])
        tgt_name = next((e["name"] for e in deduped_entities if e["id"] == r["to"]), r["to"])
        print(f"\n  Relation: {src_name} --[{r['type']}]--> {tgt_name}")
        print(f"  source_doc: {r['source_doc']}")
        print(f"  original_sentence: {r['original_sentence']}")

    return output


if __name__ == "__main__":
    result = main()
