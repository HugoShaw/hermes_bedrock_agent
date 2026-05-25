# R12 Visualization Report

## Graph Visualizations Generated

### 1. JOURNAL_BASE Subgraph

| Metric | Value |
|--------|-------|
| Focus | JOURNAL_BASE |
| Nodes | 27 |
| Edges | 40 |
| Hub connections | Rich — connects to tables, fields, processes, modules |
| Key neighbors | RECEIVING_LIST, PAYMENT_REQ, SUN_REQUEST, JournalBaseAction |

JOURNAL_BASE is the most connected entity in the rebuild graph. The visualization shows it as a central hub linking:
- Upstream: MS系統, HULFT, external data sources
- Downstream: RECEIVING_JOURNAL, PAYMENT_REQ, SUN_REQUEST
- Code: JournalBaseAction, JournalBaseService
- Fields: OTHER_SYSTEM_NO, LIST_TYPE, CPL_MK, STATUS

### 2. PAYMENT_REQ Subgraph

| Metric | Value |
|--------|-------|
| Focus | PAYMENT_REQ |
| Nodes | 8 |
| Edges | 11 |
| Key neighbors | PAYMENT_RECEIVING, PaymentReqAction, 付款審批 |

Compact graph showing the payment request lifecycle:
- Input: From RECEIVING_JOURNAL approval
- Processing: PaymentReqAction module
- Output: PAYMENT_RECEIVING, SUN_REQUEST generation
- Approval: 付款審批 process node

### 3. AP Business Flow

| Metric | Value |
|--------|-------|
| Focus | AP_FLOW (auto-query) |
| Nodes | 40 |
| Edges | 24 |
| Coverage | Full AP chain from MS to SUN ERP |

Broader view of the entire accounts payable workflow:
- External systems (MS, HULFT, SUN, OA)
- Core tables (JOURNAL_BASE, RECEIVING_*, PAYMENT_*)
- Business processes (対帳, 検収, 審批, 支払)
- Approval flows

### 4. Q4 Semantic Map (Curated)

| Metric | Value |
|--------|-------|
| Focus | Q4_SEMANTIC (curated) |
| Nodes | 15 |
| Edges | 15 |
| Main chain | 11 steps from MS to 報表 |
| Relations | generates, depends_on, relates_to only |

Clean, presentation-ready semantic map of the main AP flow:

```
MS系統 →(generates)→ HULFT →(generates)→ JOURNAL_BASE
→(generates)→ RECEIVING_LIST →(depends_on)→ 対帳単審批
→(generates)→ RECEIVING_JOURNAL →(generates)→ PAYMENT_REQ
→(depends_on)→ 付款審批 →(generates)→ PAYMENT_RECEIVING
→(generates)→ SUN_REQUEST →(generates)→ SUN ERP
→(generates)→ 報表
```

Plus supporting nodes:
- CUSTODIAN (relates_to both approval steps)
- CLIENT_ENTITY (relates_to PAYMENT_REQ)
- OA系統 (relates_to 付款審批)

## Output Formats

### Mermaid

- Embeddable in Markdown docs and GitHub
- Renderable via mermaid.live or VS Code extension
- Suitable for presentations (copy-paste into slides)

### HTML (vis.js)

- Self-contained HTML files (no server needed)
- Interactive: drag, zoom, hover
- Color-coded by node type
- Physics-based layout (force-directed)
- CDN dependency: vis-network (unpkg)

### ReactFlow JSON

- Compatible with ReactFlow React component library
- Positioned grid layout (adjustable)
- Typed edges (smoothstep, animated for generates)
- Styled nodes with color by type
- Ready for embedding in React dashboard

## Visualization Color Scheme

| Node Type | Color | Examples |
|-----------|-------|----------|
| Table | #4fc3f7 (blue) | JOURNAL_BASE, PAYMENT_REQ |
| Process | #81c784 (green) | 対帳単審批, 付款審批 |
| External | #ffb74d (orange) | MS系統, SUN ERP, OA |
| Other | #ce93d8 (purple) | Fields, Roles, Modules |
