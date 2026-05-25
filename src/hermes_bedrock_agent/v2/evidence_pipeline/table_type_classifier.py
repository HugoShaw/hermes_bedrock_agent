"""
Table type classifier — テーブル領域の種別を分類するモジュール。

テーブル領域のシート名・タイトル・ヘッダー・データサンプルから
テーブル種別を推定し、レポートを出力する。

出力: reports/table_type_classification_report.md
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# テーブル種別定義
TABLE_TYPES = [
    "field_mapping_table",
    "api_definition_table",
    "data_dictionary_table",
    "business_rule_table",
    "data_condition_table",
    "code_master_table",
    "test_case_table",
    "screen_definition_table",
    "config_table",
    "unknown_table",
]

# 種別ごとのキーワードセット (日本語・英語混在)
_KEYWORDS: dict[str, list[str]] = {
    "field_mapping_table": [
        "マッピング", "項目", "対応", "変換", "フィールド",
        "field", "mapping", "IF項目", "中間F",
    ],
    "api_definition_table": [
        "API", "エンドポイント", "endpoint", "method", "path",
        "リクエスト", "レスポンス", "メッセージ",
    ],
    "data_condition_table": [
        "データ取得条件", "取得条件", "条件", "condition", "filter", "WHERE",
    ],
    "business_rule_table": [
        "ルール", "rule", "判定", "処理", "業務ルール",
    ],
    "code_master_table": [
        "コード", "code", "名称", "マスタ", "master", "区分", "分類",
    ],
    "data_dictionary_table": [
        "データ型", "type", "length", "桁数", "論理名", "物理名", "必須",
    ],
    "screen_definition_table": [
        "画面", "screen", "表示", "入力", "ボタン",
    ],
    "test_case_table": [
        "テスト", "test", "ケース", "case", "期待", "結果",
    ],
    "config_table": [
        "設定", "config", "パラメータ", "parameter", "環境",
    ],
}

# 種別ごとの基本スコア重み (ヒット1件あたり)
_WEIGHT: dict[str, float] = {t: 1.0 for t in TABLE_TYPES}

# 種別ごとの最低信頼度しきい値
_MIN_CONFIDENCE = 0.15


def classify_table_region(table_region: dict[str, Any]) -> dict[str, Any]:
    """テーブル領域の種別を分類する。

    Parameters
    ----------
    table_region:
        ExcelTableParser.detect_tables() が返す table_regions の要素、
        または同等のキーを持つ dict。
        期待キー: sheet_name, columns, header_rows, region_type, (title)

    Returns
    -------
    dict with keys:
        table_type: str
        confidence: float (0.0〜1.0)
        matched_keywords: list[str]
        evidence: str
    """
    sheet_name: str = table_region.get("sheet_name", "")
    columns: list[str] = table_region.get("columns", [])
    region_type: str = table_region.get("region_type", "")
    title: str = table_region.get("title", "")
    data_sample: list[dict[str, Any]] = table_region.get("data_sample", [])

    # 検索対象テキストを構築
    search_parts = [sheet_name, title, region_type] + columns
    for row in data_sample[:5]:
        for v in row.values():
            if isinstance(v, str):
                search_parts.append(v)
    search_text = " ".join(search_parts)

    scores: dict[str, float] = {t: 0.0 for t in TABLE_TYPES}
    all_matched: dict[str, list[str]] = {t: [] for t in TABLE_TYPES}

    for table_type, keywords in _KEYWORDS.items():
        for kw in keywords:
            # 大文字小文字を無視した部分一致
            if re.search(re.escape(kw), search_text, re.IGNORECASE):
                scores[table_type] += _WEIGHT[table_type]
                all_matched[table_type].append(kw)

    # シート名・タイトルでのヒットは重みを増やす
    for table_type, keywords in _KEYWORDS.items():
        for kw in keywords:
            if re.search(re.escape(kw), sheet_name + " " + title, re.IGNORECASE):
                scores[table_type] += 1.5  # ボーナス

    total = sum(scores.values())
    best_type = max(scores, key=lambda t: scores[t])
    best_score = scores[best_type]

    if total == 0 or best_score / max(total, 1) < _MIN_CONFIDENCE:
        best_type = "unknown_table"
        confidence = 0.0
    else:
        # ソフトマックス的な正規化
        confidence = round(min(best_score / max(total, 1) * 2, 1.0), 3)

    matched_keywords = all_matched[best_type]
    evidence_parts = [f"sheet={sheet_name!r}"]
    if title:
        evidence_parts.append(f"title={title!r}")
    if matched_keywords:
        evidence_parts.append(f"keywords={matched_keywords}")
    evidence = ", ".join(evidence_parts)

    logger.debug(
        "classify_table_region: %s → %s (conf=%.3f, kw=%s)",
        table_region.get("table_region_id", "?"),
        best_type,
        confidence,
        matched_keywords,
    )

    return {
        "table_type": best_type,
        "confidence": confidence,
        "matched_keywords": matched_keywords,
        "evidence": evidence,
    }


def classify_batch(
    table_regions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """複数テーブル領域を一括分類する。

    Returns
    -------
    各 table_region に classify_table_region() の結果を merged した dict のリスト。
    """
    results: list[dict[str, Any]] = []
    for region in table_regions:
        classification = classify_table_region(region)
        merged = {**region, **classification}
        results.append(merged)
    return results


def write_classification_report(
    classified_regions: list[dict[str, Any]],
    output_path: str = "reports/table_type_classification_report.md",
) -> str:
    """分類結果を Markdown レポートとして書き出す。

    Parameters
    ----------
    classified_regions:
        classify_batch() の返り値。
    output_path:
        出力先パス。

    Returns
    -------
    書き出したファイルパス。
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# Table Type Classification Report",
        "",
        f"Total regions: {len(classified_regions)}",
        "",
        "| # | Workbook | Sheet | CellRange | TableType | Confidence | Keywords |",
        "|---|----------|-------|-----------|-----------|------------|----------|",
    ]

    type_counts: dict[str, int] = {}
    for i, reg in enumerate(classified_regions, start=1):
        t = reg.get("table_type", "unknown_table")
        type_counts[t] = type_counts.get(t, 0) + 1
        kw_str = ", ".join(reg.get("matched_keywords", []))[:60]
        lines.append(
            f"| {i} "
            f"| {reg.get('workbook_name', '')} "
            f"| {reg.get('sheet_name', '')} "
            f"| {reg.get('cell_range', '')} "
            f"| {t} "
            f"| {reg.get('confidence', 0.0):.3f} "
            f"| {kw_str} |"
        )

    lines += [
        "",
        "## Summary by Table Type",
        "",
        "| TableType | Count |",
        "|-----------|-------|",
    ]
    for t in TABLE_TYPES:
        lines.append(f"| {t} | {type_counts.get(t, 0)} |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote classification report → %s (%d regions)", output_path, len(classified_regions))
    return str(out)
