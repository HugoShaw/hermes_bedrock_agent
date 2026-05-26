# QA Answer — q1

**Question:** 请描述应付管理的业务流程，并要求：
1. 每个流程步骤对应的数据库表
2. 每个步骤涉及的关键字段
3. 如有对应代码模块，请指出类或方法

**Timestamp:** 2026-05-18T06:30:40.905899

---

# 应付管理完整业务流程说明

基于文档证据（MDW支払依頼_V3.1.pptx、村田.xlsx、操作手册等）和知识图谱证据，以下是应付管理的完整6步业务流程。

---

## 总览：流程架构图

```
MS系统 →(HULFT)→ JOURNAL_BASE → RECEIVING_JOURNAL → RECEIVING_LIST
                                                              ↓
                                                   PAYMENT_RECEIVING → PAYMENT_REQ
                                                                              ↓
                                                                       SUN_REQUEST → SUN ERP
                                                                              ↓
                                                                    V_PAYMENT_REQ_FILE → 报表输出
```

**系统集成关系**（来源：知识图谱 `応付管理システム`）：
- 依赖 MS系统（外部采购系统）作为数据源头
- 依赖 SUN ERP 作为总账记账目标
- 归属于 iMaps 主系统

---

## Step 1：外部数据导入

### 业务说明
MS（资材/采购）系统完成检收后，通过 HULFT 文件传输中间件将收货数据推送至 iMaps 系统。此步骤为被动接收，无需人工干预。

### 触发条件
检收完了标记：`CPL_MK = 8`

### 对应数据库表

| 表名 | 角色 |
|------|------|
| `JOURNAL_BASE` | 原始采购/收货数据存储（31字段） |

### 关键字段

| 字段名 | 说明 |
|--------|------|
| `OTHER_SYSTEM_NO` | 主键，来自MS系统的单据号 |
| `VENDOR_CD` | 供应商编码 |
| `ID_NO1_CODE` | PO号（采购订单号） |
| `TRANSACTION_AMOUNT` | 交易金额 |
| `TAX_RATE` | 税率 |
| `CPL_MK` | 检收完了标记（= 8 表示完了） |
| `LIST_TYPE` | 状态标记（= 0 表示未选入对账单） |
| `CURRENCY_CODE` | 币种 |
| `TRANSACTION_REFERENCE` | 交易参考号 |
| `RECEIVED_DATE` | 检收日期 |

### 代码模块
> **无对应代码模块**——由外部MS系统通过HULFT自动推送，iMaps被动接收。

---

## Step 2：对账单生成（Receiving List）

### 业务说明
财务人员进入 Receiving 画面，按供应商、检收日期、PO号、币种、税率等条件查询 `JOURNAL_BASE` 中未生成对账单的记录（`LIST_TYPE=0`），勾选后合并生成对账单。

**限制条件**：同一对账单内记录须为同一供应商 + 同一币种 + 同一税率。

### 对应数据库表

| 表名 | 角色 |
|------|------|
| `JOURNAL_BASE` | 数据来源，查询 `LIST_TYPE=0` 的记录 |
| `RECEIVING_LIST` | 对账单主表（生成目标） |
| `RECEIVING_JOURNAL` | 桥接表，实现 `JOURNAL_BASE` ↔ `RECEIVING_LIST` 的 M:N 关联 |

### 关键字段

| 表 | 字段名 | 说明 |
|----|--------|------|
| `RECEIVING_LIST` | `PAY_NO` | 对账单号（自增主键） |
| `RECEIVING_LIST` | `VENDOR_CD` | 供应商编码 |
| `RECEIVING_LIST` | `TOTAL_AMT` | 对账单合计金额 |
| `RECEIVING_LIST` | `CURRENCY` | 币种 |
| `RECEIVING_LIST` | `TRADE_RATE` | 汇率 |
| `RECEIVING_LIST` | `STATUS` | 状态（1=可用，0=已被付款申请锁定） |
| `JOURNAL_BASE` | `LIST_TYPE` | 状态变更：**0 → 1**（已选入对账单） |
| `RECEIVING_JOURNAL` | `PAY_NO` | 关联对账单 |
| `RECEIVING_JOURNAL` | `OTHER_SYSTEM_NO` | 关联原始交易记录 |
| `RECEIVING_JOURNAL` | `TRANSACTION_REFERENCE` | 交易参考号 |

### 状态变更
```
JOURNAL_BASE.LIST_TYPE:  0（未选入）→ 1（已选入）
RECEIVING_LIST.STATUS:   新建为 1（可用状态）
```

### 代码模块
```
【入口控制器】
JournalBaseAction.registReceiving()
    └── 【业务服务层】
        ReceivingServiceImpl.saveReceivingList()
```
> 来源：MDW支払依頼_V3.1.pptx

---

## Step 3：付款申请创建（Payment Request）

### 业务说明
采购员/财务人员进入 Payment Request 画面，选择供应商后查询可用对账单（`RECEIVING_LIST.STATUS=1`），勾选一张或多张对账单，填写金额、税额等信息，保存或提交审批。

### 对应数据库表

| 表名 | 角色 |
|------|------|
| `RECEIVING_LIST` | 来源数据，查询 `STATUS=1` 的可用对账单 |
| `PAYMENT_REQ` | 付款申请主表（27字段） |
| `PAYMENT_RECEIVING` | 桥接表，实现 `PAYMENT_REQ` ↔ `RECEIVING_LIST` 的 M:N 关联 |

### 关键字段

| 表 | 字段名 | 说明 |
|----|--------|------|
| `PAYMENT_REQ` | `BILL_NO` | 付款申请号（业务主键，格式="PR"+时间戳） |
| `PAYMENT_REQ` | `VENDOR_CD` | 供应商编码 |
| `PAYMENT_REQ` | `O_VAT` | 系统计算税额（原始） |
| `PAYMENT_REQ` | `N_VAT` | 实际税额（可修改） |
| `PAYMENT_REQ` | `O_TOTAL_AMT` | 系统计算含税总额 |
| `PAYMENT_REQ` | `N_TOTAL_AMT` | 实际含税总额（可修改） |
| `PAYMENT_REQ` | `SLIP_DATE` | 单据日期 |
| `PAYMENT_REQ` | `DIFFERENCE_NOTE` | 差额说明（当N_VAT≠O_VAT时必填） |
| `PAYMENT_REQ` | `STATUS` | 状态（1=保存草稿，2=注册提交审批） |
| `PAYMENT_RECEIVING` | `PAY_NO` | 关联对账单 |
| `PAYMENT_RECEIVING` | `BILL_NO` | 关联付款申请 |
| `RECEIVING_LIST` | `STATUS` | 状态变更：**1 → 0**（被锁定，Register后） |

### 状态变更
```
PAYMENT_REQ.STATUS:    → 1（Save，草稿保存）
                       → 2（Register，提交审批）
RECEIVING_LIST.STATUS: 1 → 0（Register后对账单被锁定，不可再被其他申请引用）
```

### 代码模块
```
【入口控制器】
PaymentReqAction.savePaymentReq()
    └── 【业务服务层】
        PaymentReqServiceImpl.savePaymentReq()
```
> 来源：MDW支払依頼_V3.1.pptx、付款申请画面需求.xlsx

---

## Step 4：审批流程（Approval）

### 業务说明
調達（Procurement）和経理（Accounting）角色的审批人进入 Payment Request Manage 画面，查看 `STATUS=2` 的待审批申请，查阅申请明细后填写审批意见，进行承认或否认操作。

### 对应数据库表

| 表名 | 角色 |
|------|------|
| `PAYMENT_REQ` | 状态更新目标表 |

### 关键字段

| 字段名 | 说明 |
|--------|------|
| `STATUS` | 状态变更（2→3 承認 / 2→4 否認） |
| `APPROVAL_BY` | 审批人 |
| `APPROVAL_TIME` | 审批时间 |
| `APPROVAL_REMARK` | 审批意见（最长500字符） |

### 状态变更（知识图谱 `PAYMENT_REQ_STATUS_*` 完整状态机）
```
STATUS 1（保存）  → STATUS 2（注册/待审批）
STATUS 2（待审批）→ STATUS 3（承認完了）✓ 触发GL记账，不可逆
                 → STATUS 4（否認）     ✗ 退回，申请人可重新编辑
                 → STATUS 6（删除）
STATUS 3（承認）  → STATUS 5（取消）
STATUS 2（待审批）→ STATUS 1（退回编辑）
STATUS 1/2/4     → STATUS 6（删除，同时 DEL_FLG=1）
```

### 代码模块
```
【入口控制器】
PaymentReqAction.updateByBillNos()
```
> 来源：MDW支払依頼_V3.1.pptx、知识图谱

---

## Step 5：GL记账 / 支付（GL Posting）

### 业务说明
审批通过（`STATUS=3`）后，系统**自动触发** GL 会计分录生成，写入 `SUN_REQUEST` 表，再通过 HULFT 传输至 SUN ERP 系统完成总账记账。

### 对应数据库表

| 表名 | 角色 |
|------|------|
| `PAYMENT_REQ` | 触发源，`STATUS=3` 时触发 |
| `SUN_REQUEST` | GL分录写入目标（25字段） |

> 知识图谱确认：`PAYMENT_REQ_STATUS_3 —[generates]→ SUN_REQUEST`

### 关键字段

| 表 | 字段名 | 说明 |
|----|--------|------|
| `SUN_REQUEST` | `ACCOUNT_CODE` | 勘定科目（会计科目代码） |
| `SUN_REQUEST` | `TRANSACTION_AMOUNT` | 分录金额 |
| `SUN_REQUEST` | `JOURNAL_NO` | 仕訳番号（分录编号） |
| `SUN_REQUEST` | `OTHER_SYSTEM_NO` | 关联原始交易（通过SUBSTR匹配 `RECEIVING_JOURNAL.OTHER_SYSTEM_NO`） |

### 特殊逻辑
- 生成借方 Request1 + 贷方 Request2 两条 GL 分录
- 当存在 VAT 差额时，额外生成 `ACCOUNT_CODE='04991'` 的差额传票

### 代码模块
> 审批通过后**自动触发**，无独立入口方法（内嵌于审批通过的事务处理中）。

---

## Step 6：报表输出（Report）

### 业务说明
财务人员进入 Payment List 画面（画面编号 PRSG0251），查询已审批的付款申请，下载 PDF 或 Excel 格式的报表。

### 对应数据库表/视图

| 表名 | 角色 |
|------|------|
| `V_PAYMENT_REQ_FILE` | 报表专用视图（从 `PAYMENT_REQ` 到 `JOURNAL_BASE` 的完整 JOIN） |

### 关键字段
> `V_PAYMENT_REQ_FILE` 视图包含从 `PAYMENT_REQ` 至 `JOURNAL_BASE` 的所有明细字段（完整JOIN结果），覆盖供应商信息、金额汇总、对账单明细、交易明细。

### 代码模块
```
【入口控制器】
PaymentReqAction.downloadPdfFile()      → PDF报表（JasperReport引擎）
PaymentReqAction.downloadExcelFile()    → Excel报表（Apache POI）

【工具类】
PaymentFileUtil.createPDFModel()        → PDF模型构建
PaymentFileUtil.createExcel()           → Excel文件构建
```

### 输出格式
| 格式 | 引擎 | 内容 |
|------|------|------|
| PDF | JasperReport | 付款申请书（含供应商信息+金额+明细行） |
| Excel | Apache POI | 付款明细表（含完整字段，支持CNY/USD/JPY多币种） |

---

## 完整流程汇总表

| 步骤 | 流程名称 | 主要数据表 | 桥接表 | 状态字段变更 | 核心代码模块 |
|------|----------|-----------|--------|------------|------------|
| 1 | 外部数据导入 | `JOURNAL_BASE` | — | `LIST_TYPE=0`, `CPL_MK=8`（初始） | 无（HULFT被动接收） |
| 2 | 对账单生成 | `RECEIVING_LIST` | `RECEIVING_JOURNAL` | `LIST_TYPE: 0→1` | `JournalBaseAction.registReceiving()` → `ReceivingServiceImpl.saveReceivingList()` |
| 3 | 付款申请创建 | `PAYMENT_REQ` | `PAYMENT_RECEIVING` | `STATUS: →1 or →2`; `RL.STATUS: 1→0` | `PaymentReqAction.savePaymentReq()` → `PaymentReqServiceImpl.savePaymentReq()` |
| 4 | 审批 | `PAYMENT_REQ` | — | `STATUS: 2→3/4` | `PaymentReqAction.updateByBillNos()` |
| 5 | GL记账/支付 | `SUN_REQUEST` | — | 自动触发（STATUS=3后） | 自动触发（内嵌于审批事务） |
| 6 | 报表输出 | `V_PAYMENT_REQ_FILE`（视图） | — | —
