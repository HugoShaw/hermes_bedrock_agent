"""Phase 10/12: Extraction report and Graph Explore query generation."""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path


def generate_extraction_report(
    project_id: str,
    project_name: str,
    input_dirs: list[str],
    output_dir: str,
    neptune_endpoint: str,
    inventory: list[dict],
    evidence_units: list[dict],
    nodes: list[dict],
    edges: list[dict],
    display_nodes: list[dict],
    display_edges: list[dict],
    candidate_links: list[dict],
    review_tasks: list[dict],
) -> str:
    """Generate the comprehensive extraction report markdown."""
    type_counts = Counter(n.get("entity_type", "Unknown") for n in nodes)
    edge_type_counts = Counter(e.get("type", "Unknown") for e in edges)
    sheet_type_counts = Counter(f["sheet_type"] for f in inventory)
    layer_counts = Counter(n.get("layer", "unknown") for n in nodes)

    mermaid_sheets = sum(1 for f in inventory if f.get("has_mermaid"))
    mapping_sheets = sum(1 for f in inventory if f.get("has_mapping_table"))
    function_modules = type_counts.get("FunctionModule", 0)
    flow_nodes = (
        type_counts.get("FlowNode", 0)
        + type_counts.get("ScriptStep", 0)
        + type_counts.get("FileOperation", 0)
    )
    field_mappings = type_counts.get("FieldMapping", 0)

    function_ids = {n["id"] for n in nodes if n.get("entity_type") == "FunctionModule"}
    functions_with_internal = sum(
        1 for e in edges
        if e.get("type") == "CONTAINS_STEP" and e.get("start_id") in function_ids
    )
    cross_sheet = sum(
        1 for e in edges if e.get("link_method") in ("cross_sheet", "cross_sheet_name_match")
    )

    empty_source = sum(1 for n in nodes if not n.get("source_file"))
    empty_evidence = sum(1 for n in nodes if not n.get("evidence_text"))

    connected: set[str] = set()
    for e in edges:
        connected.add(e.get("start_id", ""))
        connected.add(e.get("end_id", ""))
    isolated = sum(1 for n in nodes if n["id"] not in connected)

    workbooks = {f["workbook_name"] for f in inventory}

    return f"""# Semantic Map Extraction Report
## Project: {project_name} ({project_id})
## Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}

---

## 1. Project Profile
- project_name: {project_name}
- project_id: {project_id}
- input_dirs: {input_dirs}
- output_dir: {output_dir}
- neptune_endpoint: {neptune_endpoint}

## 2. Input Summary
- Markdown file count: {len(inventory)}
- Workbook / document group count: {len(workbooks)}
- Sheet count: {len(inventory)}
- Successful reads: {sum(1 for f in inventory if f['read_status'] == 'success')}
- Failed reads: {sum(1 for f in inventory if f['read_status'] == 'failed')}

## 3. Sheet Type Distribution
{chr(10).join(f'- {t}: {c}' for t, c in sheet_type_counts.most_common())}

## 4. Evidence Units
- Total evidence units: {len(evidence_units)}
- Section type: {sum(1 for e in evidence_units if e['evidence_type'] == 'section')}
- Table type: {sum(1 for e in evidence_units if e['evidence_type'] == 'table')}
- Mermaid type: {sum(1 for e in evidence_units if e['evidence_type'] == 'mermaid')}

## 5. Semantic Extraction Results
### Node Counts by Entity Type
{chr(10).join(f'- {t}: {c}' for t, c in type_counts.most_common())}

### Edge Counts by Relationship Type
{chr(10).join(f'- {t}: {c}' for t, c in edge_type_counts.most_common())}

### Layer Distribution
{chr(10).join(f'- {t}: {c}' for t, c in layer_counts.most_common())}

## 6. Graph Statistics
- Full Graph nodes: {len(nodes)}
- Full Graph edges: {len(edges)}
- Display Graph nodes: {len(display_nodes)}
- Display Graph edges: {len(display_edges)}
- Candidate links (pending): {len(candidate_links)}
- Review tasks: {len(review_tasks)}

## 7. Detailed Coverage
- Mermaid block count (sheets with Mermaid): {mermaid_sheets}
- Mapping sheet count: {mapping_sheets}
- FunctionModule count: {function_modules}
- FunctionModules with internal nodes (CONTAINS_STEP): {functions_with_internal}
- Internal FlowNode / ScriptStep / FileOperation count: {flow_nodes}
- FieldMapping count: {field_mappings}
- Cross-document / cross-sheet link count: {cross_sheet}

## 8. Quality Metrics
- Empty source_file count: {empty_source}
- Empty evidence_text count: {empty_evidence}
- Isolated node count: {isolated}
- Pending relationship count: {sum(1 for e in edges if e.get('review_status') == 'pending')}

## 9. Depth Level Assessment
- L1 Document provenance: ✅ Complete (project → workbook → sheet structure)
- L2 System / Interface / BusinessProcess: {'✅ Present' if type_counts.get('System', 0) > 0 else '⚠️ Missing'}
- L3 FunctionModule / APIOperation / MappingDefinition: {'✅ Present' if function_modules > 0 else '⚠️ Missing'}
- L4 FlowNode / APICallStep / ScriptStep / FileOperation: {'✅ Present' if flow_nodes > 0 else '⚠️ Partial/Missing'}
- L5 FieldMapping / FilterCondition / TransformationRule: {'✅ Present' if field_mappings > 0 else '⚠️ Partial/Missing'}
- L6 EvidenceUnit / row-level traceability: ✅ Complete ({len(evidence_units)} units)

## 10. Main Risks
- {'High isolated node ratio' if isolated > len(nodes) * 0.3 else 'Isolated nodes within acceptable range'}
- {'Large sheets may have truncated extraction' if any(f['content_length'] > 25000 for f in inventory) else 'All sheets within extraction size limit'}
- {'Cross-sheet linking could be stronger' if cross_sheet < 5 else 'Cross-sheet linking present'}

## 11. Next-Round Optimization Suggestions
1. Review pending relationships in candidate_links.jsonl
2. Manually verify low-confidence entities
3. Add more cross-sheet linking for shared systems/APIs
4. Extract row-level field mappings for large mapping sheets
5. Verify FunctionModules without internal steps have ReviewTasks

## 12. Verification Queries (Graph Explorer)

### Node count by entity type
```cypher
MATCH (n) WHERE n.project_id = '{project_id}'
RETURN labels(n) AS entity_type, count(n) AS cnt
ORDER BY cnt DESC
```

### Edge count by relationship type
```cypher
MATCH (a)-[r]->(b) WHERE a.project_id = '{project_id}'
RETURN type(r) AS relationship, count(r) AS cnt
ORDER BY cnt DESC
```

### Orphan nodes (no edges)
```cypher
MATCH (n) WHERE n.project_id = '{project_id}'
AND NOT (n)--()
RETURN n.id, labels(n), n.name
LIMIT 20
```

### Cross-sheet links
```cypher
MATCH (a)-[r]->(b)
WHERE a.project_id = '{project_id}'
AND a.source_file <> b.source_file
RETURN type(r) AS rel, count(r) AS cnt
ORDER BY cnt DESC
```

### Low confidence edges (review candidates)
```cypher
MATCH (a)-[r]->(b)
WHERE a.project_id = '{project_id}'
AND r.confidence < 0.70
RETURN r.type, r.confidence, r.link_method, a.name, b.name
ORDER BY r.confidence ASC
LIMIT 30
```
"""


def generate_graph_explore_queries(project_id: str, project_name: str, output_path: Path) -> None:
    """Write Neptune Graph Explore validation queries to file."""
    pid = project_id
    pname = project_name

    queries = f"""// ═══════════════════════════════════════════════════════════════
// Semantic Map Graph Explore Queries
// Project: {pname} ({pid})
// ═══════════════════════════════════════════════════════════════

// 1. All core systems in this project
MATCH (n:System)
WHERE n.project_id = '{pid}'
RETURN n.id, n.display_name, n.description, n.source_file
ORDER BY n.display_name;

// 2. Display Graph overview (project -> systems -> processes)
MATCH p = (proj:Project {{project_id: '{pid}'}})-[*1..3]-(n)
RETURN p
LIMIT 300;

// 3. Expand from Interface to systems, APIs, mappings
MATCH p = (i:Interface)-[:FROM_SYSTEM|TO_SYSTEM|VIA_MIDDLEWARE|HAS_API_OPERATION|USES_MAPPING*1..2]-(n)
WHERE i.project_id = '{pid}'
RETURN p
LIMIT 200;

// 4. Three hops from FunctionModule
MATCH p = (f:FunctionModule)-[*1..3]-(n)
WHERE f.project_id = '{pid}'
RETURN p
LIMIT 300;

// 5. All Mermaid-derived FlowNodes
MATCH (n:FlowNode)
WHERE n.project_id = '{pid}'
RETURN n.id, n.display_name, n.flow_node_kind, n.parent_function_id, n.source_file
ORDER BY n.parent_function_id, n.sequence_no;

// 6. Internal nodes of FunctionModule (CONTAINS_STEP)
MATCH p = (f:FunctionModule)-[:CONTAINS_STEP|STARTS_WITH|ENDS_WITH]-(step)
WHERE f.project_id = '{pid}'
RETURN p
LIMIT 300;

// 7. Internal flow order
MATCH p = (f:FunctionModule)-[:CONTAINS_STEP]->(s1)-[:NEXT_STEP*0..5]->(s2)
WHERE f.project_id = '{pid}'
RETURN p
LIMIT 300;

// 8. Branch and condition labels
MATCH (a)-[r]->(b)
WHERE a.project_id = '{pid}'
  AND (
    r.edge_label IS NOT NULL OR
    r.branch_label IS NOT NULL OR
    r.condition_text IS NOT NULL OR
    type(r) IN ['BRANCHES_TO','HAS_BRANCH_CONDITION','HAS_CONDITION']
  )
RETURN labels(a) AS source_labels, a.display_name AS source_name,
       type(r) AS rel_type, r.edge_label, r.branch_label, r.condition_text,
       labels(b) AS target_labels, b.display_name AS target_name
ORDER BY source_name
LIMIT 300;

// 9. FlowNode -> API -> MappingDefinition -> FieldMapping path
MATCH p = (fn)-[:CALLS_API]->(api:APIOperation)-[:USES_MAPPING]->(m:MappingDefinition)-[:HAS_MAPPING_ROW]->(fm:FieldMapping)
WHERE fn.project_id = '{pid}'
RETURN p
LIMIT 200;

// 10. Source-target field mappings
MATCH (fm:FieldMapping)-[:HAS_SOURCE_FIELD]->(sf:Field)
WHERE fm.project_id = '{pid}'
OPTIONAL MATCH (fm)-[:HAS_TARGET_FIELD]->(tf:Field)
RETURN fm.id, sf.display_name AS source_field, tf.display_name AS target_field, fm.evidence_text
LIMIT 200;

// 11. TransformationRule -> Field paths
MATCH p = (r:TransformationRule)-[:USES_FIELD|APPLIES_RULE]-(n)
WHERE r.project_id = '{pid}'
RETURN p
LIMIT 200;

// 12. All DecisionPoints and Conditions
MATCH p = (dp:DecisionPoint)-[:HAS_BRANCH_CONDITION|HAS_CONDITION|BRANCHES_TO]-(n)
WHERE dp.project_id = '{pid}'
RETURN p
LIMIT 200;

// 13. All pending ReviewTasks
MATCH (n)
WHERE n.project_id = '{pid}' AND n.review_status = 'pending'
RETURN labels(n) AS labels, n.id, n.display_name, n.evidence_text
LIMIT 100;

// 14. Nodes with empty source_file or evidence
MATCH (n)
WHERE n.project_id = '{pid}'
  AND (n.source_file IS NULL OR n.source_file = '' OR n.evidence_text IS NULL OR n.evidence_text = '')
RETURN labels(n), n.id, n.display_name, n.source_file, n.evidence_text
LIMIT 100;

// 15. Isolated nodes
MATCH (n)
WHERE n.project_id = '{pid}'
  AND NOT EXISTS {{ MATCH (n)-[]-() }}
RETURN labels(n), n.id, n.display_name
LIMIT 100;

// 16. API Call Sequence graph
MATCH p = (seq:APICallSequence)-[:HAS_API_CALL_STEP|NEXT_STEP*1..3]-(n)
WHERE seq.project_id = '{pid}'
RETURN p
LIMIT 200;

// 17. Middleware implementation graph
MATCH p = (spec:ImplementationSpec)-[:HAS_SCRIPT_STEP|NEXT_STEP|READS_FILE|WRITES_FILE|CALLS_API*1..3]-(n)
WHERE spec.project_id = '{pid}'
RETURN p
LIMIT 300;

// 18. Data retrieval conditions
MATCH p = (cond:DataRetrievalCondition)-[:HAS_FILTER_CONDITION|USES_FIELD|APPLIES_RULE*1..2]-(n)
WHERE cond.project_id = '{pid}'
RETURN p
LIMIT 200;

// 19. Node label distribution
MATCH (n)
WHERE n.project_id = '{pid}'
RETURN labels(n) AS node_labels, count(n) AS count
ORDER BY count DESC;

// 20. Relationship type distribution
MATCH (a)-[r]->(b)
WHERE a.project_id = '{pid}' OR b.project_id = '{pid}'
RETURN type(r) AS relationship_type, count(r) AS count
ORDER BY count DESC;

// 21. Schema matrix
MATCH (a)-[r]->(b)
WHERE a.project_id = '{pid}' OR b.project_id = '{pid}'
RETURN labels(a) AS source_labels, type(r) AS rel_type, labels(b) AS target_labels, count(r) AS count
ORDER BY count DESC, rel_type
LIMIT 100;

// 22. Full display graph visualization
MATCH (a)-[r]-(b)
WHERE a.project_id = '{pid}' OR b.project_id = '{pid}'
RETURN a, r, b
LIMIT 500;
"""
    output_path.write_text(queries, encoding="utf-8")
