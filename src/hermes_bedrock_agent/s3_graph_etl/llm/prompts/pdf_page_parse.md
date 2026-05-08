# PDF Page Parse Prompt

You are analyzing a page from a PDF document. Extract all meaningful content.

## Input
- Image of one PDF page

## Required Output (JSON)
```json
{
  "page_type": "text | table | diagram | form | mixed",
  "title": "section or page title if visible",
  "text_content": "all readable text on the page",
  "tables": [
    {
      "title": "table title",
      "headers": ["col1", "col2"],
      "rows": [["val1", "val2"]]
    }
  ],
  "entities": [
    {"name": "entity name", "label": "Entity | Table | API | Process", "context": "surrounding text"}
  ],
  "relations": [
    {"from": "entity A", "to": "entity B", "type": "RELATION_TYPE", "evidence": "text showing this relation"}
  ],
  "confidence": 0.0
}
```

## Rules
- Extract ALL text, including headers, footers, captions
- Identify tables and preserve structure
- Identify diagrams and describe their content
- All entities and relations must have evidence text
- Confidence 0.0-1.0 based on text clarity
