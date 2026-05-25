# R10 Graph Query Validation Report

## Key Entity Queries

| Entity | Found | Count | Labels |
|--------|-------|-------|--------|
| JOURNAL_BASE | ✅ | 5+ | Table, Class, Action |
| PAYMENT_REQ | ✅ | 5+ | Action, Method, Module, BusinessObject, Status |
| SUN_REQUEST | ✅ | 5+ | Table, View, BusinessObject |
| RECEIVING_JOURNAL | ✅ | 5+ | Table, Method |

All 4 key entities found with multiple related nodes.

## Neighbor Queries

### JOURNAL_BASE (Table) — 30 neighbors

Key connections:
- has_field → CPL_MK, OTHER_SYSTEM_NO, VENDOR_CD, ALLOCATION_MARKER...
- contains → CPL_MK, VENDOR_CD, CURRENCY_CODE, TAX_RATE...
- supports → Receiving List生成
- relates_to → RECEIVING_LIST
- joins_on → RECEIVING_JOURNAL
- references → RECEIVING_JOURNAL
- writes_to → saveReceivingList

### PaymentReqAction — 25 neighbors

Key connections:
- contains → updateByBillNos, countCalculate, findReceivingList...
- DEPENDS_ON → BaseAction
- references → PaymentReq

### Payment Request Module — 5 neighbors

Key connections:
- generates → Payment Request
- reads_from → Reconciliation Statement
- supports → Payment Request Step, 付款申请创建
- contains → iMaps

## Q3 Three-Table Path Validation ✅

| Check | Result |
|-------|--------|
| SUN_REQUEST table exists | ✅ |
| JOURNAL_BASE table exists | ✅ |
| RECEIVING_JOURNAL table exists | ✅ |
| SUN_REQUEST ↔ JOURNAL_BASE paths | 10 paths (direct + 2-hop) ✅ |
| JOURNAL_BASE ↔ RECEIVING connections | 10 connections ✅ |

Key paths discovered:
- SUN_REQUEST → JOURNAL_BASE (direct, len=1)
- SUN_REQUEST ↔ JOURNAL_BASE (2-hop, len=2)
- JOURNAL_BASE —[joins_on]→ RECEIVING_JOURNAL
- JOURNAL_BASE —[references]→ RECEIVING_JOURNAL
- JOURNAL_BASE —[relates_to]→ RECEIVING_LIST
- JOURNAL_BASE —[supports]→ Receiving List生成

## Q4 Business Flow Path Validation ✅

| Check | Result |
|-------|--------|
| AP business nodes | 30+ found |
| BusinessProcess/Step nodes | 30+ found |
| flows_to paths | 20+ paths found |
| flows_to total edges | 50 |
| calls edges | 41 |
| generates edges | 34 |
| supports edges | 26 |

Key business processes found:
- 付款申请审批流程 (Payment Request Approval Flow)
- 応付管理流程 (AP Management Flow)
- 应付管理 (AP Management)
- Receiving List生成

Key business steps:
- 審批流程, GL记账, 報表出力, 対账単分組, 検収, 承認

flows_to paths:
- 付款申请审批流程 → SUN ERP
- SUN_REQUEST → SUN ERP, HULFT
- GL伝票作成 → SUN
- GL记账 → 报表输出
- HULFT → SUN ERP, iMaps

## Q5 OA Migration Validation ✅

| Check | Result |
|-------|--------|
| OA-related nodes | 15 found |
| Approval fields/statuses | 30 found |
| OA API endpoints | 2 found |
| OA system neighbors | 14 connections |

OA entities discovered:
- OA系統 (ExternalSystem)
- OA回调接口 (Interface)
- OA推送接口 (Interface)
- OA审批 (BusinessStep)
- OA流程跟踪字段 (Field)
- POST /api/oa/approval/callback (API)
- POST /api/oa/approval/submit (API)
- 创建申请并推送OA (BusinessStep)
- OA回调更新状态 (BusinessStep)

OA system connections:
- OA系統 —[CALLS]→ approval/callback API
- OA系統 —[CALLS]→ approval/submit API
- OA系統 —[calls]→ OA回调接口
- OA系統 —[supports]→ 审批
- OA回调接口 —[updates]→ PAYMENT_REQ table
- OA推送接口 —[calls]→ OA系統

## Summary

All 5 query categories (key entities, neighbors, Q3, Q4, Q5) passed validation.
The full graph supports the required business domain queries.
