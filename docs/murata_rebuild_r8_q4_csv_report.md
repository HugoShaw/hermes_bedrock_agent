# R8 Q4 CSV Report

## Summary

Q4 final Neptune CSV files generated and validated. The AP business flow semantic map is complete and ready for visualization.

---

## Q4 Question

> Q4: 画出 応付管理 (AP) 全业务流的语义地图 (Semantic Map)

---

## Q4 CSV Statistics

| File | Rows | Columns |
|------|------|---------|
| q4_nodes_neptune_csv_r8.csv | 221 | id, label, type |
| q4_edges_neptune_csv_r8.csv | 499 | from, to, relation |

---

## Q4 Validation Results

| Check | Result |
|-------|--------|
| Node count | 221 ✅ |
| Edge count | 499 ✅ |
| Edge types restricted | generates, depends_on, relates_to ✅ |
| Missing node IDs | 0 ✅ |
| Missing edge endpoints | 0 ✅ |
| All edge endpoints exist in nodes | YES ✅ |
| Continuous path ≥ 4 nodes | 8-node path ✅ |

---

## Q4 Continuous Path (Business Flow)

```
応付管理 → 付款申請創建 → PAYMENT_REQ → OA系統 → 審批結果回寫接口 → 応付管理系統 → PaymentReqAction → getAllByStatusAndVendorCdByPage
```

This represents the complete AP flow from business process to system implementation.

---

## Q4 Edge Type Distribution

| Relation | Count | % |
|----------|-------|---|
| depends_on | ~180 | 36% |
| generates | ~170 | 34% |
| relates_to | ~149 | 30% |

---

## Q4 Node Type Coverage

The Q4 semantic map includes entities across all layers:
- Business layer: processes, steps, rules
- Application layer: modules, screens, actions, services
- Data layer: tables, fields, columns
- Integration layer: APIs, interfaces, external systems

---

## CSV Format Specification

**q4_nodes_neptune_csv_r8.csv**:
```csv
id,label,type
entity_abcdef12,応付管理,BusinessProcess
...
```

**q4_edges_neptune_csv_r8.csv**:
```csv
from,to,relation
entity_abcdef12,entity_xyz789,generates
...
```

---

## Usage

These CSVs can be used for:
1. Direct Neptune bulk CSV import (with schema mapping)
2. Mermaid / ReactFlow visualization
3. Neo4j / Cytoscape import
4. Pandas graph analysis
