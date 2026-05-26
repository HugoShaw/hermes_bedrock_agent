# Process Chain Evidence Report — Phase R2.5

**Date:** 2026-05-15
**Run ID:** murata_rebuild_v1
**Sources:** 3 HIGH-priority VLM files + text-extracted code/SQL from R2

---

## Business Process Chain: End-to-End Payment Workflow

The Murata MDW payment system follows this chain:

```
外部系统(MS/SUN) → JOURNAL_BASE → RECEIVING_LIST → PAYMENT_REQ → 审批 → 支付
```

### Chain Coverage by Source

| Chain Stage | Excel (村田.xlsx) | PPTX (MDW支払依頼) | DOCX (操作手册) | Combined |
|-------------|-------------------|---------------------|-----------------|----------|
| 订単/Purchase | ✅ JOURNAL_BASE DDL | ✅ MS→SUN flow | ⬜ (implicit) | **COVERED** |
| 对账単/Receiving | ✅ RECEIVING_LIST DDL | ✅ Receiving List creation flow | ✅ Full UI workflow | **COVERED** |
| 关联/Join | ✅ RECEIVING_JOURNAL DDL | ✅ Join keys documented | ⬜ (implicit) | **COVERED** |
| 付款申請/Payment Req | ✅ PAYMENT_REQ DDL | ✅ Payment Request flow | ✅ Create/Submit/Cancel UI | **COVERED** |
| 審批/Approval | ✅ STATUS 1-5, APPROVAL_* fields | ✅ OK/NG flow | ✅ Manage module UI | **COVERED** |
| 支付/Payment | ⬜ (table link only) | ✅ Payment voucher to SUN | ⬜ (Payment List query) | **PARTIAL** |
| 報表/Reporting | ⬜ | ⬜ | ✅ Excel export, Payment List | **PARTIAL** |

---

## Detailed Process Steps (Merged from 3 Sources)

### Step 1: External Data Import (MS Purchase → JOURNAL_BASE)

**Source:** Excel (DDL) + PPTX (slide 3, 9, 17)

- MS Purchase system generates debit records (Request1)
- SUN system generates credit records (Request2)  
- HULFT interface transfers data into JOURNAL_BASE table
- Key fields: OTHER_SYSTEM_NO, TRANSACTION_REFERENCE, ACCOUNTING_DATE, TRANSACTION_AMOUNT
- Processing status: CPL_MK (0=未完成, 1=已完成)
- LIST_TYPE (0=UnIssued, 1=Issued)

### Step 2: Receiving List Generation (JOURNAL_BASE → RECEIVING_LIST)

**Source:** Excel (RECEIVING_LIST DDL) + PPTX (slide 9-10) + DOCX (step 1-3)

- User searches by Vendor Cd, selects UnIssued records
- System groups by Vendor + Currency + VAT rate
- Generates PAY_NO (payment number) for the receiving list
- Join: RECEIVING_JOURNAL links JOURNAL_BASE.OTHER_SYSTEM_NO → RECEIVING_LIST.PAY_NO
- Output: RECEIVING_LIST record with TOTAL_AMT, STATUS=1(editable)
- User can download Receiving List PDF

### Step 3: Request1 & Request2 Merge (Debit/Credit Reconciliation)

**Source:** PPTX (slides 3, 4, 9, 10)

- Request1 (Debit/借方): All data from MS
- Request2 (Credit/貸方): Data where Allocation_Marker = "1"
- Join keys:
  - Business_Connection (Vendor Code)
  - Transaction_Reference (送貨単No/Invoice No)
- Additional join with 資材記録E (ME0039):
  - 注文No (PO No)
  - Invoice No
  - Transaction_Date
- Output: Combined journal base with matched debit/credit pairs

### Step 4: Payment Request Creation

**Source:** Excel (PAYMENT_REQ DDL) + PPTX (slide 6, 14) + DOCX (step 4-5)

- User selects receiving lists (by PAY_NO range) in Payment Request module
- System generates BILL_NO (invoice number)
- PAYMENT_RECEIVING links PAYMENT_REQ.BILL_NO → RECEIVING_LIST.PAY_NO
- Financial fields calculated:
  - O_VAT / N_VAT (old/new tax amount)
  - O_TOTAL_AMT / N_TOTAL_AMT (old/new total)
  - VAT_EXCLUDED (tax-excluded amount)
  - MS_TOTAL (MS calculated amount)
  - DIFFERENCE = MS_TOTAL - N_TOTAL_AMT
  - DISCOUNT = DIFFERENCE / MS_TOTAL (percentage)
- Initial STATUS = 1 (編辑中/暂存)

### Step 5: Payment Request Submission & Approval

**Source:** Excel (STATUS field) + PPTX (slide 8) + DOCX (steps 7-8)

- Submitter changes STATUS: 1 → 2 (等待承认/确認中)
- Approver sees request in Payment_Request_Manage module
- Approval actions:
  - OK → STATUS = 3 (承認完了/已确认)
  - Cancel → STATUS = 4 (承認却下/拒绝)
  - Delete → STATUS = 5 (承認取消) or 6 (削除)
- Approval fields: APPROVAL_BY, APPROVAL_TIME, APPROVAL_REMARK

### Step 6: VAT Adjustment & Payment Voucher

**Source:** PPTX (slides 17-21)

- After approval, system issues VAT adjustment voucher:
  - Compare 増値税発票 (official VAT invoice) vs Receiving List tax
  - Issue voucher for difference (account 04991)
- Create update data for original SUN Ledger
- Issue payment voucher to SUN
- Transaction matching (TRM) in SUN batch:
  - Allocation Marker set to "A" when debit/credit matched
  - Matching key: 増値税発票No or Invoice No

### Step 7: Payment List Query & Export

**Source:** DOCX (steps 9-10)

- Users query Payment List by: Date, Vendor Cd, Status, Applicant
- Export to Excel for reporting
- Status filtering shows full lifecycle

---

## Three-Table Join Chain (Q3 Evidence)

```
JOURNAL_BASE (OTHER_SYSTEM_NO)
    ↓ via RECEIVING_JOURNAL (PAY_NO + OTHER_SYSTEM_NO)
RECEIVING_LIST (PAY_NO)
    ↓ via PAYMENT_RECEIVING (BILL_NO + PAY_NO)  
PAYMENT_REQ (BILL_NO)
```

**No traditional foreign keys** — relationships established through:
1. `RECEIVING_JOURNAL` bridge table (PK, PAY_NO, OTHER_SYSTEM_NO)
2. `PAYMENT_RECEIVING` bridge table (PK, BILL_NO, PAY_NO)

**View evidence (from R2 SQL analysis):**
- `V_PAYMENT_REQ_FILE` joins all 4 tables
- `V_PAYMENT_RECEIVING` provides receiving+payment view

---

## Target Question Evidence Matrix (Updated with VLM Data)

| Question | Pre-VLM (R2) | Post-VLM (R2.5) | Improvement |
|----------|--------------|-----------------|-------------|
| Q1: 付款申请审批流程 | Strong (SQL+Code) | **Strong+** (Flow diagrams + UI screenshots + STATUS machine) | +Process diagrams, screen flows |
| Q2: 差异对账逻辑 | Strong (SQL fields) | **Strong+** (VAT calculation logic from PPTX) | +VAT adjustment steps |
| Q3: 三表关联 | Strong (Views+DDL) | **Strong** (Excel confirms join keys) | Confirmed, no new data |
| Q4: 数据字典 | Medium (partial) | **Strong** (Full HULFT_DICT structure + enum values) | +Complete enum mappings |
| Q5: 报表/时间分析 | Medium (time fields) | **Medium+** (Export workflow + Payment List) | +Export flow documented |

---

## Key Entities Discovered via VLM

### Systems
- SUN (SunSystems) — General ledger, transaction matching
- MS (資材記録E/ME0039) — Purchase/procurement system
- iMaps — MDW payment request application
- HULFT — Data transfer middleware

### Processes
- Receiving List generation (PRSG0251)
- Payment Request (PRSG0250)
- VAT voucher issuance
- Transaction Matching (TRM) batch
- SUN Outbound I/F2 (TRD)

### Key Business Rules
- Allocation Marker = "1" → eligible for payment
- Allocation Marker = "A" → matched (TRM complete)
- Account code starting with "V" + Vendor code format
- Journal Type = "MP1" for payment requests
- Account code starting with "6" → extracted for debit

---

## Confidence Assessment

| File | Extraction Quality | Business Value | Recommended for R3 |
|------|-------------------|----------------|---------------------|
| 村田.xlsx | High (full text extraction, VLM validated) | Critical — complete DDL with semantics | ✅ Include as structured evidence |
| MDW支払依頼_V3.1.pptx | High (flow diagrams + text from 31 slides) | Critical — end-to-end process flow | ✅ Include as visual evidence |
| 操作手册.docx | High (63 screenshots + user workflow) | High — UI field descriptions + workflows | ✅ Include as visual evidence |
