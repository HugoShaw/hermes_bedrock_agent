"""i18n Enrichment for Graph Entities and Relations.

Phase 10B: Adds multilingual display names, aliases, and descriptions
to entities and relations using Bedrock Claude LLM.

Modes:
- dry_run=True (default): Generate artifacts only, no Neptune writes
- dry_run=False: Also update Neptune properties

Design:
- Batch processing with configurable batch_size
- LLM calls are mockable (inject via bedrock_client parameter)
- Outputs JSONL artifacts for review before Neptune update
- Prioritizes high-degree / high-importance entities first
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


# ─── Protocols for dependency injection ──────────────────────────────────────


class LLMClient(Protocol):
    """Protocol for LLM client (Bedrock or mock)."""

    def invoke(self, prompt: str, *, max_tokens: int = 4096) -> str:
        """Invoke LLM and return text response."""
        ...


class NeptuneClientProtocol(Protocol):
    """Protocol for Neptune client."""

    def execute_query(self, query: str, *, parameters: dict | None = None) -> dict:
        ...


# ─── Data models ─────────────────────────────────────────────────────────────


@dataclass
class EntityI18n:
    """i18n enrichment result for an entity."""

    entity_id: str
    name: str
    canonical_name: str
    entity_type: str

    # Multi-language display names
    display_name: str = ""
    display_name_zh: str = ""
    display_name_en: str = ""
    display_name_ja: str = ""

    # Multi-language aliases
    aliases_zh: list[str] = field(default_factory=list)
    aliases_en: list[str] = field(default_factory=list)
    aliases_ja: list[str] = field(default_factory=list)

    # Multi-language descriptions
    description_zh: str = ""
    description_en: str = ""
    description_ja: str = ""

    # Label mode hint
    label_mode_hint: str = "mixed"  # business | technical | mixed

    # Metadata
    model_name: str = ""
    enriched_at: str = ""

    # Live enrichment provenance
    enrichment_source: str = ""  # "live_llm" | "mock" | "fallback" | "builtin"
    enrichment_confidence: float = 0.5
    enrichment_model: str = ""
    enrichment_error: str = ""
    updated_at: str = ""

    # Extended alias fields (live enrichment)
    technical_aliases: list[str] = field(default_factory=list)
    business_aliases_zh: list[str] = field(default_factory=list)
    business_aliases_en: list[str] = field(default_factory=list)
    business_aliases_ja: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "canonical_name": self.canonical_name,
            "entity_type": self.entity_type,
            "display_name": self.display_name,
            "display_name_zh": self.display_name_zh,
            "display_name_en": self.display_name_en,
            "display_name_ja": self.display_name_ja,
            "aliases_zh": self.aliases_zh,
            "aliases_en": self.aliases_en,
            "aliases_ja": self.aliases_ja,
            "description_zh": self.description_zh,
            "description_en": self.description_en,
            "description_ja": self.description_ja,
            "label_mode_hint": self.label_mode_hint,
            "model_name": self.model_name,
            "enriched_at": self.enriched_at,
            "enrichment_source": self.enrichment_source,
            "enrichment_confidence": self.enrichment_confidence,
            "enrichment_model": self.enrichment_model,
            "enrichment_error": self.enrichment_error,
            "updated_at": self.updated_at,
            "technical_aliases": self.technical_aliases,
            "business_aliases_zh": self.business_aliases_zh,
            "business_aliases_en": self.business_aliases_en,
            "business_aliases_ja": self.business_aliases_ja,
        }


@dataclass
class RelationI18n:
    """i18n enrichment result for a relation type."""

    relation_type: str

    # Multi-language labels
    display_label: str = ""
    label_zh: str = ""
    label_en: str = ""
    label_ja: str = ""

    # Multi-language descriptions
    description_zh: str = ""
    description_en: str = ""
    description_ja: str = ""

    # Metadata
    model_name: str = ""
    enriched_at: str = ""

    def to_dict(self) -> dict:
        return {
            "relation_type": self.relation_type,
            "display_label": self.display_label,
            "label_zh": self.label_zh,
            "label_en": self.label_en,
            "label_ja": self.label_ja,
            "description_zh": self.description_zh,
            "description_en": self.description_en,
            "description_ja": self.description_ja,
            "model_name": self.model_name,
            "enriched_at": self.enriched_at,
        }


@dataclass
class EnrichmentConfig:
    """Configuration for i18n enrichment."""

    max_entities: int = 200
    max_relations: int = 50
    batch_size: int = 10
    min_degree: int = 20
    priority_entity_types: list[str] = field(default_factory=lambda: [
        "table", "process", "screen", "module", "api", "service", "system",
    ])
    priority_entities: list[str] = field(default_factory=lambda: [
        "JOURNAL_BASE", "payment_req", "muratapr", "MURATA_20180530.sql",
        "AC_DESC.CSV", "RECEIVING_JOURNAL", "MV0008", "用户角色关系表",
    ])
    dry_run: bool = True
    model_name: str = "apac.anthropic.claude-sonnet-4-20250514-v1:0"


# ─── Built-in Relation i18n Map ──────────────────────────────────────────────

BUILTIN_RELATION_I18N_MAP: dict[str, dict[str, str]] = {
    "contains": {"zh": "包含", "en": "contains", "ja": "含む"},
    "references": {"zh": "引用", "en": "references", "ja": "参照する"},
    "writes_to": {"zh": "写入", "en": "writes to", "ja": "書き込む"},
    "custom": {"zh": "自定义关系", "en": "custom relation", "ja": "カスタム関係"},
    "calls": {"zh": "调用", "en": "calls", "ja": "呼び出す"},
    "depends_on": {"zh": "依赖", "en": "depends on", "ja": "依存する"},
    "part_of": {"zh": "属于", "en": "part of", "ja": "一部である"},
    "reads_from": {"zh": "读取", "en": "reads from", "ja": "読み取る"},
    "related_to": {"zh": "关联", "en": "related to", "ja": "関連する"},
    "belongs_to": {"zh": "属于", "en": "belongs to", "ja": "属する"},
    "manages": {"zh": "管理", "en": "manages", "ja": "管理する"},
    "defined_in": {"zh": "定义于", "en": "defined in", "ja": "定義される"},
    "produces": {"zh": "生成", "en": "produces", "ja": "生成する"},
    "connects_to": {"zh": "连接", "en": "connects to", "ja": "接続する"},
    "implements": {"zh": "实现", "en": "implements", "ja": "実装する"},
    "used_by": {"zh": "被使用", "en": "used by", "ja": "使用される"},
    "describes": {"zh": "描述", "en": "describes", "ja": "記述する"},
    "triggers": {"zh": "触发", "en": "triggers", "ja": "トリガーする"},
    "consumes": {"zh": "消费", "en": "consumes", "ja": "消費する"},
    "inherits": {"zh": "继承", "en": "inherits", "ja": "継承する"},
}


# ─── Mock/Deterministic Enrichment ───────────────────────────────────────────

# Built-in deterministic i18n data for priority entities (no LLM needed)
_PRIORITY_ENTITY_I18N: dict[str, dict] = {
    "journal_base": {
        "display_name": "JOURNAL_BASE (仕訳基礎)",
        "display_name_zh": "记账基础表",
        "display_name_en": "Journal Base Table",
        "display_name_ja": "仕訳基礎テーブル",
        "aliases_zh": ["记账基础", "仕訳基礎", "日记帐基础表", "凭证基础表"],
        "aliases_en": ["journal base", "journal entries table", "JB table"],
        "aliases_ja": ["仕訳基礎", "仕訳テーブル", "ジャーナルベース", "仕訳基礎表"],
        "description_zh": "存储财务和物料交易日记帐条目的数据库表。",
        "description_en": "Database table storing journal entries with financial and material transaction data.",
        "description_ja": "財務および資材取引の仕訳データを格納するデータベーステーブル。",
        "label_mode_hint": "technical",
    },
    "payment_req": {
        "display_name": "payment_req (付款申請)",
        "display_name_zh": "付款申请表",
        "display_name_en": "Payment Request Table",
        "display_name_ja": "支払申請テーブル",
        "aliases_zh": ["付款申请", "付款申請", "支付申请", "付款请求表"],
        "aliases_en": ["payment request", "pay req", "payment requisition", "paymentrequest"],
        "aliases_ja": ["支払申請", "支払リクエスト", "ペイメントリクエスト"],
        "description_zh": "存储付款申请信息的数据库表，包含付款金额、供应商、审批状态等。",
        "description_en": "Database table storing payment request information including amount, vendor, and approval status.",
        "description_ja": "支払い申請情報を格納するデータベーステーブル。金額、仕入先、承認状態などを含む。",
        "label_mode_hint": "technical",
    },
    "muratapr": {
        "display_name": "muratapr (Murata PRシステム)",
        "display_name_zh": "Murata PR系统",
        "display_name_en": "Murata PR System",
        "display_name_ja": "Murata PRシステム",
        "aliases_zh": ["Murata PR系统", "村田PR", "PR系统", "村田PR系统"],
        "aliases_en": ["Murata PR", "murata pr system", "PR application"],
        "aliases_ja": ["ムラタPR", "Murata PR", "PRシステム", "村田PRシステム"],
        "description_zh": "Murata企业应用主系统，包含ERP/财务/支付处理功能。",
        "description_en": "Main Murata enterprise application system containing ERP/financial/payment processing.",
        "description_ja": "ERP/財務/支払処理機能を含むMurata企業アプリケーションのメインシステム。",
        "label_mode_hint": "business",
    },
    "murata_20180530.sql": {
        "display_name": "MURATA_20180530.sql",
        "display_name_zh": "Murata数据库脚本(2018-05-30)",
        "display_name_en": "Murata Database Script (2018-05-30)",
        "display_name_ja": "Murataデータベーススクリプト(2018-05-30)",
        "aliases_zh": ["Murata SQL脚本", "数据库定义脚本"],
        "aliases_en": ["Murata SQL script", "database schema script"],
        "aliases_ja": ["MurataDBスクリプト", "データベース定義"],
        "description_zh": "Murata系统的数据库结构定义SQL脚本。",
        "description_en": "SQL script defining the Murata system database schema.",
        "description_ja": "Murataシステムのデータベース構造定義SQLスクリプト。",
        "label_mode_hint": "technical",
    },
    "ac_desc.csv": {
        "display_name": "AC_DESC.CSV (勘定科目マスタ)",
        "display_name_zh": "科目描述CSV",
        "display_name_en": "Account Description CSV",
        "display_name_ja": "勘定科目マスタ",
        "aliases_zh": ["科目描述CSV", "会计科目描述", "科目代码表"],
        "aliases_en": ["account description", "AC description CSV", "chart of accounts"],
        "aliases_ja": ["勘定科目マスタ", "AC記述CSV", "勘定科目テーブル"],
        "description_zh": "包含会计科目代码和描述的CSV主数据文件。",
        "description_en": "CSV master data file containing account codes and descriptions.",
        "description_ja": "勘定科目コードと説明を含むCSVマスタデータファイル。",
        "label_mode_hint": "technical",
    },
    "receiving_journal": {
        "display_name": "RECEIVING_JOURNAL (入荷仕訳)",
        "display_name_zh": "收货日记帐",
        "display_name_en": "Receiving Journal",
        "display_name_ja": "入荷仕訳テーブル",
        "aliases_zh": ["收货日记帐", "入库凭证", "收货凭证表"],
        "aliases_en": ["receiving journal", "goods receipt journal"],
        "aliases_ja": ["入荷仕訳", "受入仕訳テーブル", "入荷伝票"],
        "description_zh": "记录物料入库和收货相关仕訳数据的表。",
        "description_en": "Table recording journal entries related to goods receiving.",
        "description_ja": "物品の入荷および受入に関する仕訳データを記録するテーブル。",
        "label_mode_hint": "technical",
    },
    "mv0008": {
        "display_name": "MV0008 (照会画面)",
        "display_name_zh": "MV0008查询画面",
        "display_name_en": "MV0008 Inquiry Screen",
        "display_name_ja": "MV0008照会画面",
        "aliases_zh": ["MV0008画面", "查询画面", "MV0008查询"],
        "aliases_en": ["MV0008 screen", "inquiry screen", "MV0008 inquiry"],
        "aliases_ja": ["MV0008画面", "照会画面", "MV0008照会"],
        "description_zh": "MV0008查询画面，用于数据检索和显示。",
        "description_en": "MV0008 inquiry screen for data retrieval and display.",
        "description_ja": "データ検索と表示のためのMV0008照会画面。",
        "label_mode_hint": "mixed",
    },
    "用户角色关系表": {
        "display_name": "用户角色关系表",
        "display_name_zh": "用户角色关系表",
        "display_name_en": "User Role Mapping Table",
        "display_name_ja": "ユーザーロール関係テーブル",
        "aliases_zh": ["用户角色表", "角色关系表", "权限映射表"],
        "aliases_en": ["user role table", "role mapping", "user permission table"],
        "aliases_ja": ["ユーザーロールテーブル", "権限マッピング", "ロール関係"],
        "description_zh": "定义用户和角色之间映射关系的表。",
        "description_en": "Table defining the mapping between users and roles.",
        "description_ja": "ユーザーとロールの間のマッピング関係を定義するテーブル。",
        "label_mode_hint": "business",
    },
}


class MockDeterministicLLM:
    """Mock LLM client that returns deterministic i18n enrichment.

    Uses _PRIORITY_ENTITY_I18N for known entities and generates
    simple rule-based enrichment for unknown entities.
    Implements the LLMClient protocol (invoke method).
    """

    def __init__(self):
        self.call_count = 0

    def invoke(self, prompt: str, *, max_tokens: int = 4096) -> str:
        """Return deterministic JSON enrichment based on entity name in prompt."""
        self.call_count += 1
        prompt_lower = prompt.lower()

        # Check for known priority entities
        for key, data in _PRIORITY_ENTITY_I18N.items():
            if f"- name: {key}" in prompt_lower or f"canonical_name: {key}" in prompt_lower:
                return json.dumps(data, ensure_ascii=False)

        # For relation enrichment prompts
        if "relation type:" in prompt_lower:
            for rtype, labels in BUILTIN_RELATION_I18N_MAP.items():
                if f"relation type: {rtype}" in prompt_lower:
                    return json.dumps({
                        "display_label": labels["en"].title(),
                        "label_zh": labels["zh"],
                        "label_en": labels["en"],
                        "label_ja": labels["ja"],
                        "description_zh": f"表示{labels['zh']}关系",
                        "description_en": f"Represents a {labels['en']} relationship",
                        "description_ja": f"{labels['ja']}関係を表す",
                    }, ensure_ascii=False)

        # Fallback: generate minimal enrichment from entity name
        name = self._extract_name(prompt)
        return json.dumps({
            "display_name": name,
            "display_name_zh": "",
            "display_name_en": name,
            "display_name_ja": "",
            "aliases_zh": [],
            "aliases_en": [name.lower()] if name else [],
            "aliases_ja": [],
            "description_zh": "",
            "description_en": f"Entity: {name}",
            "description_ja": "",
            "label_mode_hint": "technical",
        }, ensure_ascii=False)

    @staticmethod
    def _extract_name(prompt: str) -> str:
        """Extract entity name from prompt text."""
        import re
        match = re.search(r'- name: (.+)', prompt, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return "unknown"


# ─── LLM Prompts ─────────────────────────────────────────────────────────────


ENTITY_I18N_PROMPT = """You are a multilingual enterprise system analyst. Given entity metadata from a knowledge graph, generate multilingual display names, aliases, and descriptions.

ENTITY:
- name: {name}
- canonical_name: {canonical_name}
- entity_type: {entity_type}
- description: {description}
- context: This entity is from the Murata enterprise application system (ERP/accounting/payment processing). It has {degree} connections in the knowledge graph.

RULES:
1. Do NOT change entity_id or canonical_name.
2. Technical names (table names, class names, file names) must be preserved as-is in aliases.
3. Generate business-friendly names in Chinese (zh), English (en), and Japanese (ja).
4. aliases should include common variants: abbreviations, full forms, alternate scripts.
5. For table names like JOURNAL_BASE: provide the business meaning (e.g., "仕訳基礎テーブル" in Japanese).
6. For system names like muratapr: provide the full form (e.g., "Murata PRシステム").
7. If uncertain about business meaning, keep the technical name. Do NOT invent meanings.
8. label_mode_hint: "technical" for code/DB entities, "business" for process/screen entities, "mixed" for both.

OUTPUT (strict JSON, no markdown):
{{
  "display_name": "<primary display name, prefer English technical + CJK business>",
  "display_name_zh": "<Chinese display name>",
  "display_name_en": "<English display name>",
  "display_name_ja": "<Japanese display name>",
  "aliases_zh": ["<Chinese alias 1>", ...],
  "aliases_en": ["<English alias 1>", ...],
  "aliases_ja": ["<Japanese alias 1>", ...],
  "description_zh": "<1-2 sentence Chinese description>",
  "description_en": "<1-2 sentence English description>",
  "description_ja": "<1-2 sentence Japanese description>",
  "label_mode_hint": "technical|business|mixed"
}}"""


RELATION_I18N_PROMPT = """You are a multilingual enterprise system analyst. Given a relation type from a knowledge graph, generate multilingual labels and descriptions.

RELATION TYPE: {relation_type}
USAGE COUNT: {count} edges in the graph
EXAMPLE PAIRS: {examples}

CONTEXT: This is from the Murata enterprise application system knowledge graph (ERP/accounting/payment processing).

RULES:
1. Generate business-friendly labels in Chinese (zh), English (en), and Japanese (ja).
2. Labels should be concise (2-4 words max).
3. Keep technical meaning accurate.
4. display_label should be the most readable short form.

OUTPUT (strict JSON, no markdown):
{{
  "display_label": "<primary display label in English>",
  "label_zh": "<Chinese label>",
  "label_en": "<English label>",
  "label_ja": "<Japanese label>",
  "description_zh": "<Chinese description of this relation type>",
  "description_en": "<English description of this relation type>",
  "description_ja": "<Japanese description of this relation type>"
}}"""


# ─── Core Enricher ───────────────────────────────────────────────────────────


class I18nEnricher:
    """Enriches graph entities and relations with multilingual metadata.

    Usage:
        enricher = I18nEnricher(llm_client, neptune_client, config)
        entities = enricher.select_entities_for_enrichment()
        results = enricher.batch_enrich_entities(entities)
        enricher.write_i18n_artifacts(results, output_dir)
    """

    def __init__(
        self,
        llm_client: LLMClient,
        neptune_client: Optional[NeptuneClientProtocol] = None,
        config: Optional[EnrichmentConfig] = None,
    ):
        self._llm = llm_client
        self._neptune = neptune_client
        self.config = config or EnrichmentConfig()

    def select_entities_for_enrichment(
        self,
        *,
        entities_jsonl_path: Optional[str | Path] = None,
    ) -> list[dict]:
        """Select entities for i18n enrichment based on priority criteria.

        Priority order:
        1. Explicitly listed priority entities
        2. High-degree entities (degree >= min_degree)
        3. Priority entity types

        Can load from entities.jsonl OR query Neptune.

        Returns:
            List of entity dicts with name, canonical_name, entity_type,
            entity_id, description, degree.
        """
        selected: list[dict] = []
        seen_ids: set[str] = set()

        if entities_jsonl_path:
            selected = self._select_from_jsonl(Path(entities_jsonl_path))
        elif self._neptune:
            selected = self._select_from_neptune()
        else:
            raise ValueError("Need either entities_jsonl_path or neptune_client")

        # Deduplicate
        result = []
        for ent in selected:
            eid = ent.get("entity_id", "")
            if eid not in seen_ids:
                seen_ids.add(eid)
                result.append(ent)
            if len(result) >= self.config.max_entities:
                break

        return result

    def _select_from_jsonl(self, path: Path) -> list[dict]:
        """Select from entities.jsonl file."""
        entities = []
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                entities.append(json.loads(line))

        # Sort by priority
        priority_names = {n.lower() for n in self.config.priority_entities}
        priority_types = set(self.config.priority_entity_types)

        def sort_key(e):
            name_lower = e.get("name", "").lower()
            canonical = e.get("canonical_name", "").lower()
            etype = e.get("entity_type", "")

            # Priority entities first
            is_priority = name_lower in priority_names or canonical in priority_names
            # Then by type
            is_priority_type = etype in priority_types
            # Then by... we don't have degree in jsonl without Neptune
            return (not is_priority, not is_priority_type, name_lower)

        entities.sort(key=sort_key)
        return entities[:self.config.max_entities]

    def _select_from_neptune(self) -> list[dict]:
        """Select from Neptune based on degree + priority."""
        assert self._neptune is not None

        # First get priority entities
        priority_results = []
        for name in self.config.priority_entities:
            r = self._neptune.execute_query(
                "MATCH (n {run_id: $run_id, dataset: $dataset}) "
                "WHERE n.name = $name OR n.canonical_name = $canon "
                "OPTIONAL MATCH (n)-[rel]-() "
                "WITH n, count(rel) AS deg "
                "RETURN n.name AS name, n.canonical_name AS canonical_name, "
                "n.entity_type AS entity_type, n.entity_id AS entity_id, "
                "n.description AS description, deg AS degree "
                "LIMIT 1",
                parameters={
                    "run_id": "murata_live_v1",
                    "dataset": "murata",
                    "name": name,
                    "canon": name.lower(),
                },
            )
            for row in r.get("results", []):
                priority_results.append(row)

        # Then get high-degree entities
        r2 = self._neptune.execute_query(
            "MATCH (n {run_id: $run_id, dataset: $dataset}) "
            "OPTIONAL MATCH (n)-[rel]-() "
            "WITH n, count(rel) AS deg "
            "WHERE deg >= $min_deg "
            "RETURN n.name AS name, n.canonical_name AS canonical_name, "
            "n.entity_type AS entity_type, n.entity_id AS entity_id, "
            "n.description AS description, deg AS degree "
            "ORDER BY deg DESC LIMIT $limit",
            parameters={
                "run_id": "murata_live_v1",
                "dataset": "murata",
                "min_deg": self.config.min_degree,
                "limit": self.config.max_entities,
            },
        )
        high_degree = r2.get("results", [])

        return priority_results + high_degree

    def enrich_entity_i18n(self, entity: dict) -> EntityI18n:
        """Enrich a single entity with multilingual metadata via LLM.

        Args:
            entity: Dict with name, canonical_name, entity_type, description, degree.

        Returns:
            EntityI18n with populated multilingual fields.
        """
        name = entity.get("name", "")
        canonical = entity.get("canonical_name", "") or name.lower()
        etype = entity.get("entity_type", "unknown")
        desc = entity.get("description", "") or ""
        degree = entity.get("degree", 0)
        eid = entity.get("entity_id", "")

        prompt = ENTITY_I18N_PROMPT.format(
            name=name,
            canonical_name=canonical,
            entity_type=etype,
            description=desc,
            degree=degree,
        )

        try:
            response = self._llm.invoke(prompt, max_tokens=2048)
            parsed = self._parse_json_response(response)
        except Exception as e:
            logger.warning(f"LLM enrichment failed for {name}: {e}")
            parsed = {}

        now = datetime.now(timezone.utc).isoformat()

        return EntityI18n(
            entity_id=eid,
            name=name,
            canonical_name=canonical,
            entity_type=etype,
            display_name=parsed.get("display_name", name),
            display_name_zh=parsed.get("display_name_zh", ""),
            display_name_en=parsed.get("display_name_en", name),
            display_name_ja=parsed.get("display_name_ja", ""),
            aliases_zh=parsed.get("aliases_zh", []),
            aliases_en=parsed.get("aliases_en", [name]),
            aliases_ja=parsed.get("aliases_ja", []),
            description_zh=parsed.get("description_zh", ""),
            description_en=parsed.get("description_en", desc),
            description_ja=parsed.get("description_ja", ""),
            label_mode_hint=parsed.get("label_mode_hint", "mixed"),
            model_name=self.config.model_name,
            enriched_at=now,
        )

    def enrich_relation_i18n(
        self, relation_type: str, count: int = 0, examples: str = ""
    ) -> RelationI18n:
        """Enrich a single relation type with multilingual labels."""
        prompt = RELATION_I18N_PROMPT.format(
            relation_type=relation_type,
            count=count,
            examples=examples or "N/A",
        )

        try:
            response = self._llm.invoke(prompt, max_tokens=1024)
            parsed = self._parse_json_response(response)
        except Exception as e:
            logger.warning(f"LLM enrichment failed for relation {relation_type}: {e}")
            parsed = {}

        now = datetime.now(timezone.utc).isoformat()

        return RelationI18n(
            relation_type=relation_type,
            display_label=parsed.get("display_label", relation_type.replace("_", " ").title()),
            label_zh=parsed.get("label_zh", ""),
            label_en=parsed.get("label_en", relation_type.replace("_", " ").lower()),
            label_ja=parsed.get("label_ja", ""),
            description_zh=parsed.get("description_zh", ""),
            description_en=parsed.get("description_en", ""),
            description_ja=parsed.get("description_ja", ""),
            model_name=self.config.model_name,
            enriched_at=now,
        )

    def batch_enrich_entities(
        self, entities: list[dict], *, progress_callback=None
    ) -> list[EntityI18n]:
        """Batch enrich entities with i18n metadata.

        Args:
            entities: List of entity dicts.
            progress_callback: Optional fn(current, total) for progress.

        Returns:
            List of EntityI18n results.
        """
        results: list[EntityI18n] = []
        total = len(entities)

        for i, entity in enumerate(entities):
            result = self.enrich_entity_i18n(entity)
            results.append(result)

            if progress_callback:
                progress_callback(i + 1, total)

            # Rate limiting between batches
            if (i + 1) % self.config.batch_size == 0 and i < total - 1:
                time.sleep(0.5)  # Gentle rate limit

        return results

    def batch_enrich_relations(
        self, relation_types: list[dict]
    ) -> list[RelationI18n]:
        """Batch enrich relation types.

        Uses BUILTIN_RELATION_I18N_MAP for known types (no LLM call),
        falls back to LLM for unknown types.

        Args:
            relation_types: List of dicts with relation_type, count, examples.
        """
        results: list[RelationI18n] = []
        now = datetime.now(timezone.utc).isoformat()

        for rt in relation_types:
            rtype = rt["relation_type"]
            # Check builtin map first — no LLM needed
            if rtype.lower() in BUILTIN_RELATION_I18N_MAP:
                labels = BUILTIN_RELATION_I18N_MAP[rtype.lower()]
                results.append(RelationI18n(
                    relation_type=rtype,
                    display_label=labels["en"].title(),
                    label_zh=labels["zh"],
                    label_en=labels["en"],
                    label_ja=labels["ja"],
                    description_zh=f"表示{labels['zh']}关系",
                    description_en=f"Represents a {labels['en']} relationship",
                    description_ja=f"{labels['ja']}関係を表す",
                    model_name="builtin",
                    enriched_at=now,
                ))
            else:
                # Fall back to LLM
                result = self.enrich_relation_i18n(
                    rtype,
                    count=rt.get("count", 0),
                    examples=rt.get("examples", ""),
                )
                results.append(result)
                time.sleep(0.3)

        return results

    def write_i18n_artifacts(
        self,
        entity_results: list[EntityI18n],
        relation_results: list[RelationI18n],
        output_dir: str | Path,
    ) -> dict[str, Path]:
        """Write enrichment artifacts to disk.

        Returns:
            Dict of artifact_name → file_path.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        paths: dict[str, Path] = {}

        # Entities JSONL
        ent_path = output_dir / "i18n_entities_enriched.jsonl"
        with open(ent_path, "w") as f:
            for r in entity_results:
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
        paths["entities"] = ent_path

        # Relations JSONL
        rel_path = output_dir / "i18n_relations_enriched.jsonl"
        with open(rel_path, "w") as f:
            for r in relation_results:
                f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
        paths["relations"] = rel_path

        # Neptune update preview (parameterized)
        preview_path = output_dir / "i18n_update_neptune_preview.cypher"
        with open(preview_path, "w") as f:
            f.write("// Phase 10B — i18n Neptune Update Preview\n")
            f.write("// Execute ONLY after reviewing i18n_entities_enriched.jsonl\n")
            f.write("// All queries are parameterized — DO NOT inline values\n\n")

            f.write("// === Entity Updates (parameterized) ===\n")
            f.write("// Template: MATCH (n {entity_id: $entity_id, run_id: $run_id, dataset: $dataset})\n")
            f.write("//   SET n += {display_name_zh: $zh, display_name_en: $en, display_name_ja: $ja, ...}\n\n")

            for r in entity_results[:5]:
                f.write(f"// Example: {r.name} ({r.entity_type})\n")
                f.write(f"//   display_name_zh: {r.display_name_zh}\n")
                f.write(f"//   display_name_ja: {r.display_name_ja}\n")
                f.write(f"//   aliases_ja: {r.aliases_ja}\n\n")

            f.write("\n// === Relation Type Updates ===\n")
            f.write("// Template: MATCH ()-[r:TYPE {run_id: $run_id, dataset: $dataset}]->()\n")
            f.write("//   SET r += {label_zh: $zh, label_en: $en, label_ja: $ja}\n\n")

            for r in relation_results[:5]:
                f.write(f"// Example: {r.relation_type}\n")
                f.write(f"//   label_zh: {r.label_zh}\n")
                f.write(f"//   label_ja: {r.label_ja}\n\n")

        paths["preview"] = preview_path

        # Report JSON
        report = {
            "phase": "10B",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": {
                "max_entities": self.config.max_entities,
                "max_relations": self.config.max_relations,
                "min_degree": self.config.min_degree,
                "dry_run": self.config.dry_run,
                "model": self.config.model_name,
            },
            "entities_enriched": len(entity_results),
            "relations_enriched": len(relation_results),
            "entity_types_covered": list(set(r.entity_type for r in entity_results)),
            "relation_types_covered": [r.relation_type for r in relation_results],
            "files": {k: str(v) for k, v in paths.items()},
        }
        report_path = output_dir / "i18n_enrichment_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        paths["report"] = report_path

        return paths

    def optional_update_neptune_i18n_properties(
        self,
        entity_results: list[EntityI18n],
        relation_results: list[RelationI18n],
        *,
        run_id: str = "murata_live_v1",
        dataset: str = "murata",
    ) -> dict[str, int]:
        """Update Neptune with i18n properties. Only runs if dry_run=False.

        Returns:
            Dict with counts: entities_updated, relations_updated, errors.
        """
        if self.config.dry_run:
            logger.info("DRY RUN — skipping Neptune update")
            return {"entities_updated": 0, "relations_updated": 0, "errors": 0, "mode": "dry_run"}

        if not self._neptune:
            raise ValueError("Neptune client required for live update")

        stats = {"entities_updated": 0, "relations_updated": 0, "errors": 0, "mode": "live"}

        # Update entities
        for ent in entity_results:
            try:
                props = {
                    "display_name": ent.display_name,
                    "display_name_zh": ent.display_name_zh,
                    "display_name_en": ent.display_name_en,
                    "display_name_ja": ent.display_name_ja,
                    "aliases_zh": json.dumps(ent.aliases_zh, ensure_ascii=False),
                    "aliases_en": json.dumps(ent.aliases_en, ensure_ascii=False),
                    "aliases_ja": json.dumps(ent.aliases_ja, ensure_ascii=False),
                    "description_zh": ent.description_zh,
                    "description_en": ent.description_en,
                    "description_ja": ent.description_ja,
                    "label_mode_hint": ent.label_mode_hint,
                    "i18n_enriched_at": ent.enriched_at,
                    "i18n_model": ent.model_name,
                }

                self._neptune.execute_query(
                    "MATCH (n {entity_id: $eid, run_id: $run_id, dataset: $dataset}) "
                    "SET n += $props",
                    parameters={
                        "eid": ent.entity_id,
                        "run_id": run_id,
                        "dataset": dataset,
                        "props": props,
                    },
                )
                stats["entities_updated"] += 1
            except Exception as e:
                logger.error(f"Failed to update entity {ent.name}: {e}")
                stats["errors"] += 1

        # Update relations (by type, not individual edges)
        for rel in relation_results:
            try:
                props = {
                    "display_label": rel.display_label,
                    "label_zh": rel.label_zh,
                    "label_en": rel.label_en,
                    "label_ja": rel.label_ja,
                    "description_zh": rel.description_zh,
                    "description_en": rel.description_en,
                    "description_ja": rel.description_ja,
                    "i18n_enriched_at": rel.enriched_at,
                }

                # Update all edges of this type
                self._neptune.execute_query(
                    f"MATCH ()-[r:{rel.relation_type} {{run_id: $run_id, dataset: $dataset}}]->() "
                    "SET r += $props",
                    parameters={
                        "run_id": run_id,
                        "dataset": dataset,
                        "props": props,
                    },
                )
                stats["relations_updated"] += 1
            except Exception as e:
                logger.error(f"Failed to update relation {rel.relation_type}: {e}")
                stats["errors"] += 1

        return stats

    @staticmethod
    def _parse_json_response(response: str) -> dict:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = response.strip()

        # Strip markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (```json and ```)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        # Find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]

        return json.loads(text)


# ─── Live Enrichment ──────────────────────────────────────────────────────────


LIVE_ENTITY_I18N_PROMPT = """You are a multilingual enterprise system analyst. Given entity metadata from a knowledge graph, generate multilingual display names, aliases, and descriptions.

ENTITY:
- name: {name}
- canonical_name: {canonical_name}
- entity_type: {entity_type}
- description: {description}
- context: This entity is from the Murata enterprise application system (ERP/accounting/payment processing). It has {degree} connections in the knowledge graph.

RULES:
1. Do NOT change entity_id or canonical_name.
2. Technical names (table names, class names, file names) must be preserved in technical_aliases.
3. Generate business-friendly names in Chinese (zh), English (en), and Japanese (ja).
4. aliases should include common variants: abbreviations, full forms, alternate scripts.
5. For table names like JOURNAL_BASE: provide the business meaning (e.g., "仕訳基礎テーブル" in Japanese).
6. For system names like muratapr: provide the full form (e.g., "Murata PRシステム").
7. If uncertain about business meaning, keep the technical name. Do NOT invent meanings.
8. label_mode_hint: "technical" for code/DB entities, "business" for process/screen entities, "mixed" for both.
9. enrichment_confidence: 0.0-1.0 reflecting your confidence in the business meaning.

OUTPUT (strict JSON, no markdown):
{{
  "display_name": "<primary display name, prefer English technical + CJK business>",
  "display_name_zh": "<Chinese display name>",
  "display_name_en": "<English display name>",
  "display_name_ja": "<Japanese display name>",
  "aliases_zh": ["<Chinese alias 1>", ...],
  "aliases_en": ["<English alias 1>", ...],
  "aliases_ja": ["<Japanese alias 1>", ...],
  "description_zh": "<1-2 sentence Chinese description>",
  "description_en": "<1-2 sentence English description>",
  "description_ja": "<1-2 sentence Japanese description>",
  "label_mode_hint": "technical|business|mixed",
  "enrichment_confidence": 0.0,
  "technical_aliases": ["<original technical name variants>"],
  "business_aliases_zh": ["<Chinese business name variants>"],
  "business_aliases_en": ["<English business name variants>"],
  "business_aliases_ja": ["<Japanese business name variants>"]
}}"""


class BedrockLLMAdapter:
    """Adapts BedrockRuntimeClient to LLMClient protocol for i18n enrichment."""

    def __init__(self, bedrock_client, model_id: str = "apac.anthropic.claude-sonnet-4-20250514-v1:0"):
        self._client = bedrock_client
        self._model_id = model_id

    def invoke(self, prompt: str, *, max_tokens: int = 4096) -> str:
        response = self._client.converse(
            model_id=self._model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inference_config={"maxTokens": max_tokens, "temperature": 0.1},
        )
        output = response.get("output", {})
        message = output.get("message", {})
        content = message.get("content", [])
        for block in content:
            if "text" in block:
                return block["text"]
        return ""


@dataclass
class LiveEnrichmentConfig(EnrichmentConfig):
    """Extended configuration for live LLM enrichment."""

    rate_limit_per_minute: int = 20
    max_retries: int = 3
    checkpoint_every: int = 10
    save_raw_outputs: bool = False
    save_failures: bool = True
    output_suffix: str = "live"


class LiveI18nEnricher(I18nEnricher):
    """Live LLM enricher with resume, retry, rate limiting, and checkpointing.

    Extends I18nEnricher with:
    - Resume from checkpoint
    - Skip-existing support
    - Configurable rate limiting
    - Exponential backoff retry
    - Per-entity error isolation
    - Raw LLM output logging
    - Failure logging
    - Checkpoint saving every N entities
    """

    def __init__(
        self,
        llm_client: LLMClient,
        neptune_client=None,
        config: Optional[LiveEnrichmentConfig] = None,
        checkpoint_path: Optional[Path] = None,
        raw_output_path: Optional[Path] = None,
        failure_path: Optional[Path] = None,
    ):
        live_config = config or LiveEnrichmentConfig()
        super().__init__(llm_client, neptune_client, live_config)
        self._live_config = live_config
        self._checkpoint_path = checkpoint_path
        self._raw_output_path = raw_output_path
        self._failure_path = failure_path
        self._processed_ids: set[str] = set()
        self._request_times: list[float] = []

        if checkpoint_path and checkpoint_path.exists():
            self._load_checkpoint(checkpoint_path)

    def _load_checkpoint(self, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._processed_ids = set(data.get("processed_ids", []))
            logger.info("Loaded checkpoint: %d processed ids from %s", len(self._processed_ids), path)
        except Exception as e:
            logger.warning("Failed to load checkpoint %s: %s", path, e)

    def _save_checkpoint(self, path: Path) -> None:
        try:
            path.write_text(
                json.dumps({"processed_ids": sorted(self._processed_ids)}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Failed to save checkpoint to %s: %s", path, e)

    def _enforce_rate_limit(self) -> None:
        """Block until rate limit allows next request."""
        now = time.monotonic()
        window = 60.0
        rate = self._live_config.rate_limit_per_minute
        # Remove timestamps outside the window
        self._request_times = [t for t in self._request_times if now - t < window]
        if len(self._request_times) >= rate:
            sleep_until = self._request_times[0] + window
            wait = sleep_until - now
            if wait > 0:
                logger.debug("Rate limit: sleeping %.1fs", wait)
                time.sleep(wait)
            now = time.monotonic()
            self._request_times = [t for t in self._request_times if now - t < window]
        self._request_times.append(time.monotonic())

    def _invoke_with_retry(self, prompt: str, max_tokens: int = 2048) -> tuple[str, bool]:
        """Invoke LLM with exponential backoff retry. Returns (response, success)."""
        max_retries = self._live_config.max_retries
        for attempt in range(max_retries + 1):
            try:
                self._enforce_rate_limit()
                response = self._llm.invoke(prompt, max_tokens=max_tokens)
                return response, True
            except Exception as e:
                if attempt == max_retries:
                    logger.error("All %d retries exhausted: %s", max_retries, e)
                    return str(e), False
                wait = 2 ** attempt
                logger.warning("LLM call failed (attempt %d/%d): %s — retrying in %ds",
                               attempt + 1, max_retries, e, wait)
                time.sleep(wait)
        return "", False

    def _log_raw_output(self, entity_id: str, prompt: str, response: str) -> None:
        if not self._raw_output_path:
            return
        record = {
            "entity_id": entity_id,
            "prompt": prompt,
            "response": response,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self._raw_output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to log raw output: %s", e)

    def _log_failure(self, entity: dict, error: str) -> None:
        if not self._failure_path:
            return
        record = {
            "entity_id": entity.get("entity_id", ""),
            "name": entity.get("name", ""),
            "error": error,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self._failure_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed to log failure: %s", e)

    def _builtin_entity_i18n(self, entity: dict) -> Optional[EntityI18n]:
        """Return builtin enrichment for priority entities, or None."""
        canonical = (entity.get("canonical_name") or entity.get("name", "")).lower()
        name_lower = entity.get("name", "").lower()
        for key in (canonical, name_lower):
            data = _PRIORITY_ENTITY_I18N.get(key)
            if data:
                now = datetime.now(timezone.utc).isoformat()
                name = entity.get("name", "")
                return EntityI18n(
                    entity_id=entity.get("entity_id", ""),
                    name=name,
                    canonical_name=canonical,
                    entity_type=entity.get("entity_type", "unknown"),
                    display_name=data.get("display_name", name),
                    display_name_zh=data.get("display_name_zh", ""),
                    display_name_en=data.get("display_name_en", name),
                    display_name_ja=data.get("display_name_ja", ""),
                    aliases_zh=data.get("aliases_zh", []),
                    aliases_en=data.get("aliases_en", []),
                    aliases_ja=data.get("aliases_ja", []),
                    description_zh=data.get("description_zh", ""),
                    description_en=data.get("description_en", ""),
                    description_ja=data.get("description_ja", ""),
                    label_mode_hint=data.get("label_mode_hint", "mixed"),
                    model_name="builtin",
                    enriched_at=now,
                    enrichment_source="builtin",
                    enrichment_confidence=1.0,
                    enrichment_model="builtin",
                    enrichment_error="",
                    updated_at=now,
                    technical_aliases=[name],
                    business_aliases_zh=data.get("aliases_zh", []),
                    business_aliases_en=data.get("aliases_en", []),
                    business_aliases_ja=data.get("aliases_ja", []),
                )
        return None

    def enrich_entity_live(self, entity: dict) -> EntityI18n:
        """Enrich a single entity via live LLM, with retry and fallback.

        Priority entities use builtin data (no LLM call).
        Falls back to canonical_name on JSON parse failure.
        """
        name = entity.get("name", "")
        canonical = entity.get("canonical_name", "") or name.lower()
        etype = entity.get("entity_type", "unknown")
        desc = entity.get("description", "") or ""
        degree = entity.get("degree", 0)
        eid = entity.get("entity_id", "")
        now = datetime.now(timezone.utc).isoformat()

        # Priority entities use builtin data
        builtin = self._builtin_entity_i18n(entity)
        if builtin is not None:
            return builtin

        prompt = LIVE_ENTITY_I18N_PROMPT.format(
            name=name,
            canonical_name=canonical,
            entity_type=etype,
            description=desc,
            degree=degree,
        )

        raw_response, success = self._invoke_with_retry(prompt)

        if self._live_config.save_raw_outputs:
            self._log_raw_output(eid, prompt, raw_response)

        if not success:
            self._log_failure(entity, raw_response)
            return EntityI18n(
                entity_id=eid,
                name=name,
                canonical_name=canonical,
                entity_type=etype,
                display_name=name,
                display_name_en=name,
                aliases_en=[name],
                model_name=self._live_config.model_name,
                enriched_at=now,
                enrichment_source="fallback",
                enrichment_confidence=0.0,
                enrichment_model=self._live_config.model_name,
                enrichment_error=raw_response,
                updated_at=now,
                technical_aliases=[name],
            )

        # Parse JSON — fallback to canonical_name on failure
        try:
            parsed = self._parse_json_response(raw_response)
            parse_error = ""
            enrichment_source = "live_llm"
        except Exception as e:
            logger.warning("JSON parse failed for %s: %s — using fallback", name, e)
            self._log_failure(entity, f"JSON parse error: {e}")
            parsed = {}
            parse_error = str(e)
            enrichment_source = "fallback"

        confidence = float(parsed.get("enrichment_confidence", 0.5))

        return EntityI18n(
            entity_id=eid,
            name=name,
            canonical_name=canonical,
            entity_type=etype,
            display_name=parsed.get("display_name", name),
            display_name_zh=parsed.get("display_name_zh", ""),
            display_name_en=parsed.get("display_name_en", name),
            display_name_ja=parsed.get("display_name_ja", ""),
            aliases_zh=parsed.get("aliases_zh", []),
            aliases_en=parsed.get("aliases_en", [name]),
            aliases_ja=parsed.get("aliases_ja", []),
            description_zh=parsed.get("description_zh", ""),
            description_en=parsed.get("description_en", desc),
            description_ja=parsed.get("description_ja", ""),
            label_mode_hint=parsed.get("label_mode_hint", "mixed"),
            model_name=self._live_config.model_name,
            enriched_at=now,
            enrichment_source=enrichment_source,
            enrichment_confidence=confidence,
            enrichment_model=self._live_config.model_name,
            enrichment_error=parse_error,
            updated_at=now,
            technical_aliases=parsed.get("technical_aliases", [canonical]),
            business_aliases_zh=parsed.get("business_aliases_zh", []),
            business_aliases_en=parsed.get("business_aliases_en", []),
            business_aliases_ja=parsed.get("business_aliases_ja", []),
        )

    def batch_enrich_live(
        self,
        entities: list[dict],
        *,
        existing_ids: Optional[set[str]] = None,
        progress_callback=None,
        multi_entity_batch_size: int = 5,
    ) -> list[EntityI18n]:
        """Batch enrich with resume, skip-existing, rate limiting, checkpointing.

        Supports multi-entity prompting: multiple entities per LLM call to reduce
        total API calls (e.g., 5 entities/call reduces 3034 to ~607 calls).

        Args:
            entities: All candidate entities.
            existing_ids: Entity IDs already in output file (skip-existing).
            progress_callback: Optional fn(current, total).
            multi_entity_batch_size: Entities per LLM call (default: 5).

        Returns:
            List of EntityI18n for all processed (new) entities.
        """
        skip_ids = set(self._processed_ids)
        if existing_ids:
            skip_ids |= existing_ids

        to_process = [e for e in entities if e.get("entity_id", "") not in skip_ids]
        total = len(to_process)
        results: list[EntityI18n] = []

        logger.info("Live batch enrich: %d entities to process (%d skipped), batch_size=%d",
                    total, len(entities) - total, multi_entity_batch_size)

        # Process in multi-entity batches
        i = 0
        while i < total:
            batch = to_process[i:i + multi_entity_batch_size]

            # Separate builtin vs LLM entities
            builtin_results = []
            llm_entities = []
            for entity in batch:
                builtin = self._builtin_entity_i18n(entity)
                if builtin:
                    builtin_results.append(builtin)
                    self._processed_ids.add(entity.get("entity_id", ""))
                else:
                    llm_entities.append(entity)

            results.extend(builtin_results)

            # Process LLM entities in one call if possible
            if llm_entities:
                if len(llm_entities) == 1:
                    # Single entity — use standard method
                    entity = llm_entities[0]
                    eid = entity.get("entity_id", "")
                    try:
                        result = self.enrich_entity_live(entity)
                    except Exception as e:
                        logger.error("Unexpected error enriching %s: %s", eid, e)
                        self._log_failure(entity, str(e))
                        result = self._make_fallback_entity(entity, str(e))
                    results.append(result)
                    self._processed_ids.add(eid)
                else:
                    # Multi-entity batch prompt
                    batch_results = self._enrich_multi_entity_batch(llm_entities)
                    results.extend(batch_results)
                    for entity in llm_entities:
                        self._processed_ids.add(entity.get("entity_id", ""))

            i += multi_entity_batch_size

            if progress_callback:
                progress_callback(min(i, total), total)

            # Checkpoint every N entities
            if self._checkpoint_path and i % self._live_config.checkpoint_every == 0:
                self._save_checkpoint(self._checkpoint_path)
                logger.debug("Checkpoint saved at entity %d/%d", min(i, total), total)

        # Final checkpoint save
        if self._checkpoint_path:
            self._save_checkpoint(self._checkpoint_path)

        return results

    def _enrich_multi_entity_batch(self, entities: list[dict]) -> list[EntityI18n]:
        """Enrich multiple entities in a single LLM call.

        Falls back to individual processing if batch parsing fails.
        """
        prompt = self._build_multi_entity_prompt(entities)
        response, success = self._invoke_with_retry(prompt, max_tokens=8192)

        if success:
            self._log_raw_output(
                f"batch_{entities[0].get('entity_id', '')}",
                prompt[:200] + "...",
                response,
            )
            try:
                parsed_list = self._parse_multi_entity_response(response, entities)
                return parsed_list
            except Exception as e:
                logger.warning("Multi-entity parse failed, falling back to individual: %s", e)

        # Fallback: process individually
        results = []
        for entity in entities:
            eid = entity.get("entity_id", "")
            try:
                result = self.enrich_entity_live(entity)
            except Exception as e:
                logger.error("Individual fallback failed for %s: %s", eid, e)
                self._log_failure(entity, str(e))
                result = self._make_fallback_entity(entity, str(e))
            results.append(result)
        return results

    def _build_multi_entity_prompt(self, entities: list[dict]) -> str:
        """Build a prompt for enriching multiple entities at once."""
        entity_specs = []
        for idx, entity in enumerate(entities, 1):
            name = entity.get("name", "")
            canonical = entity.get("canonical_name", "") or name.lower()
            etype = entity.get("entity_type", "unknown")
            desc = entity.get("description", "") or ""
            entity_specs.append(
                f"ENTITY {idx}:\n"
                f"  - name: {name}\n"
                f"  - canonical_name: {canonical}\n"
                f"  - entity_type: {etype}\n"
                f"  - description: {desc}"
            )

        entities_text = "\n\n".join(entity_specs)
        return f"""You are a multilingual enterprise system analyst. Given multiple entities from the Murata enterprise application system (ERP/accounting/payment processing) knowledge graph, generate multilingual display names, aliases, and descriptions for EACH entity.

{entities_text}

RULES:
1. Do NOT change entity_id or canonical_name.
2. Technical names (table names, class names, file names) must be preserved as-is in technical_aliases.
3. Generate business-friendly names in Chinese (zh), English (en), and Japanese (ja).
4. aliases should include common variants: abbreviations, full forms, alternate scripts.
5. For table names like JOURNAL_BASE: provide the business meaning (e.g., "仕訳基礎テーブル" in Japanese).
6. For system names like muratapr: provide the full form (e.g., "Murata PRシステム").
7. If uncertain about business meaning, keep the technical name. Do NOT invent meanings.
8. label_mode_hint: "technical" for code/DB entities, "business" for process/screen entities, "mixed" for both.
9. enrichment_confidence: 0.0-1.0 (how confident are you in the business meaning?)

OUTPUT (strict JSON array, no markdown, no extra text):
[
  {{
    "entity_index": 1,
    "display_name": "<primary display name>",
    "display_name_zh": "<Chinese display name>",
    "display_name_en": "<English display name>",
    "display_name_ja": "<Japanese display name>",
    "aliases_zh": ["<Chinese alias 1>", ...],
    "aliases_en": ["<English alias 1>", ...],
    "aliases_ja": ["<Japanese alias 1>", ...],
    "technical_aliases": ["<technical name variants>"],
    "business_aliases_zh": ["<Chinese business aliases>"],
    "business_aliases_en": ["<English business aliases>"],
    "business_aliases_ja": ["<Japanese business aliases>"],
    "description_zh": "<1-2 sentence Chinese description>",
    "description_en": "<1-2 sentence English description>",
    "description_ja": "<1-2 sentence Japanese description>",
    "label_mode_hint": "technical|business|mixed",
    "enrichment_confidence": 0.0-1.0
  }},
  ...
]

Return exactly {len(entities)} objects in the array, one per entity IN ORDER."""

    def _parse_multi_entity_response(
        self, response: str, entities: list[dict]
    ) -> list[EntityI18n]:
        """Parse a multi-entity LLM response into EntityI18n objects."""
        text = response.strip()
        # Strip markdown code blocks
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [ln for ln in lines if not ln.strip().startswith("```")]
            text = "\n".join(lines)

        # Find JSON array
        start = text.find("[")
        end = text.rfind("]") + 1
        if start < 0 or end <= start:
            raise ValueError("No JSON array found in response")

        parsed_list = json.loads(text[start:end])
        if not isinstance(parsed_list, list):
            raise ValueError("Response is not a JSON array")

        now = datetime.now(timezone.utc).isoformat()
        results = []

        for idx, entity in enumerate(entities):
            eid = entity.get("entity_id", "")
            name = entity.get("name", "")
            canonical = entity.get("canonical_name", "") or name.lower()
            etype = entity.get("entity_type", "unknown")

            # Find matching parsed result
            if idx < len(parsed_list):
                parsed = parsed_list[idx]
            else:
                parsed = {}

            results.append(EntityI18n(
                entity_id=eid,
                name=name,
                canonical_name=canonical,
                entity_type=etype,
                display_name=parsed.get("display_name", name),
                display_name_zh=parsed.get("display_name_zh", ""),
                display_name_en=parsed.get("display_name_en", name),
                display_name_ja=parsed.get("display_name_ja", ""),
                aliases_zh=parsed.get("aliases_zh", []),
                aliases_en=parsed.get("aliases_en", [name]),
                aliases_ja=parsed.get("aliases_ja", []),
                description_zh=parsed.get("description_zh", ""),
                description_en=parsed.get("description_en", ""),
                description_ja=parsed.get("description_ja", ""),
                label_mode_hint=parsed.get("label_mode_hint", "mixed"),
                model_name=self._live_config.model_name,
                enriched_at=now,
                enrichment_source="live_llm",
                enrichment_confidence=parsed.get("enrichment_confidence", 0.7),
                enrichment_model=self._live_config.model_name,
                enrichment_error="",
                updated_at=now,
                technical_aliases=parsed.get("technical_aliases", [canonical]),
                business_aliases_zh=parsed.get("business_aliases_zh", []),
                business_aliases_en=parsed.get("business_aliases_en", []),
                business_aliases_ja=parsed.get("business_aliases_ja", []),
            ))

        return results

    def _make_fallback_entity(self, entity: dict, error: str) -> EntityI18n:
        """Create a fallback EntityI18n when enrichment fails."""
        now = datetime.now(timezone.utc).isoformat()
        name = entity.get("name", "")
        canonical = entity.get("canonical_name", name.lower())
        return EntityI18n(
            entity_id=entity.get("entity_id", ""),
            name=name,
            canonical_name=canonical,
            entity_type=entity.get("entity_type", "unknown"),
            display_name=name,
            display_name_en=name,
            model_name=self._live_config.model_name,
            enriched_at=now,
            enrichment_source="fallback",
            enrichment_confidence=0.0,
            enrichment_model=self._live_config.model_name,
            enrichment_error=error,
            updated_at=now,
        )


# ===========================================================================
# run_enrichment() — Dispatcher for optional enrichment stage
# ===========================================================================


def run_enrichment(
    mode: str,
    entities: list[dict],
    relations: list[dict],
    max_entities: int = 200,
    output_dir: "Path | str | None" = None,
    output_suffix: str = "",
    update_neptune: bool = False,
) -> dict | None:
    """Dispatch enrichment by mode. Called from pipeline stage_enrichment().

    Args:
        mode: One of 'none', 'rule', 'mock', 'llm'.
        entities: List of entity dicts from entities.jsonl.
        relations: List of relation dicts from relations_clean.jsonl.
        max_entities: Max entities to process.
        output_dir: Directory for output artifacts.
        output_suffix: Suffix for output filenames.
        update_neptune: Whether to write back to Neptune (requires explicit confirm).

    Returns:
        Dict with enrichment results, or None if mode=none.
    """
    import json as _json
    from pathlib import Path as _Path

    if mode == "none":
        return None

    if output_dir is not None:
        output_dir = _Path(output_dir)

    # Select entities (limited by max_entities)
    selected = entities[:max_entities]

    if mode == "rule":
        # Rule-based: use builtin priority i18n data + basic alias generation
        enriched_entities = []
        for ent in selected:
            entity_id = ent.get("entity_id", "")
            canonical_name = ent.get("canonical_name", entity_id)
            name = ent.get("name", canonical_name)

            # Check priority builtin
            i18n_data = None
            for key, data in _PRIORITY_ENTITY_I18N.items():
                if key.lower() == entity_id.lower() or key.lower() == canonical_name.lower():
                    i18n_data = data
                    break

            if i18n_data:
                enriched_entities.append({
                    "entity_id": entity_id,
                    "entity_type": ent.get("entity_type", "unknown"),
                    "canonical_name": canonical_name,
                    "name": name,
                    "display_name": i18n_data.get("display_name", name),
                    "display_name_zh": i18n_data.get("display_name_zh", ""),
                    "display_name_en": i18n_data.get("display_name_en", ""),
                    "display_name_ja": i18n_data.get("display_name_ja", ""),
                    "aliases_zh": i18n_data.get("aliases_zh", []),
                    "aliases_en": i18n_data.get("aliases_en", []),
                    "aliases_ja": i18n_data.get("aliases_ja", []),
                    "label_mode_hint": i18n_data.get("label_mode_hint", "technical"),
                    "enrichment_source": "rule_builtin",
                    "enrichment_confidence": 1.0,
                })
            else:
                # Basic rule: keep canonical_name, generate EN alias
                aliases_en = [canonical_name]
                if "_" in canonical_name:
                    aliases_en.append(canonical_name.replace("_", " ").lower())
                enriched_entities.append({
                    "entity_id": entity_id,
                    "entity_type": ent.get("entity_type", "unknown"),
                    "canonical_name": canonical_name,
                    "name": name,
                    "display_name": name,
                    "display_name_zh": "",
                    "display_name_en": canonical_name,
                    "display_name_ja": "",
                    "aliases_zh": [],
                    "aliases_en": aliases_en,
                    "aliases_ja": [],
                    "label_mode_hint": "technical",
                    "enrichment_source": "rule_basic",
                    "enrichment_confidence": 0.3,
                })

        # Relations: use builtin map
        enriched_relations = []
        for rel in relations:
            rtype = rel.get("relation_type", "related_to")
            labels = BUILTIN_RELATION_I18N_MAP.get(rtype.lower(), {})
            enriched_relations.append({
                "relation_id": rel.get("relation_id", ""),
                "relation_type": rtype,
                "display_label": labels.get("en", rtype),
                "label_zh": labels.get("zh", ""),
                "label_en": labels.get("en", rtype),
                "label_ja": labels.get("ja", ""),
            })

    elif mode == "mock":
        # Mock: use MockDeterministicLLM
        config = EnrichmentConfig(max_entities=max_entities)
        mock_llm = MockDeterministicLLM()
        enricher = I18nEnricher(config=config, llm_client=mock_llm)
        entity_results = enricher.batch_enrich_entities(selected)
        enriched_entities = [e.to_dict() for e in entity_results]

        # Relations: deterministic
        rel_results = enricher.batch_enrich_relations(relations)
        enriched_relations = [r.to_dict() for r in rel_results]

    elif mode == "llm":
        # LLM mode should NOT be triggered from the pipeline dispatcher
        # without explicit setup. Return empty result with warning.
        return {
            "entities_enriched": 0,
            "relations_enriched": 0,
            "output_files": [],
            "warning": "LLM mode requires running scripts/enrich_i18n.py directly with --mode llm",
        }
    else:
        return None

    # Write output artifacts if output_dir specified
    output_files = []
    if output_dir and output_dir.exists():
        suffix = f"_{output_suffix}" if output_suffix else ""
        ent_path = output_dir / f"i18n_entities_enriched{suffix}.jsonl"
        rel_path = output_dir / f"i18n_relations_enriched{suffix}.jsonl"

        with open(ent_path, "w") as f:
            for e in enriched_entities:
                f.write(_json.dumps(e, ensure_ascii=False) + "\n")
        output_files.append(str(ent_path))

        with open(rel_path, "w") as f:
            for r in enriched_relations:
                f.write(_json.dumps(r, ensure_ascii=False) + "\n")
        output_files.append(str(rel_path))

    return {
        "entities_enriched": len(enriched_entities),
        "relations_enriched": len(enriched_relations),
        "output_files": output_files,
        "mode": mode,
        "update_neptune": update_neptune,
    }
