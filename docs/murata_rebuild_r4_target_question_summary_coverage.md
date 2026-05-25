# Phase R4 — Target Question Summary Coverage Report

**Date**: 2026-05-15 07:18
**Run ID**: murata_rebuild_v1

---

## Original Target Questions

- **Q1**: 应付管理业务流程
- **Q2**: JOURNAL_BASE 表作用
- **Q3**: SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三表关联
- **Q4**: 应付管理完整业务流程 Semantic Map
- **Q5**: 付款申请审批迁移到 OA 的系统改造方案

---

## Coverage Matrix

### Q1: 应付管理业务流程

**Supporting summaries: 12**

| Summary ID | Type | Parent Chunks | Key Tables | Evidence |
|-----------|------|---------------|------------|----------|
| summary_r4_001 | code_summary | chunk_r3_013 | RECEIVING_LIST, RECEIVING_JOURNAL, JOURNAL_BASE | strong |
| summary_r4_002 | code_summary | chunk_r3_014 | RECEIVING_LIST, RECEIVING_JOURNAL, JOURNAL_BASE | strong |
| summary_r4_003 | code_summary | chunk_r3_015 | PAYMENT_REQ | strong |
| summary_r4_004 | code_summary | chunk_r3_017 | JOURNAL_BASE, RECEIVING_JOURNAL, RECEIVING_LIST, V_RECEIVING_LIST | strong |
| summary_r4_005 | code_summary | chunk_r3_018 | V_RECEIVING_LIST, RECEIVING_LIST, RECEIVING_JOURNAL, JOURNAL_BASE | strong |
| summary_r4_006 | code_summary | chunk_r3_031 | PAYMENT_REQ, PAYMENT_RECEIVING, RECEIVING_LIST | strong |
| summary_r4_007 | code_summary | chunk_r3_032 | JOURNAL_BASE | strong |
| summary_r4_008 | process_summary | chunk_r3_036 | JOURNAL_BASE, SUN_REQUEST | strong |
| summary_r4_009 | schema_summary | chunk_r3_037 | JOURNAL_BASE, RECEIVING_JOURNAL, RECEIVING_LIST, PAYMENT_RECEIVING | strong |
| summary_r4_010 | process_summary | chunk_r3_053 | JOURNAL_BASE, RECEIVING_LIST, RECEIVING_JOURNAL, PAYMENT_REQ | strong |
| summary_r4_011 | schema_summary | chunk_r3_055 | JOURNAL_BASE, RECEIVING_LIST, RECEIVING_JOURNAL, PAYMENT_REQ | strong |
| summary_r4_012 | semantic_map_summary | chunk_r3_053, chunk_r3_037 | JOURNAL_BASE, RECEIVING_LIST, RECEIVING_JOURNAL, PAYMENT_REQ | strong |

### Q2: JOURNAL_BASE 表作用

**Supporting summaries: 4**

| Summary ID | Type | Parent Chunks | Key Tables | Evidence |
|-----------|------|---------------|------------|----------|
| summary_r4_001 | code_summary | chunk_r3_013 | RECEIVING_LIST, RECEIVING_JOURNAL, JOURNAL_BASE | strong |
| summary_r4_007 | code_summary | chunk_r3_032 | JOURNAL_BASE | strong |
| summary_r4_009 | schema_summary | chunk_r3_037 | JOURNAL_BASE, RECEIVING_JOURNAL, RECEIVING_LIST, PAYMENT_RECEIVING | strong |
| summary_r4_011 | schema_summary | chunk_r3_055 | JOURNAL_BASE, RECEIVING_LIST, RECEIVING_JOURNAL, PAYMENT_REQ | strong |

### Q3: SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三表关联

**Supporting summaries: 2**

| Summary ID | Type | Parent Chunks | Key Tables | Evidence |
|-----------|------|---------------|------------|----------|
| summary_r4_009 | schema_summary | chunk_r3_037 | JOURNAL_BASE, RECEIVING_JOURNAL, RECEIVING_LIST, PAYMENT_RECEIVING | strong |
| summary_r4_011 | schema_summary | chunk_r3_055 | JOURNAL_BASE, RECEIVING_LIST, RECEIVING_JOURNAL, PAYMENT_REQ | strong |

### Q4: 应付管理完整业务流程 Semantic Map

**Supporting summaries: 11**

| Summary ID | Type | Parent Chunks | Key Tables | Evidence |
|-----------|------|---------------|------------|----------|
| summary_r4_001 | code_summary | chunk_r3_013 | RECEIVING_LIST, RECEIVING_JOURNAL, JOURNAL_BASE | strong |
| summary_r4_002 | code_summary | chunk_r3_014 | RECEIVING_LIST, RECEIVING_JOURNAL, JOURNAL_BASE | strong |
| summary_r4_003 | code_summary | chunk_r3_015 | PAYMENT_REQ | strong |
| summary_r4_004 | code_summary | chunk_r3_017 | JOURNAL_BASE, RECEIVING_JOURNAL, RECEIVING_LIST, V_RECEIVING_LIST | strong |
| summary_r4_005 | code_summary | chunk_r3_018 | V_RECEIVING_LIST, RECEIVING_LIST, RECEIVING_JOURNAL, JOURNAL_BASE | strong |
| summary_r4_006 | code_summary | chunk_r3_031 | PAYMENT_REQ, PAYMENT_RECEIVING, RECEIVING_LIST | strong |
| summary_r4_008 | process_summary | chunk_r3_036 | JOURNAL_BASE, SUN_REQUEST | strong |
| summary_r4_009 | schema_summary | chunk_r3_037 | JOURNAL_BASE, RECEIVING_JOURNAL, RECEIVING_LIST, PAYMENT_RECEIVING | strong |
| summary_r4_010 | process_summary | chunk_r3_053 | JOURNAL_BASE, RECEIVING_LIST, RECEIVING_JOURNAL, PAYMENT_REQ | strong |
| summary_r4_011 | schema_summary | chunk_r3_055 | JOURNAL_BASE, RECEIVING_LIST, RECEIVING_JOURNAL, PAYMENT_REQ | strong |
| summary_r4_012 | semantic_map_summary | chunk_r3_053, chunk_r3_037 | JOURNAL_BASE, RECEIVING_LIST, RECEIVING_JOURNAL, PAYMENT_REQ | strong |

### Q5: 付款申请审批迁移到 OA 的系统改造方案

**Supporting summaries: 5**

| Summary ID | Type | Parent Chunks | Key Tables | Evidence |
|-----------|------|---------------|------------|----------|
| summary_r4_003 | code_summary | chunk_r3_015 | PAYMENT_REQ | strong |
| summary_r4_006 | code_summary | chunk_r3_031 | PAYMENT_REQ, PAYMENT_RECEIVING, RECEIVING_LIST | strong |
| summary_r4_009 | schema_summary | chunk_r3_037 | JOURNAL_BASE, RECEIVING_JOURNAL, RECEIVING_LIST, PAYMENT_RECEIVING | strong |
| summary_r4_011 | schema_summary | chunk_r3_055 | JOURNAL_BASE, RECEIVING_LIST, RECEIVING_JOURNAL, PAYMENT_REQ | strong |
| summary_r4_013 | oa_migration_summary | chunk_r3_015, chunk_r3_031, chunk_r3_037 | PAYMENT_REQ, PAYMENT_RECEIVING, RECEIVING_LIST | strong |

---

## Q-Label Consistency Check

| Question | Original Definition | R3 Label Match | R4 Coverage |
|----------|--------------------:|:--------------:|:-----------:|
| Q1 | 应付管理业务流程 | ✅ Consistent | 12 summaries |
| Q2 | JOURNAL_BASE 表作用 | ✅ Consistent | 4 summaries |
| Q3 | SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三表关联 | ✅ Consistent | 2 summaries |
| Q4 | 应付管理完整业务流程 Semantic Map | ✅ Consistent | 11 summaries |
| Q5 | 付款申请审批迁移到 OA 的系统改造方案 | ✅ Consistent | 5 summaries |

**Conclusion**: All R3 question labels are consistent with original Q1-Q5 definitions. No mismatch detected.

---

## Coverage Adequacy Assessment

| Question | Min Required | Actual | Assessment |
|----------|:----------:|:------:|:-----------|
| Q1 | 1 | 12 | Strong |
| Q2 | 1 | 4 | Adequate |
| Q3 | 1 | 2 | Adequate |
| Q4 | 1 | 11 | Strong |
| Q5 | 1 | 5 | Strong |

---

## Specialized Summaries

### semantic_map_summary (summary_r4_012)

- **Purpose**: Full AP process chain node/edge extraction for Q4 Semantic Map construction
- **Nodes extracted**: 20
- **Edges extracted**: 25
- **Process chain path**: ['data_import', 'reconciliation_gen', 'payment_req_create', 'approval', 'gl_payment', 'report_gen']

### oa_migration_summary (summary_r4_013)

- **Purpose**: Q5 OA approval migration impact analysis
- **Tables impacted**: ['PAYMENT_REQ', 'PAYMENT_RECEIVING', 'RECEIVING_LIST']
- **Modules to modify**: ['PaymentReqAction', 'PaymentReqServiceImpl', 'PaymentReqService']
- **API candidates**: 3
