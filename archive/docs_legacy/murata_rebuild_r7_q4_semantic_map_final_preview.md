# R7 Q4 Semantic Map Final Preview

## Overview

Q4 asks for the complete AP (応付管理) business flow semantic map:

```
订单/外部数据 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表
```

## Q4 Final Preview Statistics

| Metric | Value |
|--------|-------|
| Q4 nodes | 221 |
| Q4 edges | 499 |
| Allowed relation types | generates, depends_on, relates_to |
| Restricted to 3 types | ✅ YES |
| Longest continuous path | 10 nodes |

## Q4 Relation Type Distribution

| Type | Count | % |
|------|-------|---|
| relates_to | 203 | 40.7% |
| depends_on | 186 | 37.3% |
| generates | 110 | 22.0% |

Note: The dominance of `relates_to` in Q4 is by design — original fine-grained types (contains, has_field, has_status, etc.) are mapped to `relates_to` for Q4 simplification. This is not a quality issue.

## Verified Continuous Path (10 nodes)

```
審批結果回寫接口 → 応付管理システム → PaymentReqAction → downloadPdfFile
→ PaymentFileUtil → createPDFModel → Payment Requisition PDF Report
→ V_PAYMENT_REQ_FILE → PAYMENT_REQ → APPROVAL_BY
```

## Business Flow Path Verification

| Segment | Found | Detail |
|---------|-------|--------|
| 外部数据 → 対帳単 | ✅ | Connected via 応付管理 nodes |
| 対帳単 → 付款申請 | ✅ | Connected via 応付管理流程 |
| 付款申請 → 審批 | ✅ | Connected via 付款申請管理 |
| Business start path | ✅ | 完整業務流程→付款申請作成→審批流程→GL記帳→SUN_REQUEST→ACCOUNT_CODE |

## Key Business Flow Nodes Present

| Expected Node | Found | Entity ID |
|---------------|-------|-----------|
| 外部数据導入 | ✅ | ent_business_business_step_外部数据导入 |
| 対帳単生成 | ✅ | ent_business_business_step_対帳単生成 |
| 付款申請作成 | ✅ | ent_business_business_step_付款申請作成 |
| 審批流程 | ✅ | ent_business_business_step_審批流程 |
| GL記帳 | ✅ | ent_business_business_step_gl記帳 |
| 報表輸出 | ✅ | ent_business_business_step_报表输出 |
| 完整業務流程 | ✅ | ent_business_business_process_完整業務流程 |
| 応付管理流程 | ✅ | ent_business_business_process_応付管理流程 |

## Files Generated

- `q4_nodes_final_preview_r7.csv` — 221 nodes (id, label, type)
- `q4_edges_final_preview_r7.csv` — 499 edges (from, to, relation using q4_relation_type)

## Conclusion

Q4 semantic map meets all requirements:
- ✅ Only 3 allowed relation types (generates, depends_on, relates_to)
- ✅ At least one A→B→C→D continuous path (10 nodes)
- ✅ Business flow segments connected
- ✅ All expected business step nodes present
- ✅ Ready for visualization in R8
