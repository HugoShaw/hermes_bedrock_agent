"""
Header role detector — テーブルの各カラムのロールを検出するモジュール。

ヘッダーテキスト・マージセル構造・カラム位置から
各カラムが source_field / target_field / mapping_rule などのどのロールに
対応するかを推定する。
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# カラムロールの許可値
COLUMN_ROLES = [
    "source_system",
    "source_field",
    "source_data_type",
    "source_length",
    "target_system",
    "target_field",
    "target_data_type",
    "target_length",
    "mapping_rule",
    "condition",
    "description",
    "required",
    "default_value",
    "code_value",
    "remarks",
    "api_name",
    "method",
    "path",
    "request_message",
    "response_message",
    "item_no",
    "item_name",
    "unknown",
]

# ヘッダーパターン: (正規表現, ロール候補リスト)
# ロール候補は位置によって確定する (source/target の区別は位置で行う)
_HEADER_PATTERNS: list[tuple[re.Pattern[str], list[str]]] = [
    # 番号系
    (re.compile(r"^(no\.?|番号|項番|no)$", re.IGNORECASE), ["item_no"]),
    # 項目名系 (source_field or target_field — 位置で解決)
    (re.compile(r"(項目名|項目|フィールド名|フィールド|field\s*name|field)", re.IGNORECASE), ["source_field", "target_field"]),
    # データ型系
    (re.compile(r"(型|タイプ|type|データ型|data\s*type)", re.IGNORECASE), ["source_data_type", "target_data_type"]),
    # 桁数系
    (re.compile(r"(桁|桁数|length|サイズ|size|len)", re.IGNORECASE), ["source_length", "target_length"]),
    # システム名系
    (re.compile(r"(システム|system|送信元|送信先|source|target|連携先|連携元)", re.IGNORECASE), ["source_system", "target_system"]),
    # マッピングルール系
    (re.compile(r"(変換|ルール|rule|マッピング|mapping|変換規則)", re.IGNORECASE), ["mapping_rule"]),
    # 条件系
    (re.compile(r"(条件|condition|取得条件|filter|where)", re.IGNORECASE), ["condition"]),
    # 説明・備考系
    (re.compile(r"(説明|description|備考|remarks|備考欄|note)", re.IGNORECASE), ["description", "remarks"]),
    # 必須系
    (re.compile(r"(必須|required|○×|require)", re.IGNORECASE), ["required"]),
    # デフォルト値系
    (re.compile(r"(デフォルト|default|初期値|既定)", re.IGNORECASE), ["default_value"]),
    # コード値系
    (re.compile(r"(コード値|code\s*value|コード|code)", re.IGNORECASE), ["code_value"]),
    # API名系
    (re.compile(r"(api\s*名?|api\s*name|インターフェース名?)", re.IGNORECASE), ["api_name"]),
    # HTTPメソッド系
    (re.compile(r"^(method|メソッド|http\s*method)$", re.IGNORECASE), ["method"]),
    # パス系
    (re.compile(r"^(path|パス|uri|url|endpoint)$", re.IGNORECASE), ["path"]),
    # リクエストメッセージ系
    (re.compile(r"(リクエスト|request|要求)", re.IGNORECASE), ["request_message"]),
    # レスポンスメッセージ系
    (re.compile(r"(レスポンス|response|応答)", re.IGNORECASE), ["response_message"]),
    # 項目名 (item_name)
    (re.compile(r"(名称|name|名前|item\s*name)", re.IGNORECASE), ["item_name"]),
]

# マージセルによるグループ名と source/target 対応
_SOURCE_GROUP_PATTERNS = re.compile(r"(送信元|source|ソース|連携元|IF項目|中間F|変換前)", re.IGNORECASE)
_TARGET_GROUP_PATTERNS = re.compile(r"(送信先|target|ターゲット|連携先|変換後)", re.IGNORECASE)


def detect_column_roles(table_region: dict[str, Any]) -> dict[str, Any]:
    """テーブル領域の各カラムのロールを検出する。

    Parameters
    ----------
    table_region:
        ExcelTableParser.detect_tables() が返す table_regions の要素。
        期待キー: columns, header_rows, merged_cells (オプション)

    Returns
    -------
    dict with keys:
        column_roles: dict[str, str]   カラム名 → ロール
        header_structure: dict         マージセルグループ情報
        confidence: float
    """
    columns: list[str] = table_region.get("columns", [])
    merged_cells: list[dict[str, Any]] = table_region.get("merged_cells", [])

    if not columns:
        return {"column_roles": {}, "header_structure": {}, "confidence": 0.0}

    # マージセルグループを解析して source/target 区域を特定
    group_map = _build_group_map(merged_cells, len(columns))

    column_roles: dict[str, str] = {}
    matched_count = 0

    for col_idx, col_name in enumerate(columns):
        role = _detect_single_role(col_name, col_idx, group_map, len(columns))
        column_roles[col_name] = role
        if role != "unknown":
            matched_count += 1

    confidence = round(matched_count / max(len(columns), 1), 3)

    header_structure = _extract_header_structure(columns, group_map)

    logger.debug(
        "detect_column_roles: %d/%d columns matched (conf=%.3f)",
        matched_count,
        len(columns),
        confidence,
    )

    return {
        "column_roles": column_roles,
        "header_structure": header_structure,
        "confidence": confidence,
    }


def _detect_single_role(
    col_name: str,
    col_idx: int,
    group_map: dict[int, str],
    total_cols: int,
) -> str:
    """1カラムのロールを決定する。"""
    clean = col_name.strip()

    # パターンマッチング
    for pattern, candidates in _HEADER_PATTERNS:
        if pattern.search(clean):
            if len(candidates) == 1:
                return candidates[0]
            # source/target の曖昧な候補は位置・グループで解決
            return _resolve_source_target(candidates, col_idx, group_map, total_cols)

    return "unknown"


def _resolve_source_target(
    candidates: list[str],
    col_idx: int,
    group_map: dict[int, str],
    total_cols: int,
) -> str:
    """source/target 曖昧候補を位置・グループで解決する。"""
    group_label = group_map.get(col_idx, "")

    if group_label:
        if _SOURCE_GROUP_PATTERNS.search(group_label):
            return next((c for c in candidates if c.startswith("source_")), candidates[0])
        if _TARGET_GROUP_PATTERNS.search(group_label):
            return next((c for c in candidates if c.startswith("target_")), candidates[-1])

    # グループ情報がない場合は列位置で推定 (前半→source, 後半→target)
    midpoint = total_cols / 2
    if col_idx < midpoint:
        return next((c for c in candidates if c.startswith("source_")), candidates[0])
    return next((c for c in candidates if c.startswith("target_")), candidates[-1])


def _build_group_map(
    merged_cells: list[dict[str, Any]],
    total_cols: int,
) -> dict[int, str]:
    """マージセル情報から列インデックス → グループ名のマップを構築する。

    merged_cells の各要素は {"value": str, "min_col": int, "max_col": int} を想定
    (openpyxl の MergedCell 情報を dict 化したもの)。
    列インデックスは 0 始まりに変換する。
    """
    group_map: dict[int, str] = {}
    for mc in merged_cells:
        label = str(mc.get("value", "")).strip()
        if not label:
            continue
        min_col = mc.get("min_col", 1) - 1  # 1始まり → 0始まり
        max_col = mc.get("max_col", min_col + 1) - 1
        for ci in range(min_col, max_col + 1):
            if 0 <= ci < total_cols:
                group_map[ci] = label
    return group_map


def _extract_header_structure(
    columns: list[str],
    group_map: dict[int, str],
) -> dict[str, Any]:
    """ヘッダー構造情報を整理して返す。"""
    groups: dict[str, list[str]] = {}
    ungrouped: list[str] = []

    for ci, col in enumerate(columns):
        group_label = group_map.get(ci, "")
        if group_label:
            groups.setdefault(group_label, []).append(col)
        else:
            ungrouped.append(col)

    return {
        "groups": groups,
        "ungrouped_columns": ungrouped,
        "total_columns": len(columns),
        "has_merged_header": len(groups) > 0,
    }
