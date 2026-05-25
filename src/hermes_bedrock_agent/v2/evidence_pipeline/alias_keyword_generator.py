"""
エイリアス・キーワードジェネレーター — EvidenceRecord にキーワード・別名・エンティティ言及を付加するモジュール。

日本語/英語/中国語の既知エンタープライズ用語マッピングと
テキスト中のシステム名・ドメイン用語を組み合わせてリッチ化する。

出力フィールド (EvidenceRecord):
  keywords        … 検索に使えるトークンリスト
  aliases         … 正規化された別名リスト
  entity_mentions … 固有エンティティ (システム名・フィールド名など)
"""
from __future__ import annotations

import logging
import re
from typing import Any

from hermes_bedrock_agent.v2.evidence_pipeline.evidence_schema import EvidenceRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known alias mappings
# Each entry: canonical term → list of aliases (all variants, cross-lingual)
# ---------------------------------------------------------------------------

_ALIAS_TABLE: dict[str, list[str]] = {
    # 発注 / purchase order
    "発注": ["purchase order", "PO", "订单", "発注"],
    "purchase order": ["発注", "PO", "订单", "purchase order"],
    "PO": ["発注", "purchase order", "订单", "PO"],
    "订单": ["発注", "purchase order", "PO", "订单"],

    # 納品 / delivery
    "納品": ["delivery", "交货", "DN", "納品"],
    "delivery": ["納品", "交货", "DN", "delivery"],
    "DN": ["納品", "delivery", "交货", "DN"],
    "交货": ["納品", "delivery", "DN", "交货"],

    # 中間F / intermediate file
    "中間F": ["intermediate file", "中间文件", "IF", "中間F"],
    "intermediate file": ["中間F", "中间文件", "IF", "intermediate file"],
    "IF": ["中間F", "intermediate file", "中间文件", "IF"],
    "中间文件": ["中間F", "intermediate file", "IF", "中间文件"],

    # SAP
    "SAP": ["SAP ERP", "SAP"],
    "SAP ERP": ["SAP", "SAP ERP"],

    # ANDPAD
    "ANDPAD": ["Andpad", "ANDPAD"],
    "Andpad": ["ANDPAD", "Andpad"],

    # DataSpider
    "DataSpider": ["DataSpider Servista", "DS", "DataSpider"],
    "DataSpider Servista": ["DataSpider", "DS", "DataSpider Servista"],
    "DS": ["DataSpider", "DataSpider Servista", "DS"],

    # 項目 / field / column
    "項目": ["field", "column", "字段", "フィールド", "項目"],
    "field": ["項目", "column", "字段", "フィールド", "field"],
    "column": ["項目", "field", "字段", "フィールド", "column"],
    "字段": ["項目", "field", "column", "フィールド", "字段"],
    "フィールド": ["項目", "field", "column", "字段", "フィールド"],

    # テーブル / table
    "テーブル": ["table", "表", "テーブル"],
    "table": ["テーブル", "表", "table"],
    "表": ["テーブル", "table", "表"],

    # メッセージ / message
    "メッセージ": ["message", "MSG", "消息", "メッセージ"],
    "message": ["メッセージ", "MSG", "消息", "message"],
    "MSG": ["メッセージ", "message", "消息", "MSG"],
    "消息": ["メッセージ", "message", "MSG", "消息"],
}

# Lookup: any token → canonical key → full alias list
_ALIAS_INDEX: dict[str, str] = {}
for _canon, _variants in _ALIAS_TABLE.items():
    _ALIAS_INDEX[_canon.lower()] = _canon
    for _v in _variants:
        _ALIAS_INDEX[_v.lower()] = _canon


# ---------------------------------------------------------------------------
# System-name detection pattern
# ---------------------------------------------------------------------------

_SYSTEM_NAMES = [
    "SAP", "ANDPAD", "DataSpider", "中間F", "Oracle", "Salesforce",
    "MySQL", "PostgreSQL", "Andpad",
]
_SYSTEM_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _SYSTEM_NAMES) + r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Data-type keywords
# ---------------------------------------------------------------------------

_DTYPE_PATTERN = re.compile(
    r"\b(VARCHAR|CHAR|INT|INTEGER|NUMBER|DATE|DATETIME|TIMESTAMP|BOOLEAN|FLOAT|DECIMAL|TEXT|BLOB)\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Business domain keywords
# ---------------------------------------------------------------------------

_DOMAIN_PATTERN = re.compile(
    r"(マッピング|フィールド|テーブル|メッセージ|項目|条件|ルール|発注|納品|中間F|"
    r"mapping|field|table|message|condition|rule|purchase.?order|delivery|"
    r"PO\b|DN\b|IF\b|MSG\b)",
    re.IGNORECASE,
)


class AliasKeywordGenerator:
    """EvidenceRecord のキーワード・別名・エンティティを生成・付加するクラス。

    generate()       — テキスト + フィールド名 + システム名から dict を生成
    enrich_record()  — EvidenceRecord 1件をリッチ化して返す
    enrich_batch()   — EvidenceRecord リストを一括リッチ化
    """

    def generate(
        self,
        text: str,
        field_names: list[str] | None = None,
        system_names: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """テキストとオプションのフィールド名・システム名からキーワード等を生成する。

        Returns
        -------
        dict with keys:
            keywords       — 正規化トークンのリスト (重複なし)
            aliases        — エイリアス展開されたバリアントのリスト
            entity_mentions — 固有エンティティのリスト
        """
        keywords: list[str] = []
        aliases: list[str] = []
        entity_mentions: list[str] = []

        # --- 1. システム名の検出 ---
        detected_systems = _detect_systems(text)
        if system_names:
            detected_systems = list(dict.fromkeys(detected_systems + system_names))
        entity_mentions.extend(detected_systems)

        # --- 2. データ型キーワード ---
        dtypes = list(dict.fromkeys(m.upper() for m in _DTYPE_PATTERN.findall(text)))
        keywords.extend(dtypes)

        # --- 3. ドメインキーワード ---
        domain_hits = list(dict.fromkeys(_DOMAIN_PATTERN.findall(text)))
        keywords.extend(domain_hits)

        # --- 4. フィールド名からのエイリアス展開 ---
        if field_names:
            entity_mentions.extend(field_names)
            for fname in field_names:
                exp = _expand_aliases(fname)
                aliases.extend(exp)

        # --- 5. テキストトークンからのエイリアス展開 ---
        tokens = re.split(r"[\s,、。・/\\|()（）「」【】]+", text)
        for tok in tokens:
            tok_clean = tok.strip()
            if len(tok_clean) < 2:
                continue
            keywords.append(tok_clean)
            exp = _expand_aliases(tok_clean)
            if exp:
                aliases.extend(exp)

        # --- 6. 重複排除 ---
        keywords = list(dict.fromkeys(k for k in keywords if k))
        aliases = list(dict.fromkeys(a for a in aliases if a))
        entity_mentions = list(dict.fromkeys(e for e in entity_mentions if e))

        return {
            "keywords": keywords,
            "aliases": aliases,
            "entity_mentions": entity_mentions,
        }

    def enrich_record(self, record: EvidenceRecord) -> EvidenceRecord:
        """EvidenceRecord 1件にキーワード・別名・エンティティを付加する。

        既存の keywords / aliases / entity_mentions はマージされる。
        """
        source_text = " ".join(filter(None, [
            record.text_for_embedding,
            record.text_for_llm,
            record.text,
        ]))
        field_names = record.column_names or []
        system_names = record.entity_mentions or []

        result = self.generate(
            text=source_text,
            field_names=field_names,
            system_names=system_names,
        )

        # Merge — preserve existing values, extend with new ones
        existing_kw = list(record.keywords or [])
        existing_al = list(record.aliases or [])
        existing_em = list(record.entity_mentions or [])

        record.keywords = list(dict.fromkeys(
            existing_kw + result["keywords"]
        ))
        record.aliases = list(dict.fromkeys(
            existing_al + result["aliases"]
        ))
        record.entity_mentions = list(dict.fromkeys(
            existing_em + result["entity_mentions"]
        ))
        return record

    def enrich_batch(self, records: list[EvidenceRecord]) -> list[EvidenceRecord]:
        """EvidenceRecord リストを一括リッチ化して返す。"""
        enriched: list[EvidenceRecord] = []
        for rec in records:
            try:
                enriched.append(self.enrich_record(rec))
            except Exception:
                logger.exception(
                    "AliasKeywordGenerator: error enriching record %s", rec.record_id
                )
                enriched.append(rec)

        logger.info(
            "AliasKeywordGenerator: enriched %d records",
            len(enriched),
        )
        return enriched


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _detect_systems(text: str) -> list[str]:
    return list(dict.fromkeys(m for m in _SYSTEM_PATTERN.findall(text)))


def _expand_aliases(token: str) -> list[str]:
    """トークンがエイリアステーブルにあれば全バリアントを返す。なければ空リスト。"""
    canon = _ALIAS_INDEX.get(token.lower())
    if canon is None:
        return []
    return _ALIAS_TABLE.get(canon, [])
