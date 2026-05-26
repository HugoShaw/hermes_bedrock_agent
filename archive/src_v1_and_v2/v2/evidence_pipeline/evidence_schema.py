"""
Evidence record schema — パイプライン全体の統一証拠レコード定義。

全ステージの出力はこのスキーマに正規化される。
最終成果物: parsed_text_records.jsonl
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# record_type の許可値
VALID_RECORD_TYPES = frozenset({
    "sheet_text",
    "table_region",
    "table_row",
    "cell_block",
    "drawing_object",
    "connector",
    "chart",
    "image_reference",
    "sheet_screenshot",
    "mermaid_graph",
    "mermaid_node",
    "mermaid_edge",
    "visual_analysis",
    "formula",
    "comment",
    # セマンティックテーブル解析用
    "sheet_summary",
    "table_header_structure",
    "field_definition",
    "business_rule",
    "graph_candidate",
    "raw_table_markdown",
})

# record_role の許可値
VALID_RECORD_ROLES = frozenset({
    "field_mapping",
    "api_definition",
    "business_rule",
    "data_condition",
    "code_master",
    "config",
    "unknown",
})


@dataclass
class EvidenceRecord:
    """統一証拠レコード — 全パーサーの出力形式。

    Attributes
    ----------
    record_id:
        SHA256ベースの決定論的ID。
    record_type:
        レコード種別 (VALID_RECORD_TYPES のいずれか)。
    dataset:
        データセット名 (例: sample_20260519)。
    run_id:
        パイプライン実行ID。
    source_file:
        元ファイルのローカルパス。
    source_s3_uri:
        元ファイルのS3 URI (例: s3://bucket/key)。
    workbook_name:
        ワークブック名 (Excelファイル名)。
    sheet_name:
        シート名。
    sheet_index:
        シートインデックス (0始まり)。
    cell_range:
        セル範囲 (例: B3:H42)。
    row_number:
        行番号 (1始まり)。テーブル行の場合のみ。
    column_names:
        カラム名リスト。
    text:
        テキスト内容 (UTF-8)。
    image_path:
        画像ファイルのローカルパス (参照のみ、埋め込みなし)。
    mermaid_source:
        Mermaidソーステキスト。
    metadata:
        追加メタデータ。
    parser:
        このレコードを生成したパーサーモジュール名。
    confidence:
        検出信頼度 (0.0〜1.0)。
    created_at:
        ISO 8601形式の生成タイムスタンプ。
    """

    record_id: str = ""
    record_type: str = "sheet_text"
    dataset: str = ""
    run_id: str = ""
    source_file: str = ""
    source_s3_uri: str = ""
    workbook_name: str = ""
    sheet_name: str = ""
    sheet_index: int = 0
    cell_range: str = ""
    row_number: Optional[int] = None
    column_names: list[str] = field(default_factory=list)
    text: str = ""
    image_path: str = ""
    mermaid_source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    parser: str = ""
    confidence: float = 1.0
    created_at: str = ""
    # セマンティックテーブル解析フィールド
    record_role: str = ""
    table_region_id: str = ""
    text_for_embedding: str = ""
    text_for_llm: str = ""
    text_for_display: str = ""
    raw_values: dict[str, Any] = field(default_factory=dict)
    normalized_values: dict[str, Any] = field(default_factory=dict)
    source_cell_refs: dict[str, str] = field(default_factory=dict)
    table_type: str = ""
    column_roles: dict[str, str] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    entity_mentions: list[str] = field(default_factory=list)
    relation_hints: list[str] = field(default_factory=list)
    graph_hints: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if self.record_type not in VALID_RECORD_TYPES:
            raise ValueError(
                f"Invalid record_type '{self.record_type}'. "
                f"Must be one of: {sorted(VALID_RECORD_TYPES)}"
            )
        if not self.record_id:
            self.record_id = self.generate_record_id()

    def generate_record_id(self) -> str:
        """コンテンツハッシュに基づく決定論的ID生成。"""
        raw = "|".join([
            self.record_type,
            self.dataset,
            self.run_id,
            self.source_file,
            self.workbook_name,
            self.sheet_name,
            str(self.sheet_index),
            self.cell_range,
            str(self.row_number),
            self.table_type,
            self.text[:200],  # 最初の200文字のみハッシュ対象
        ])
        return "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    def to_json_line(self) -> str:
        """Serialize to a single JSONL line (UTF-8, ensure_ascii=False)。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceRecord":
        """Deserialize from dict."""
        import dataclasses
        # record_id は復元後に再生成しない
        record = cls.__new__(cls)
        for f in dataclasses.fields(cls):
            if f.name in data:
                setattr(record, f.name, data[f.name])
            elif f.default is not dataclasses.MISSING:
                setattr(record, f.name, f.default)
            elif f.default_factory is not dataclasses.MISSING:  # type: ignore[misc]
                setattr(record, f.name, f.default_factory())  # type: ignore[misc]
            else:
                setattr(record, f.name, None)
        return record

    @classmethod
    def from_json_line(cls, line: str) -> "EvidenceRecord":
        """Deserialize from a JSONL line."""
        return cls.from_dict(json.loads(line.strip()))


def write_jsonl(records: list[EvidenceRecord], output_path: str) -> int:
    """Write a list of EvidenceRecord objects to a JSONL file.

    Returns the number of records written.
    """
    from pathlib import Path
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(output_path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(rec.to_json_line() + "\n")
            count += 1
    return count


def read_jsonl(path: str) -> list[EvidenceRecord]:
    """Read JSONL file and return list of EvidenceRecord."""
    records: list[EvidenceRecord] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(EvidenceRecord.from_json_line(line))
    return records
