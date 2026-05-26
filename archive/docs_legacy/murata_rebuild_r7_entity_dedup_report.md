# R7 Entity Dedup Report

## Summary

| Metric | Value |
|--------|-------|
| Raw entities | 859 |
| Canonical entities | 381 |
| Reduction | 55.6% (478 removed) |
| Merge groups | 143 (entities with support_count > 1) |
| Pending merges | 0 |
| Cross-type conflicts avoided | True |

---

## Dedup Strategy

Entities are merged when:
1. Same normalized slug (CamelCase/snake_case/UPPER normalization)
2. Same entity_type
3. Same inferred layer

Entities are **NOT** merged when:
- Different entity_type (Table ≠ Class ≠ Action ≠ Service)
- Different semantic layer (data ≠ system ≠ business)
- Ambiguous context

---

## Top 20 Merge Groups (by support_count)

| # | Canonical Name | Type | Support | Aliases |
|---|---------------|------|---------|---------|
| 1 | STATUS | Field | 15 | status |
| 2 | PAYMENT_REQ | Table | 13 | payment_req |
| 3 | BILL_NO | Column | 11 | bill_no |
| 4 | RECEIVING_LIST | Table | 10 | receiving_list |
| 5 | JOURNAL_BASE | Table | 9 | journal_base |
| 6 | PAYMENT_RECEIVING | Table | 8 | payment_receiving |
| 7 | SUN_REQUEST | Table | 8 | sun_request |
| 8 | PAY_NO | Field | 7 | pay_no |
| 9 | RECEIVING_JOURNAL | Table | 7 | receiving_journal |
| 10 | LIST_TYPE | Column | 6 | list_type |
| 11 | VENDOR_CD | Column | 6 | vendor_cd |
| 12 | 応付管理流程 | BusinessProcess | 5 | |
| 13 | APPROVAL_BY | Column | 5 | approval_by |
| 14 | APPROVAL_TIME | Column | 5 | approval_time |
| 15 | APPROVAL_REMARK | Column | 5 | approval_remark |
| 16 | PaymentReqAction | Action | 4 | |
| 17 | OTHER_SYSTEM_NO | Column | 4 | other_system_no |
| 18 | ACCOUNT_CODE | Column | 4 | account_code |
| 19 | 応付管理システム | System | 4 | |
| 20 | OA系統 | ExternalSystem | 3 | |

---

## Cross-Type Separation Examples

These entities share similar names but are kept separate due to different types:

| Slug | Types Preserved | Reason |
|------|----------------|--------|
| payment_req | Table, Action, Class, Status | Different implementation layers |
| journal_base | Table, Action, Class | Table ≠ Code artifact |
| receiving_journal | Table, Action | Schema vs code |
| sun_request | Table, Method | Data vs system |

---

## Pending Entity Merges

**0 pending merges.** All entity groups resolved deterministically.

---

## Conclusion

The dedup strategy is conservative and type-safe. No cross-type merges occurred. The most-merged entities (STATUS, PAYMENT_REQ, BILL_NO) are core domain concepts appearing across multiple source chunks — their merge is well-justified.
