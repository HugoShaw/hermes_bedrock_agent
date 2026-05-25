"""
Evidence-first Pipeline — V2 modular Excel/Mermaid/Visual evidence extraction.

このパッケージはエンタープライズExcelドキュメントを構造化証拠レコードに変換します。
Neptune/Graph/Vector操作は一切行いません。

Stages:
  1. S3 source discovery
  2. Excel parsing (workbooks + sheets)
  3. Table detection + row normalization
  4. Visual prescan (OOXML-based, no rendering required)
  5. OOXML drawing/shape/connector extraction
  6. Embedded image extraction
  7. Mermaid file parsing
  8. Optional VLM analysis (Bedrock Claude Sonnet)
  9. Evidence record building (unified JSONL)
  10. Markdown export + human review checklist
  11. Run reporting
  12. S3 upload
"""

__version__ = "1.0.0"
