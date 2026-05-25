# R9 Sample Readback Validation Report

## Node Readback

| Check | Result |
|-------|--------|
| Expected node count | 20 |
| Actual node count | 20 ✅ |
| Sample nodes readable | YES (10 sampled) ✅ |
| entity_id property | Present ✅ |
| run_id property | Present (murata_rebuild_v1) ✅ |
| dataset property | Present (murata) ✅ |
| canonical_name property | Present ✅ |
| Labels correctly assigned | YES (10 distinct labels) ✅ |

---

## Edge Readback

| Check | Result |
|-------|--------|
| Expected edges (both endpoints in sample) | 10 |
| Actual edge count | 10 ✅ |
| Sample edges readable | YES (10 sampled) ✅ |
| relation_id property | Present ✅ |
| run_id property | Present (murata_rebuild_v1) ✅ |
| dataset property | Present (murata) ✅ |
| relation_type property | Present ✅ |
| Edge labels correct | YES (DEPENDS_ON, CALLS, HAS_STATUS, etc.) ✅ |

---

## Labels Found in Sample

| Label | Count |
|-------|-------|
| API | 2 |
| Action | 2 |
| BusinessObject | 2 |
| BusinessProcess | 2 |
| BusinessStep | 2 |
| Class | 2 |
| Column | 2 |
| EnumValue | 2 |
| ExternalSystem | 2 |
| Field | 2 |

---

## Key Entity Readback

| Entity | Found | Node ID |
|--------|-------|---------|
| JOURNAL_BASE | ✅ | ent_system_action_journal_base_action |
| PAYMENT_REQ | ✅ | ent_system_action_payment_req_action |
| PaymentReq (BusinessObject) | ✅ | ent_business_business_object_payment_req |

---

## Path Readback

| Path Type | Found | Count |
|-----------|-------|-------|
| 2-hop (A→B→C) | ✅ | 7 paths |
| Variable-length [*1..3] | ✅ | 10 paths (supported) |

Example 2-hop path:
```
API:post_apioaapproval → CALLS → ExternalSystem:oa系統 → CALLS → API:post_apioaapproval
```

---

## Conclusion

All readback validations PASS. Properties are fully preserved, labels are correct, and graph traversal queries work as expected.
