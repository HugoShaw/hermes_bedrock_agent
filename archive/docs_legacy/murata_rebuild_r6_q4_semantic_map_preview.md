# R6 Q4 Semantic Map Preview

## Overview

Q4 asks for a semantic map of the complete AP (応付管理) business flow:

```
订单 → 対帳単 → 審批 → 付款申請 → 審批 → 支付 → 報表
```

## Extracted Q4 Graph

| Metric | Value |
|--------|-------|
| Q4 preview nodes | 286 |
| Q4 preview edges | 149 |
| Edge types | generates, depends_on, relates_to |
| Longest continuous path | 8 nodes |

## Continuous Path (A → B → C → D requirement)

**Verified path (8 nodes):**

```
外部数据导入 → 対帳単生成 → 付款申請創建 → 審批 → GL記帳/支付 → SUN_REQUEST → HULFT → SUN ERP
```

This path traces the complete AP flow from data import through to external system export.

## Key Process Nodes in Semantic Map

### Business Layer
- 外部データ取込 (External Data Import)
- 対帳単生成 (Reconciliation Statement Generation)
- 対帳単確認 (Reconciliation Statement Confirmation)
- 付款申請創建 (Payment Request Creation)
- 付款申請審批 (Payment Request Approval)
- GL記帳/支付 (GL Posting/Payment)
- 報表出力 (Report Output)

### System Layer
- SUN ERP (External System)
- HULFT (File Transfer)
- MDW (Core System)
- OA System (Approval - proposed migration target)

### Data Layer
- RECEIVING_JOURNAL (受入仕訳)
- JOURNAL_BASE (仕訳基礎)
- PAYMENT_REQ (付款申請)
- SUN_REQUEST (SUN請求)
- RECEIVING_LIST (受入明細)
- PAYMENT_RECEIVING (付款受入)

## Edge Type Distribution (Q4 Preview)

| Type | Count | Meaning |
|------|-------|---------|
| generates | ~60 | Step A produces output for Step B |
| depends_on | ~50 | Step B requires Step A to complete |
| relates_to | ~39 | Semantic association |

## Alignment with Target Q4 Flow

| Target Step | Extracted Node | Status |
|-------------|---------------|--------|
| 订单 | 外部データ取込/SUN | ✅ Found |
| 対帳単 | 対帳単生成/確認 | ✅ Found |
| 審批 | 付款申請審批 | ✅ Found |
| 付款申請 | 付款申請創建 | ✅ Found |
| 審批 | 審批 (approval step) | ✅ Found |
| 支付 | GL記帳/支付 | ✅ Found |
| 報表 | 報表出力 | ✅ Found |

## Assessment

The Q4 semantic map preview successfully:
1. ✅ Contains at least one continuous path A→B→C→D (8 nodes)
2. ✅ Maps to all 7 expected business steps
3. ✅ Only uses allowed Q4 relation types (generates, depends_on, relates_to)
4. ✅ Connects business, system, and data layers

## R7 Normalization Tasks

1. Consolidate duplicate business step nodes (e.g., "審批" appears multiple times)
2. Reduce 286 nodes to canonical semantic map (~30-50 core nodes)
3. Prune tangential edges not on the main flow path
4. Establish clear layer separation in final visualization
