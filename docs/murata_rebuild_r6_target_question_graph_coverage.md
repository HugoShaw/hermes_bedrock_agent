# R6 Target Question Graph Coverage Report

## Overview

All 5 target questions achieved **full graph coverage** from the R6 extraction.

## Coverage Matrix

| Question | Entities | Relations | Evidence | Level |
|----------|----------|-----------|----------|-------|
| Q1 (応付管理業務流程) | 286 | 1,613 | 113 | Full ✅ |
| Q2 (JOURNAL_BASE作用) | 106 | 574 | 39 | Full ✅ |
| Q3 (三表関連) | 114 | 619 | 40 | Full ✅ |
| Q4 (Semantic Map) | 207 | 1,488 | 93 | Full ✅ |
| Q5 (OA迁移) | 140 | 971 | 49 | Full ✅ |

## Q1: 応付管理業務流程

**Coverage**: Full (286 entities covering business steps, tables, code modules)

Key entities found:
- BusinessProcess: 対帳単処理, 付款申請処理, 支払処理
- BusinessStep: 外部データ取込, 対帳単生成, 審批, 付款申請, 支払実行
- Table: JOURNAL_BASE, RECEIVING_JOURNAL, PAYMENT_REQ, SUN_REQUEST
- Action: ReceivingJournalAction, PaymentReqAction, JournalBaseAction
- Service: ReceivingJournalService, PaymentReqService

## Q2: JOURNAL_BASE表の作用

**Coverage**: Full (106 entities, JOURNAL_BASE explicitly present ✅)

Key findings:
- JOURNAL_BASE table structure with columns (BILL_NO, OTHER_SYSTEM_NO, VENDOR_CD, etc.)
- Service layer: JournalBaseService, JournalBaseServiceImpl
- Action: JournalBaseAction
- DAO: JournalBaseDAO
- Related tables: RECEIVING_JOURNAL, RECEIVING_LIST

## Q3: SUN_REQUEST/JOURNAL_BASE/RECEIVING_JOURNAL三表関連

**Coverage**: Full (114 entities)

- **SUN_REQUEST**: ✅ Present
- **JOURNAL_BASE**: ✅ Present
- **RECEIVING_JOURNAL**: ✅ Present

Key join fields extracted:
- OTHER_SYSTEM_NO (SUN_REQUEST ↔ JOURNAL_BASE)
- BILL_NO (JOURNAL_BASE ↔ RECEIVING_JOURNAL)
- PAY_NO, LIST_TYPE (cross-table references)

## Q4: Semantic Map 完整業務流程

**Coverage**: Full (207 entities, continuous path confirmed)

Continuous path found (8 nodes):
```
外部数据导入 → 対帳単生成 → 付款申請創建 → 審批 → GL記帳/支付 → SUN_REQUEST → HULFT → SUN ERP
```

Q4 preview CSV:
- nodes_r6_q4_preview.csv: 286 nodes
- edges_r6_q4_preview.csv: 149 edges (restricted to generates/depends_on/relates_to)

## Q5: OA迁移流程

**Coverage**: Full (140 entities)

- **PAYMENT_REQ**: ✅ Present (payment request table)
- **OA/審批 nodes**: ✅ Present (OA system, approval workflow)
- Proposed design nodes marked with `proposed_design: true`
- Migration entities: API interfaces, approval status fields, OA system integration

## Quality Assessment

| Gate | Status |
|------|--------|
| Q1 partial coverage | ✅ Full (286E) |
| Q2 includes JOURNAL_BASE | ✅ |
| Q3 includes all 3 tables | ✅ |
| Q4 continuous path A→B→C→D | ✅ (8 nodes) |
| Q5 includes PAYMENT_REQ + OA | ✅ |
