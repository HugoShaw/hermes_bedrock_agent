"""
Business Graph Builder for Stage 05.

Builds the Business Semantic Graph from selected evidence chunks using
a deterministic heuristic approach (with optional LLM upgrade path).

Heuristic strategy:
  1. Create Project node for Murata
  2. Create BusinessDomain nodes from major document groups / top-level sections
  3. Create BusinessProcess nodes from process/workflow/application keywords
  4. Create BusinessStep nodes from step-like subsections
  5. Create BusinessTerm nodes from repeated business nouns
  6. Create Function nodes from screen/function-related content
  7. Create BusinessRule nodes from rule-like sentences
  8. Create Role nodes from role-related content
  9. Create edges following schema relationships
  10. Validate all with schema_registry
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hermes_bedrock_agent.v2.schemas.graph_schema import GraphEdge, GraphNode
from hermes_bedrock_agent.v2.graph.schema_registry import (
    BUSINESS_LABELS,
    BUSINESS_LAYER,
    BUSINESS_RELATION_TYPES,
    is_valid_label,
    is_valid_relation,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Heuristic Patterns
# ============================================================================

# Pattern groups for detecting business entities

PROCESS_PATTERNS = re.compile(
    r"(支払[い]?申請|付款申请|支払処理|支払依頼|入金処理|仕訳処理|"
    r"対帳[処理]?|会計処理|承認[処理フロー]?|申請[処理フロー]?|"
    r"payment\s*request|payment\s*receiving|receiving\s*journal|"
    r"journal\s*base|payment\s*process|approval\s*process|"
    r"业务功能管理|系统管理|用户管理|角色管理|资源管理|"
    r"データ[取込出力]|マスタ[管理登録]|"
    r"登録処理|更新処理|削除処理|検索処理|"
    r"数据背景|数据格式|出错和恢复)",
    re.IGNORECASE,
)

FUNCTION_PATTERNS = re.compile(
    r"(資源管理|角色管理|用户管理|支付管理|付款管理|"
    r"対帳単[画面]?|支払依頼[画面]?|仕訳基礎[画面]?|"
    r"payment\s*(?:req|request)|receiving\s*list|journal\s*base|"
    r"添加[用户资源角色]|修改[用户资源角色]|删除[用户资源角色]|"
    r"检索条件|查询[用户资源角色]|"
    r"入力画面|一覧画面|照会画面|"
    r"授权|编辑)",
    re.IGNORECASE,
)

RULE_PATTERNS = re.compile(
    r"(必須|できない|場合|条件|必要|ルール|"
    r"不可|禁止|許可|権限|制限|"
    r"必填|非必填|格式|规则|不能|"
    r"must|shall|required|cannot|if\s+.{5,30}\s+then)",
    re.IGNORECASE,
)

ROLE_PATTERNS = re.compile(
    r"(管理者|ユーザー|承認者|申請者|"
    r"系统管理员|普通用户|管理员|操作员|"
    r"administrator|admin|approver|requester|user|"
    r"角色[名称]?)",
    re.IGNORECASE,
)

SCREEN_PATTERNS = re.compile(
    r"(画面|一覧|フォーム|ダイアログ|弹出框|"
    r"リスト|テーブル|ビュー|タブ|"
    r"列表|对话框|表格|视图|标签|"
    r"screen|form|dialog|list\s*view|table\s*view)",
    re.IGNORECASE,
)

TERM_PATTERNS = re.compile(
    r"(仕訳|対帳単|支払依頼|入金|出金|振込|"
    r"凭证|对账单|付款申请|收入|支出|转账|"
    r"勘定科目|部門|取引先|通貨|税率|"
    r"科目|部门|供应商|币种|税率|"
    r"account\s*code|department|vendor|currency|tax)",
    re.IGNORECASE,
)


# ============================================================================
# Builder Configuration
# ============================================================================

@dataclass
class BusinessGraphConfig:
    """Configuration for business graph building."""
    max_nodes: int = 500
    max_edges: int = 1000
    min_confidence: float = 0.5
    project_name: str = "Murata MDW支払システム"
    run_id: str = "murata_semantic_v2"
    dataset: str = "murata"


# ============================================================================
# Builder State
# ============================================================================

@dataclass
class BuilderState:
    """Accumulates nodes, edges, and rejected items."""
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)  # node_id -> node
    edges: dict[str, dict[str, Any]] = field(default_factory=dict)  # edge_id -> edge
    rejected: list[dict[str, Any]] = field(default_factory=list)

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


# ============================================================================
# Node/Edge Creation Helpers
# ============================================================================

def _make_node_id(label: str, name: str) -> str:
    """Generate deterministic node_id."""
    return GraphNode.generate_id(BUSINESS_LAYER, label, name.lower().strip())


def _make_edge_id(source_id: str, relation: str, target_id: str) -> str:
    """Generate deterministic edge_id."""
    return GraphEdge.generate_id(source_id, relation, target_id)


def _create_node(
    label: str,
    name: str,
    display_name: str,
    *,
    description: str = "",
    aliases: list[str] | None = None,
    source_ids: list[str] | None = None,
    evidence_chunk_ids: list[str] | None = None,
    confidence: float = 0.8,
    config: BusinessGraphConfig | None = None,
) -> dict[str, Any]:
    """Create a GraphNode dict."""
    cfg = config or BusinessGraphConfig()
    node_id = _make_node_id(label, name)
    return {
        "node_id": node_id,
        "label": label,
        "name": name.lower().strip(),
        "display_name": display_name,
        "layer": BUSINESS_LAYER,
        "aliases": aliases or [],
        "description": description,
        "properties": {},
        "source_ids": source_ids or [],
        "evidence_chunk_ids": evidence_chunk_ids or [],
        "confidence": confidence,
        "run_id": cfg.run_id,
        "dataset": cfg.dataset,
    }


def _create_edge(
    source_node_id: str,
    target_node_id: str,
    relation_type: str,
    *,
    description: str = "",
    source_ids: list[str] | None = None,
    evidence_chunk_ids: list[str] | None = None,
    confidence: float = 0.8,
    config: BusinessGraphConfig | None = None,
) -> dict[str, Any]:
    """Create a GraphEdge dict."""
    cfg = config or BusinessGraphConfig()
    edge_id = _make_edge_id(source_node_id, relation_type, target_node_id)
    return {
        "edge_id": edge_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "relation_type": relation_type,
        "layer": BUSINESS_LAYER,
        "description": description,
        "properties": {},
        "source_ids": source_ids or [],
        "evidence_chunk_ids": evidence_chunk_ids or [],
        "confidence": confidence,
        "run_id": cfg.run_id,
        "dataset": cfg.dataset,
    }


# ============================================================================
# Heuristic Extraction Functions
# ============================================================================

def _extract_project_node(
    config: BusinessGraphConfig,
    candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create the top-level Project node."""
    # Find evidence from operation manuals or top-level docs
    evidence_ids = []
    source_ids = set()
    if candidates:
        for chunk in candidates:
            src = chunk.get("source_path", "")
            if "操作手册" in src or "MDW" in src:
                evidence_ids.append(chunk["chunk_id"])
                source_ids.add(chunk.get("document_id", ""))
                if len(evidence_ids) >= 3:
                    break

    return _create_node(
        label="Project",
        name="murata mdw payment system",
        display_name=config.project_name,
        description="村田MDW支払依頼/付款申请系统 — Enterprise payment processing system",
        aliases=["Murata MDW", "村田支払システム", "村田MDW支付系统", "MDW Payment System"],
        source_ids=list(source_ids)[:3],
        evidence_chunk_ids=evidence_ids[:3],
        confidence=1.0,
        config=config,
    )


def _extract_domains_from_sources(
    candidates: list[dict[str, Any]],
    config: BusinessGraphConfig,
) -> list[dict[str, Any]]:
    """Extract BusinessDomain nodes from document/source structure."""
    domains = []

    # Known business domains from source structure
    domain_defs = [
        {
            "name": "支払管理",
            "display": "支払管理 (Payment Management)",
            "aliases": ["支払", "付款管理", "Payment Management", "支払依頼"],
            "desc": "支払申請・承認・実行に関する業務ドメイン",
            "keywords": ["支払", "付款", "payment", "支付"],
        },
        {
            "name": "入金管理",
            "display": "入金管理 (Receiving Management)",
            "aliases": ["入金", "收款管理", "Receiving Management", "対帳"],
            "desc": "入金確認・対帳に関する業務ドメイン",
            "keywords": ["入金", "receiving", "対帳", "对账"],
        },
        {
            "name": "仕訳管理",
            "display": "仕訳管理 (Journal Management)",
            "aliases": ["仕訳", "凭证管理", "Journal Management", "仕訳基礎"],
            "desc": "仕訳データ管理に関する業務ドメイン",
            "keywords": ["仕訳", "journal", "凭证", "journal_base"],
        },
        {
            "name": "システム管理",
            "display": "システム管理 (System Administration)",
            "aliases": ["系统管理", "System Administration", "System Management"],
            "desc": "ユーザー管理・権限管理・リソース管理に関する業務ドメイン",
            "keywords": ["系统管理", "ユーザー管理", "角色管理", "资源管理", "user", "role", "resource"],
        },
    ]

    for domain_def in domain_defs:
        # Find evidence chunks that mention this domain
        evidence_ids = []
        source_ids = set()
        for chunk in candidates:
            text = chunk.get("text", "").lower()
            source = chunk.get("source_path", "")
            if any(kw.lower() in text for kw in domain_def["keywords"]):
                evidence_ids.append(chunk["chunk_id"])
                source_ids.add(chunk.get("document_id", ""))
                if len(evidence_ids) >= 10:
                    break

        if evidence_ids:
            node = _create_node(
                label="BusinessDomain",
                name=domain_def["name"],
                display_name=domain_def["display"],
                description=domain_def["desc"],
                aliases=domain_def["aliases"],
                source_ids=list(source_ids)[:5],
                evidence_chunk_ids=evidence_ids[:5],
                confidence=0.9,
                config=config,
            )
            domains.append(node)

    return domains


def _extract_processes(
    candidates: list[dict[str, Any]],
    config: BusinessGraphConfig,
) -> list[dict[str, Any]]:
    """Extract BusinessProcess nodes from evidence."""
    processes_found: dict[str, dict] = {}

    # Known processes
    known_processes = [
        {
            "name": "支払申請プロセス",
            "display": "支払申請プロセス (Payment Request Process)",
            "aliases": ["付款申请流程", "Payment Request Process", "支払依頼"],
            "keywords": ["支払申請", "付款申请", "payment request", "支払依頼"],
        },
        {
            "name": "支払承認プロセス",
            "display": "支払承認プロセス (Payment Approval Process)",
            "aliases": ["付款审批流程", "Payment Approval Process"],
            "keywords": ["承認", "审批", "approval"],
        },
        {
            "name": "入金確認プロセス",
            "display": "入金確認プロセス (Receiving Confirmation Process)",
            "aliases": ["收款确认流程", "Receiving Confirmation Process", "対帳処理"],
            "keywords": ["入金", "receiving", "対帳", "对账"],
        },
        {
            "name": "仕訳登録プロセス",
            "display": "仕訳登録プロセス (Journal Entry Process)",
            "aliases": ["凭证登录流程", "Journal Entry Process"],
            "keywords": ["仕訳", "journal", "凭证", "journal_base"],
        },
        {
            "name": "ユーザー管理プロセス",
            "display": "ユーザー管理プロセス (User Management Process)",
            "aliases": ["用户管理流程", "User Management Process"],
            "keywords": ["用户管理", "ユーザー管理", "user management", "用户添加", "用户角色"],
        },
        {
            "name": "リソース管理プロセス",
            "display": "リソース管理プロセス (Resource Management Process)",
            "aliases": ["资源管理流程", "Resource Management Process"],
            "keywords": ["资源管理", "リソース管理", "resource management", "资源编号"],
        },
        {
            "name": "角色管理プロセス",
            "display": "角色管理プロセス (Role Management Process)",
            "aliases": ["角色管理流程", "Role Management Process"],
            "keywords": ["角色管理", "ロール管理", "role management", "角色授权"],
        },
    ]

    for proc_def in known_processes:
        evidence_ids = []
        source_ids = set()
        for chunk in candidates:
            text = chunk.get("text", "").lower()
            if any(kw.lower() in text for kw in proc_def["keywords"]):
                evidence_ids.append(chunk["chunk_id"])
                source_ids.add(chunk.get("document_id", ""))
                if len(evidence_ids) >= 8:
                    break

        if evidence_ids:
            node = _create_node(
                label="BusinessProcess",
                name=proc_def["name"],
                display_name=proc_def["display"],
                aliases=proc_def["aliases"],
                source_ids=list(source_ids)[:5],
                evidence_chunk_ids=evidence_ids[:5],
                confidence=0.85,
                config=config,
            )
            processes_found[proc_def["name"]] = node

    return list(processes_found.values())


def _extract_functions(
    candidates: list[dict[str, Any]],
    config: BusinessGraphConfig,
) -> list[dict[str, Any]]:
    """Extract Function nodes from evidence."""
    functions_found: dict[str, dict] = {}

    known_functions = [
        {"name": "支払依頼入力", "display": "支払依頼入力", "aliases": ["付款申请录入", "Payment Request Input"], "keywords": ["支払依頼", "付款申请", "payment request"]},
        {"name": "対帳単照会", "display": "対帳単照会", "aliases": ["对账单查询", "Receiving List Query"], "keywords": ["対帳", "对账单", "receiving list"]},
        {"name": "仕訳基礎照会", "display": "仕訳基礎照会", "aliases": ["凭证基础查询", "Journal Base Query"], "keywords": ["仕訳基礎", "journal base", "凭证基础"]},
        {"name": "ユーザー追加", "display": "ユーザー追加", "aliases": ["添加用户", "Add User"], "keywords": ["用户添加", "添加用户", "add user", "ユーザー追加"]},
        {"name": "角色授権", "display": "角色授権", "aliases": ["角色授权", "Role Authorization"], "keywords": ["角色授权", "ロール授権", "role authorization"]},
        {"name": "リソース追加", "display": "リソース追加", "aliases": ["添加资源", "Add Resource"], "keywords": ["添加资源", "リソース追加", "add resource", "资源添加"]},
        {"name": "データ出力", "display": "データ出力 (Data Export)", "aliases": ["数据输出", "Data Export"], "keywords": ["数据格式", "データ出力", "data export", "输出"]},
        {"name": "データ入力", "display": "データ入力 (Data Import)", "aliases": ["数据输入", "Data Import"], "keywords": ["数据背景", "データ入力", "data import", "输入"]},
    ]

    for func_def in known_functions:
        evidence_ids = []
        source_ids = set()
        for chunk in candidates:
            text = chunk.get("text", "").lower()
            if any(kw.lower() in text for kw in func_def["keywords"]):
                evidence_ids.append(chunk["chunk_id"])
                source_ids.add(chunk.get("document_id", ""))
                if len(evidence_ids) >= 5:
                    break

        if evidence_ids:
            node = _create_node(
                label="Function",
                name=func_def["name"],
                display_name=func_def["display"],
                aliases=func_def["aliases"],
                source_ids=list(source_ids)[:3],
                evidence_chunk_ids=evidence_ids[:3],
                confidence=0.8,
                config=config,
            )
            functions_found[func_def["name"]] = node

    return list(functions_found.values())


def _extract_roles(
    candidates: list[dict[str, Any]],
    config: BusinessGraphConfig,
) -> list[dict[str, Any]]:
    """Extract Role nodes from evidence."""
    roles_found: dict[str, dict] = {}

    known_roles = [
        {"name": "システム管理者", "display": "システム管理者", "aliases": ["系统管理员", "System Administrator"], "keywords": ["系统管理员", "管理者", "administrator"]},
        {"name": "一般ユーザー", "display": "一般ユーザー", "aliases": ["普通用户", "Regular User"], "keywords": ["普通用户", "一般ユーザー", "regular user"]},
    ]

    for role_def in known_roles:
        evidence_ids = []
        source_ids = set()
        for chunk in candidates:
            text = chunk.get("text", "").lower()
            if any(kw.lower() in text for kw in role_def["keywords"]):
                evidence_ids.append(chunk["chunk_id"])
                source_ids.add(chunk.get("document_id", ""))
                if len(evidence_ids) >= 5:
                    break

        if evidence_ids:
            node = _create_node(
                label="Role",
                name=role_def["name"],
                display_name=role_def["display"],
                aliases=role_def["aliases"],
                source_ids=list(source_ids)[:3],
                evidence_chunk_ids=evidence_ids[:3],
                confidence=0.8,
                config=config,
            )
            roles_found[role_def["name"]] = node

    return list(roles_found.values())


def _extract_business_rules(
    candidates: list[dict[str, Any]],
    config: BusinessGraphConfig,
) -> list[dict[str, Any]]:
    """Extract BusinessRule nodes from rule-like sentences."""
    rules_found: dict[str, dict] = {}

    for chunk in candidates:
        text = chunk.get("text", "")
        # Look for rule-like sentences
        if not RULE_PATTERNS.search(text):
            continue

        # Extract individual rule sentences
        sentences = re.split(r"[。\n]", text)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < 15 or len(sent) > 200:
                continue
            if not RULE_PATTERNS.search(sent):
                continue

            # Create a rule name from the sentence
            rule_name = sent[:60].strip()
            if rule_name in rules_found:
                # Add more evidence to existing rule
                rules_found[rule_name]["evidence_chunk_ids"].append(chunk["chunk_id"])
                continue

            node = _create_node(
                label="BusinessRule",
                name=rule_name,
                display_name=rule_name,
                description=sent[:200],
                source_ids=[chunk.get("document_id", "")],
                evidence_chunk_ids=[chunk["chunk_id"]],
                confidence=0.7,
                config=config,
            )
            rules_found[rule_name] = node

            if len(rules_found) >= 50:
                break

        if len(rules_found) >= 50:
            break

    return list(rules_found.values())


def _extract_business_terms(
    candidates: list[dict[str, Any]],
    config: BusinessGraphConfig,
) -> list[dict[str, Any]]:
    """Extract BusinessTerm nodes from repeated business nouns."""
    terms_found: dict[str, dict] = {}

    known_terms = [
        {"name": "仕訳", "display": "仕訳 (Journal Entry)", "aliases": ["凭证", "Journal Entry", "仕訳伝票"]},
        {"name": "対帳単", "display": "対帳単 (Reconciliation Statement)", "aliases": ["对账单", "Reconciliation Statement"]},
        {"name": "支払依頼", "display": "支払依頼 (Payment Request)", "aliases": ["付款申请", "Payment Request"]},
        {"name": "入金", "display": "入金 (Receipt/Receiving)", "aliases": ["收款", "Receipt", "Receiving"]},
        {"name": "勘定科目", "display": "勘定科目 (Account Code)", "aliases": ["科目", "Account Code", "ACCOUNT_CODE"]},
        {"name": "リソース", "display": "リソース (Resource)", "aliases": ["资源", "Resource"]},
        {"name": "角色", "display": "角色 (Role)", "aliases": ["ロール", "Role"]},
    ]

    for term_def in known_terms:
        # Find evidence
        evidence_ids = []
        source_ids = set()
        term_lower = term_def["name"].lower()
        for chunk in candidates:
            text = chunk.get("text", "").lower()
            if term_lower in text or any(a.lower() in text for a in term_def["aliases"]):
                evidence_ids.append(chunk["chunk_id"])
                source_ids.add(chunk.get("document_id", ""))
                if len(evidence_ids) >= 5:
                    break

        if evidence_ids:
            node = _create_node(
                label="BusinessTerm",
                name=term_def["name"],
                display_name=term_def["display"],
                aliases=term_def["aliases"],
                source_ids=list(source_ids)[:3],
                evidence_chunk_ids=evidence_ids[:3],
                confidence=0.85,
                config=config,
            )
            terms_found[term_def["name"]] = node

    return list(terms_found.values())


def _build_edges(
    state: BuilderState,
    config: BusinessGraphConfig,
) -> None:
    """Build edges between existing nodes."""
    # Get node lookups
    nodes_by_label: dict[str, list[dict]] = defaultdict(list)
    for node in state.nodes.values():
        nodes_by_label[node["label"]].append(node)

    project_nodes = nodes_by_label.get("Project", [])
    domain_nodes = nodes_by_label.get("BusinessDomain", [])
    process_nodes = nodes_by_label.get("BusinessProcess", [])
    function_nodes = nodes_by_label.get("Function", [])
    role_nodes = nodes_by_label.get("Role", [])
    term_nodes = nodes_by_label.get("BusinessTerm", [])
    rule_nodes = nodes_by_label.get("BusinessRule", [])

    # Project CONTAINS BusinessDomain
    for proj in project_nodes:
        for domain in domain_nodes:
            edge = _create_edge(
                proj["node_id"], domain["node_id"], "CONTAINS",
                description=f"Project contains domain {domain['display_name']}",
                evidence_chunk_ids=domain["evidence_chunk_ids"][:2],
                source_ids=domain["source_ids"][:2],
                confidence=0.95,
                config=config,
            )
            state.edges[edge["edge_id"]] = edge

    # Map processes to domains
    domain_process_map = {
        "支払管理": ["支払申請プロセス", "支払承認プロセス"],
        "入金管理": ["入金確認プロセス"],
        "仕訳管理": ["仕訳登録プロセス"],
        "システム管理": ["ユーザー管理プロセス", "リソース管理プロセス", "角色管理プロセス"],
    }

    domain_by_name = {d["name"]: d for d in domain_nodes}
    process_by_name = {p["name"]: p for p in process_nodes}

    for domain_name, proc_names in domain_process_map.items():
        domain = domain_by_name.get(domain_name)
        if not domain:
            continue
        for proc_name in proc_names:
            proc = process_by_name.get(proc_name)
            if not proc:
                continue
            edge = _create_edge(
                domain["node_id"], proc["node_id"], "CONTAINS",
                description=f"{domain['display_name']} contains {proc['display_name']}",
                evidence_chunk_ids=proc["evidence_chunk_ids"][:2],
                source_ids=proc["source_ids"][:2],
                confidence=0.85,
                config=config,
            )
            state.edges[edge["edge_id"]] = edge

    # Map functions to domains
    domain_function_map = {
        "支払管理": ["支払依頼入力"],
        "入金管理": ["対帳単照会"],
        "仕訳管理": ["仕訳基礎照会"],
        "システム管理": ["ユーザー追加", "角色授権", "リソース追加", "データ出力", "データ入力"],
    }

    func_by_name = {f["name"]: f for f in function_nodes}
    for domain_name, func_names in domain_function_map.items():
        domain = domain_by_name.get(domain_name)
        if not domain:
            continue
        for func_name in func_names:
            func = func_by_name.get(func_name)
            if not func:
                continue
            edge = _create_edge(
                domain["node_id"], func["node_id"], "HAS_FUNCTION",
                description=f"{domain['display_name']} has function {func['display_name']}",
                evidence_chunk_ids=func["evidence_chunk_ids"][:2],
                source_ids=func["source_ids"][:2],
                confidence=0.8,
                config=config,
            )
            state.edges[edge["edge_id"]] = edge

    # BusinessDomain HAS_TERM BusinessTerm
    for term in term_nodes:
        # Assign terms to the most relevant domain
        term_name_lower = term["name"].lower()
        best_domain = None
        if any(kw in term_name_lower for kw in ["仕訳", "凭证"]):
            best_domain = domain_by_name.get("仕訳管理")
        elif any(kw in term_name_lower for kw in ["支払", "付款"]):
            best_domain = domain_by_name.get("支払管理")
        elif any(kw in term_name_lower for kw in ["入金", "対帳", "收款"]):
            best_domain = domain_by_name.get("入金管理")
        elif any(kw in term_name_lower for kw in ["リソース", "角色", "资源"]):
            best_domain = domain_by_name.get("システム管理")

        if best_domain:
            edge = _create_edge(
                best_domain["node_id"], term["node_id"], "HAS_TERM",
                description=f"{best_domain['display_name']} has term {term['display_name']}",
                evidence_chunk_ids=term["evidence_chunk_ids"][:2],
                source_ids=term["source_ids"][:2],
                confidence=0.8,
                config=config,
            )
            state.edges[edge["edge_id"]] = edge

    # BusinessProcess HAS_RULE BusinessRule (assign rules to processes based on overlap)
    for rule in rule_nodes[:30]:
        rule_text = rule.get("description", "").lower()
        best_process = None
        for proc in process_nodes:
            proc_keywords = [a.lower() for a in proc.get("aliases", [])] + [proc["name"].lower()]
            if any(kw in rule_text for kw in proc_keywords):
                best_process = proc
                break
        if best_process:
            edge = _create_edge(
                best_process["node_id"], rule["node_id"], "HAS_RULE",
                description=f"{best_process['display_name']} has rule",
                evidence_chunk_ids=rule["evidence_chunk_ids"][:2],
                source_ids=rule["source_ids"][:1],
                confidence=0.7,
                config=config,
            )
            state.edges[edge["edge_id"]] = edge

    # Role USES Function  
    for role in role_nodes:
        # Admin uses all system management functions
        if "管理" in role["name"]:
            for func in function_nodes:
                evidence_overlap = set(role["evidence_chunk_ids"]) & set(func["evidence_chunk_ids"])
                if evidence_overlap or "管理" in func["name"] or "追加" in func["name"] or "授権" in func["name"]:
                    edge = _create_edge(
                        role["node_id"], func["node_id"], "USES",
                        description=f"{role['display_name']} uses {func['display_name']}",
                        evidence_chunk_ids=list(evidence_overlap)[:2] or func["evidence_chunk_ids"][:1],
                        source_ids=role["source_ids"][:1],
                        confidence=0.75,
                        config=config,
                    )
                    state.edges[edge["edge_id"]] = edge


# ============================================================================
# Main Builder
# ============================================================================

def build_business_graph(
    candidates: list[dict[str, Any]],
    *,
    config: BusinessGraphConfig | None = None,
) -> BuilderState:
    """Build the Business Semantic Graph using heuristic extraction.

    Args:
        candidates: Selected business evidence chunks.
        config: Builder configuration.

    Returns:
        BuilderState with nodes, edges, and rejected items.
    """
    cfg = config or BusinessGraphConfig()
    state = BuilderState()

    logger.info(f"Building business graph from {len(candidates)} candidate chunks")

    # 1. Project node
    project_node = _extract_project_node(cfg, candidates)
    state.nodes[project_node["node_id"]] = project_node

    # 2. Business domains
    domain_nodes = _extract_domains_from_sources(candidates, cfg)
    for node in domain_nodes:
        state.nodes[node["node_id"]] = node
    logger.info(f"  Extracted {len(domain_nodes)} domain nodes")

    # 3. Business processes
    process_nodes = _extract_processes(candidates, cfg)
    for node in process_nodes:
        state.nodes[node["node_id"]] = node
    logger.info(f"  Extracted {len(process_nodes)} process nodes")

    # 4. Functions
    function_nodes = _extract_functions(candidates, cfg)
    for node in function_nodes:
        state.nodes[node["node_id"]] = node
    logger.info(f"  Extracted {len(function_nodes)} function nodes")

    # 5. Roles
    role_nodes = _extract_roles(candidates, cfg)
    for node in role_nodes:
        state.nodes[node["node_id"]] = node
    logger.info(f"  Extracted {len(role_nodes)} role nodes")

    # 6. Business terms
    term_nodes = _extract_business_terms(candidates, cfg)
    for node in term_nodes:
        state.nodes[node["node_id"]] = node
    logger.info(f"  Extracted {len(term_nodes)} term nodes")

    # 7. Business rules
    rule_nodes = _extract_business_rules(candidates, cfg)
    for node in rule_nodes:
        state.nodes[node["node_id"]] = node
    logger.info(f"  Extracted {len(rule_nodes)} rule nodes")

    # 8. Build edges
    _build_edges(state, cfg)
    logger.info(f"  Built {state.edge_count} edges")

    # 9. Validate
    _validate_state(state)

    logger.info(
        f"Business graph complete: {state.node_count} nodes, "
        f"{state.edge_count} edges, {len(state.rejected)} rejected"
    )

    return state


def _validate_state(state: BuilderState) -> None:
    """Validate all nodes and edges against schema."""
    invalid_nodes = []
    for node_id, node in list(state.nodes.items()):
        if not is_valid_label(node["label"], BUSINESS_LAYER):
            state.rejected.append({
                "type": "node",
                "item": node,
                "reason": f"Label '{node['label']}' not valid for business layer",
            })
            invalid_nodes.append(node_id)

    for node_id in invalid_nodes:
        del state.nodes[node_id]

    invalid_edges = []
    for edge_id, edge in list(state.edges.items()):
        if not is_valid_relation(edge["relation_type"], BUSINESS_LAYER):
            state.rejected.append({
                "type": "edge",
                "item": edge,
                "reason": f"Relation '{edge['relation_type']}' not valid for business layer",
            })
            invalid_edges.append(edge_id)
        # Check that source and target nodes exist
        elif edge["source_node_id"] not in state.nodes:
            state.rejected.append({
                "type": "edge",
                "item": edge,
                "reason": f"Source node '{edge['source_node_id']}' not found",
            })
            invalid_edges.append(edge_id)
        elif edge["target_node_id"] not in state.nodes:
            state.rejected.append({
                "type": "edge",
                "item": edge,
                "reason": f"Target node '{edge['target_node_id']}' not found",
            })
            invalid_edges.append(edge_id)

    for edge_id in invalid_edges:
        del state.edges[edge_id]


def save_graph_outputs(
    state: BuilderState,
    output_dir: Path,
) -> tuple[Path, Path, Path]:
    """Save business graph outputs to JSONL files.

    Returns:
        (nodes_path, edges_path, rejected_path)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = output_dir / "business_nodes.jsonl"
    edges_path = output_dir / "business_edges.jsonl"
    rejected_path = output_dir / "rejected_business_graph_items.jsonl"

    with open(nodes_path, "w", encoding="utf-8") as f:
        for node in state.nodes.values():
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    with open(edges_path, "w", encoding="utf-8") as f:
        for edge in state.edges.values():
            f.write(json.dumps(edge, ensure_ascii=False) + "\n")

    with open(rejected_path, "w", encoding="utf-8") as f:
        for item in state.rejected:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    logger.info(
        f"Saved: {len(state.nodes)} nodes to {nodes_path}, "
        f"{len(state.edges)} edges to {edges_path}, "
        f"{len(state.rejected)} rejected to {rejected_path}"
    )

    return nodes_path, edges_path, rejected_path
