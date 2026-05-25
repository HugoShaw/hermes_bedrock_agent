# QA Answer — q3

**Question:** SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三张表之间，在没有外键的情况下：
1. 通过哪些字段形成关联
2. 这些关联在代码中是如何体现的，如 SQL 或 Mapper
3. 在业务流程中的数据流转路径

**Timestamp:** 2026-05-18T06:46:17.958013

---

# SUN_REQUEST、JOURNAL_BASE、RECEIVING_JOURNAL 三表关联分析

---

## 1. 关联字段定义

三表之间通过 `OTHER_SYSTEM_NO` 字段形成关联链路，但匹配方式不同：

### 关联1：JOURNAL_BASE ↔ RECEIVING_JOURNAL（精确匹配）

| 表 | 字段 | 类型 | 角色 |
|---|---|---|---|
| JOURNAL_BASE | `OTHER_SYSTEM_NO` | VARCHAR2(20), PK | 外部MS系统传入的原始交易号 |
| RECEIVING_JOURNAL | `OTHER_SYSTEM_NO` | VARCHAR2(20) | 引用上述交易号 |

```sql
JOIN RECEIVING_JOURNAL rj ON jb.OTHER_SYSTEM_NO = rj.OTHER_SYSTEM_NO
```
> 来源：文档证据1、证据3

---

### 关联2：SUN_REQUEST ↔ RECEIVING_JOURNAL（子串匹配）

| 表 | 字段 | 类型 | 角色 |
|---|---|---|---|
| SUN_REQUEST | `OTHER_SYSTEM_NO` | VARCHAR2(20), PK | GL传票号（系统生成） |
| RECEIVING_JOURNAL | `OTHER_SYSTEM_NO` | VARCHAR2(20) | 原始交易号（来自MS系统） |

```sql
LEFT JOIN RECEIVING_JOURNAL RJ
  ON SUBSTR(RJ.OTHER_SYSTEM_NO, 0, 12) = SUBSTR(SR.OTHER_SYSTEM_NO, 0, 12)
```

**为何用 SUBSTR 而非精确匹配？**
- `SUN_REQUEST.OTHER_SYSTEM_NO` 是付款申请审批通过后由系统生成的 **GL传票号**
- `RECEIVING_JOURNAL.OTHER_SYSTEM_NO` 是来自 MS 系统的 **原始交易号**
- 两者共享**前12位前缀**（设计约定），后续位数不同
- 这是一种"软关联"设计模式，无物理外键约束
> 来源：文档证据1、证据3

---

### 关联3：JOURNAL_BASE ↔ SUN_REQUEST（间接，无直接字段）

```
JOURNAL_BASE.OTHER_SYSTEM_NO
    → (精确匹配) → RECEIVING_JOURNAL.OTHER_SYSTEM_NO
    → (SUBSTR前12位) → SUN_REQUEST.OTHER_SYSTEM_NO
```

两者**没有直接关联字段**，必须以 `RECEIVING_JOURNAL` 作为桥接中转。
> 来源：文档证据1、证据3

---

## 2. 代码层面的体现

### 2.1 SQL 层（PaymentReqAction.countCalculate()）

这是**唯一需要跨越三表**的业务场景，用于计算付款申请的 `O_VAT`（已有消費税）：

```sql
-- 来源：文档证据1、证据3
SELECT SUM(SR.TRANSACTION_AMOUNT)
FROM SUN_REQUEST SR
LEFT JOIN RECEIVING_JOURNAL RJ
    ON SUBSTR(RJ.OTHER_SYSTEM_NO, 0, 12) = SUBSTR(SR.OTHER_SYSTEM_NO, 0, 12)
WHERE SR.ACCOUNT_CODE = '04991'        -- 消費税差额科目
  AND RJ.PAY_NO IN (...)               -- 限定对账单范围
```

完整三表链路查询（通过视图）：
```sql
-- 来源：文档证据4（V_PAYMENT_RECEIVING视图）
JOURNAL_BASE jb
  JOIN RECEIVING_JOURNAL rj ON jb.OTHER_SYSTEM_NO = rj.OTHER_SYSTEM_NO
  JOIN RECEIVING_LIST    rl ON rj.PAY_NO = rl.PAY_NO
  -- SUN_REQUEST通过SUBSTR在countCalculate中单独关联
```

> ⚠️ SUBSTR函数操作导致**索引失效**，当前数据量（SUN_REQUEST ~1000行，RECEIVING_JOURNAL ~2000行）尚可接受；若数据增长，建议创建函数索引：
> ```sql
> CREATE INDEX IDX_RJ_SUBSTR ON RECEIVING_JOURNAL(SUBSTR(OTHER_SYSTEM_NO, 1, 12));
> CREATE INDEX IDX_SR_SUBSTR ON SUN_REQUEST(SUBSTR(OTHER_SYSTEM_NO, 1, 12));
> ```

### 2.2 Java Mapper / HQL 层

**RECEIVING_JOURNAL Entity（ReceivingJournal.java）**
```java
// 来源：文档证据2
@Entity @Table(name="RECEIVING_JOURNAL")
public class ReceivingJournal extends BaseEntity {
    @Id private String pk;
    private String payNo;           // → PAY_NO (FK → RECEIVING_LIST)
    private String otherSystemNo;   // → OTHER_SYSTEM_NO (FK → JOURNAL_BASE)
    private String transactionReference;
}
```

**关键 HQL 查询**
```java
// 来源：文档证据2
// 防重复检查（关联到JOURNAL_BASE前验证）
"FROM ReceivingJournal WHERE otherSystemNo IN (:ids)"

// 按对账单查询已关联的JOURNAL_BASE记录
"FROM ReceivingJournal WHERE payNo = :payNo AND delFlg = '0'"

// 逻辑删除（释放JOURNAL_BASE锁定）
"UPDATE ReceivingJournal SET delFlg='1' WHERE payNo IN (:payNos)"
```

**关联写入代码（ReceigIngServiceImpl.saveReceivingList()）**
```java
// 来源：文档证据1
rj.setOtherSystemNo(jb.getOtherSystemNo());  // 建立 RJ → JB 的关联
```

---

## 3. 业务流程数据流转路径

```
┌─────────────────────────────────────────────────────────────────────┐
│ 外部MS系统 →(HULFT文件传输)→ JOURNAL_BASE                           │
│   LIST_TYPE='0', CPL_MK='8'                                         │
│   OTHER_SYSTEM_NO = "原始交易号"（12位前缀+后缀）                   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ ① 用户在Receiving画面选择记录
                           │   条件：CPL_MK='8' AND LIST_TYPE='0'
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ RECEIVING_JOURNAL（桥接表）                                         │
│   OTHER_SYSTEM_NO = JOURNAL_BASE.OTHER_SYSTEM_NO  ← 精确写入       │
│   PAY_NO          = 新生成的对账单号                                │
│   同时：JOURNAL_BASE.LIST_TYPE → '1'（锁定，防重复选入）            │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ ② 对账单生成→付款申请→审批通过
                           │   PAYMENT_REQ.STATUS → 3（承认完了）
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│ SUN_REQUEST（GL总账传票）                                           │
│   OTHER_SYSTEM_NO = "GL传票号"（前12位与原始交易号相同）            │
│   ACCOUNT_CODE = '04991'（消費税差额分录）                          │
│   → 通过HULFT传输到SUN ERP完成总账记账                             │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ ③ 反查（countCalculate追溯O_VAT）
                           │   SUBSTR(SR.OTHER_SYSTEM_NO,0,12)
                           │   = SUBSTR(RJ.OTHER_SYSTEM_NO,0,12)
                           ▼
                    回溯至 RECEIVING_JOURNAL → JOURNAL_BASE
```

### 完整数据流转路径（文字版）

| 阶段 | 操作 | 涉及表 | 关键状态变化 |
|---|---|---|---|
| **①导入** | MS系统→HULFT→系统 | `JOURNAL_BASE` | `LIST_TYPE=0`, `CPL_MK=8` |
| **②分组** | 用户选择记录生成对账单 | `JOURNAL_BASE` → `RECEIVING_JOURNAL` → `RECEIVING_LIST` | `LIST_TYPE: 0→1` |
| **③申请** | 对账单纳入付款申请 | `RECEIVING_LIST` → `PAYMENT_RECEIVING` → `PAYMENT_REQ` | `STATUS: 1→0`(RL锁定) |
| **④审批** | 审批流程 | `PAYMENT_REQ` | `STATUS: 2→3` |
| **⑤记账** | 生成GL分录 | `PAYMENT_REQ` → `SUN_REQUEST` | OTHER_SYSTEM_NO前12位继承 |
| **⑥追溯** | 计算O_VAT | `SUN_REQUEST` ←SUBSTR→ `RECEIVING_JOURNAL` | 唯一跨三表查询场景 |

> 来源：文档证据3、证据6

---

## 总结

```
JOURNAL_BASE ←──精确匹配 OTHER_SYSTEM_NO──→ RECEIVING_JOURNAL ←──SUBSTR前12位──→ SUN_REQUEST
    (数据源头/原始交易)              (桥接枢纽)                           (GL总账分录)
```

`RECEIVING_JOURNAL` 是整个系统的**数据枢纽**：
- 向左通过精确匹配连接 `JOURNAL_BASE`（采购明细）
- 向右通过子串匹配连接 `SUN_REQUEST`（GL分录）
- 实现了"从GL传票反向追溯到原始采购交易"的唯一跨模块路径
