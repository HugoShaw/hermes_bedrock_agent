# Table Parse Prompt

You are analyzing an image containing a table (screenshot, scanned document, or spreadsheet image).

## Input
- Image containing one or more tables

## Required Output (JSON)
```json
{
  "tables": [
    {
      "title": "table title or caption",
      "description": "what this table represents",
      "headers": ["column1", "column2", "column3"],
      "rows": [
        ["value1", "value2", "value3"]
      ],
      "entities": [
        {"name": "entity from table", "label": "Table | Column | Field", "context": "row/column context"}
      ],
      "relations": [
        {"from": "entity A", "to": "entity B", "type": "USES_COLUMN | CONTAINS", "evidence": "evidence text"}
      ]
    }
  ],
  "confidence": 0.0
}
```

## Rules
- Preserve exact table structure (rows and columns)
- Handle merged cells by repeating values
- Extract entities (table names, column names, field types)
- Identify foreign key / reference relationships
- Confidence based on table readability
