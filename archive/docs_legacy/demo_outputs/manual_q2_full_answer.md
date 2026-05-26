# QA Answer — q2

**Question:** JOURNAL_BASE 表在系统中的作用是什么？
请结合：
1. 表结构
2. 相关业务流程
3. 调用该表的代码模块进行说明

**Timestamp:** 2026-05-18T06:43:29.254623

---

# JOURNAL_BASE 表综合分析

## 1. 表结构

基于文档证据2，JOURNAL_BASE 共有 **31 个字段**，主键为 `OTHER_SYSTEM_NO`（外部系统号），核心字段如下：

| 字段名 | 类型 | 业务含义 |
|--------|------|----------|
| `OTHER_SYSTEM_NO` | VARCHAR2(20) **PK** | 外部系统唯一标识，来自 MS 系材系统 |
| `LIST_TYPE` | VARCHAR2(2) | **状态控制核心**：`0`=未生成对账单（可选），`1`=已生成对账单（锁定） |
| `CPL_MK` | VARCHAR2(5) | **完了标记**：`8`=検収完了，是进入对账单流程的前提条件 |
| `VENDOR_CD` | VARCHAR2(20) | 供应商编码，查询过滤与分组依据 |
| `ID_NO1_CODE` | VARCHAR2(30) | PO No.（采购订单号） |
| `TRANSACTION_AMOUNT` | VARCHAR2(20) | 交易金额，汇总计算基础 |
| `TAX_RATE` | VARCHAR2(10) | 税率 / 贸易类型代码 |
| `TRANSACTION_DATE` | TIMESTAMP | 交易日期（Slip Date） |
| `ACCOUNTING_DATE` | TIMESTAMP | 検収日 / 会计日期 |
| `CURRENCY_CODE` | VARCHAR2(5) | 币种 |

### 状态机模型

```
外部MS系统推送
      ↓
 LIST_TYPE = '0'   ←──── delReceivingList()（从对账单释放）
  (可被选择)                         ↑
      ↓  saveReceivingList()         │
 LIST_TYPE = '1'  ─────────────────→┘
  (已锁定/编入对账单)
```

> 来源：文档证据1、2

---

## 2. 业务流程中的角色

JOURNAL_BASE 是**整个 MDW 应付支付系统的数据源头**，处于业务链路的最上游：

```
外部MS系统
    ↓ HULFT文件传输
JOURNAL_BASE（原始采购/收货台账）
    ↓ 用户在 Receiving 画面选择记录（CPL_MK='8' AND LIST_TYPE='0'）
RECEIVING_LIST（对账单，PAY_NO）
  + RECEIVING_JOURNAL（桥接表）
    ↓
PAYMENT_REQ（付款申请，BILL_NO）
    ↓ 审批通过
SUN_REQUEST（GL 会计分录）
    ↓
SUN ERP 总账系统
```

### 关键业务规则（文档证据10）

1. **进入对账单的双重前提**：`CPL_MK = '8'`（検収完了）且 `LIST_TYPE = '0'`（尚未被占用）
2. **同一对账单内一致性约束**：同一 `VENDOR_CD`、同一 `CURRENCY_CODE`、同一 `TAX_RATE`（在 Receiving 画面通过查询条件强制保证）
3. **事务原子性**：对账单生成时，`RECEIVING_LIST` + `RECEIVING_JOURNAL` + `JOURNAL_BASE.LIST_TYPE` 更新在同一事务内完成，任一失败全部回滚

> 来源：文档证据2、8、10

---

## 3. 调用该表的代码模块

### 3.1 JournalBaseAction.java（前端控制器）

> 来源：文档证据3、知识图谱

| 方法 | 功能 | 对 JOURNAL_BASE 的操作 |
|------|------|------------------------|
| `findReceigIngByParam()` | 查询可选的收货记录 | `READ`：过滤 `LIST_TYPE='0'`, `CPL_MK='8'`, `DEL_FLG='0'` |
| `findReceigConfirmSList()` | 获取用户选中记录进行确认 | `READ` |
| `registReceiving()` | 生成对账单 | 间接触发 `LIST_TYPE: 0→1` |
| `findReceIvingList()` | 查询已生成的对账单明细 | `READ`（通过 `V_BASE_LIST_JOURNAL` 视图） |

失败时执行 `callBack()` 回滚，物理删除 `RECEIVING_JOURNAL` 和 `RECEIVING_LIST`，并将 `LIST_TYPE` 恢复为 `'0'`。

### 3.2 JournalBaseServiceImpl.java（服务层）

> 来源：文档证据5

核心方法 `findJournalBaseList()`，使用 `HqlFilter` 动态查询框架：

```java
// 强制过滤条件（不可绕过）
hqlFilter.addFilter("QUERY_t#cplMk_S_EQ", "8");      // 検収完了
hqlFilter.addFilter("QUERY_t#listType_S_EQ", "0");    // 未选入对账单

// 可选查询条件
// VENDOR_CD / CURRENCY_CODE / BUYER_CODE
// ACCOUNTING_DATE（范围） / ID_NO1_CODE（范围） / TAX_RATE
```

### 3.3 ReceigIngServiceImpl.java（对账单生成服务）

> 来源：文档证据1、8

```java
// saveReceivingList() 中的状态变更
update JournalBase set listType = '1'   // 选入后锁定
// delReceivingList() 中的状态释放
update JournalBase set listType = '0'   // 删除对账单后解锁
```

### 3.4 视图层（4 个视图间接引用）

> 来源：文档证据4、6、9

| 视图 | JOIN 路径 | 用途 |
|------|-----------|------|
| `V_BASE_LIST_JOURNAL` | `JOURNAL_BASE` → `RECEIVING_JOURNAL` → `RECEIVING_LIST` | Receiving 画面 Unissued/Issued 列表 |
| `V_RECEIVING_LIST` | 同上 | 对账单明细展示 |
| `V_PAYMENT_RECEIVING` | 5表全链路（含 `PAYMENT_REQ`） | 付款申请全视图 |
| `V_PAYMENT_REQ_FILE` | 含 `PAYMENT_REQ` | 报表导出 |

### 3.5 PaymentReqAction.java（付款申请，间接引用）

> 来源：文档证据6、8

在 `countCalculate()` 方法中通过 SUBSTR 子串匹配跨表追溯：

```sql
LEFT JOIN RECEIVING_JOURNAL RJ
  ON SUBSTR(RJ.OTHER_SYSTEM_NO, 0, 12) = SUBSTR(SR.OTHER_SYSTEM_NO, 0, 12)
WHERE SR.ACCOUNT_CODE = '04991'
```

用于计算付款申请中的 `O_VAT`（已有消費税），是系统中**唯一需要跨 `JOURNAL_BASE` → `SUN_REQUEST` 追溯**的业务场景。

---

## 总结

JOURNAL_BASE 在系统中扮演**"采购交易原始数据仓库"**的核心角色：

- **数据来源**：由外部 MS 系材系统通过 HULFT 文件传输导入
- **状态守门**：通过 `CPL_MK` 和 `LIST_TYPE` 两个字段控制记录是否可进入对账单流程
- **架构地位**：位于整条业务链路（采购 → 对账 → 付款 → GL）的最上游，是后续所有业务对象的数据根基
- **唯一数据源**：生成对账单（`RECEIVING_LIST`）的**唯一数据来源**，通过 `RECEIVING_JOURNAL` 桥接表间接关联到付款申请和 GL 分录
