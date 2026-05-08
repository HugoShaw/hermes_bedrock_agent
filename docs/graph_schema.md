# Graph Schema

## Node Labels

| Label    | Description                          | Required Properties |
|----------|--------------------------------------|---------------------|
| Document | Source document from S3              | name, source_uri    |
| Section  | Document section/heading             | name                |
| Table    | Database table                       | name                |
| Column   | Table column                         | name, table_name    |
| API      | API endpoint                         | name                |
| Process  | Business process                     | name                |
| Rule     | Business rule                        | name                |
| Service  | System/service component             | name                |
| Module   | Software module                      | name                |
| Entity   | Generic entity                       | name                |

## Edge Types

| Type                | Description                                  |
|---------------------|----------------------------------------------|
| CONTAINS            | Hierarchical containment (doc->section)      |
| REFERENCES          | Generic reference between entities            |
| USES_TABLE          | Process/API uses a database table            |
| USES_COLUMN         | Process/API uses a specific column           |
| CALLS_API           | Service/module calls an API                  |
| IMPLEMENTS_PROCESS  | Module/service implements a business process |
| DESCRIBES_RULE      | Section/document describes a business rule   |
| DEPENDS_ON          | Dependency relationship                      |
| SAME_AS             | Identity/equivalence relationship            |
| RELATED_TO          | Generic relationship                         |
| FLOWS_TO            | Data/process flow direction                  |

## Neptune Analytics Conventions

- Node identity: `~id` property (string, unique)
- Node ID format: `{label_lower}:{name_slug}` (e.g., `table:payment_header`)
- Edge identity: `~id` property on relationship
- Edge ID format: `rel:{from_id}-[{type}]->{to_id}`
- Vector index: use `neptune.algo.vectors.upsert(node, embedding)`
- All string properties use single quotes in openCypher
- No array properties (Neptune Analytics limitation)
- Empty strings instead of NULL for optional text fields
