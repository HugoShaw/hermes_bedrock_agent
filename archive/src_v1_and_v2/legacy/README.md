# Legacy Code

This directory holds code from the original experimental implementation that has
been superseded by the new Enterprise GraphRAG architecture.

These modules are kept as reference during migration:

- `graphrag/` — Early GraphRAG experiment (spaCy NER, SQLite, regex extraction)
- `doc_analyze/` — Document analysis + Mermaid rendering
- `s3_graph_etl/` — Original S3-to-Graph ETL pipeline (being refactored)
- `semantic_map_workflow/` — Semantic Map workflow (external to src/)

Do NOT import from this directory in new code. If you need functionality from
here, port it to the appropriate new module under the enterprise structure.
