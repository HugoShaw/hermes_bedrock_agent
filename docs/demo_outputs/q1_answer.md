# QA Answer — q1

**Question:** 请描述应付管理的业务流程，并要求：
1. 每个流程步骤对应的数据库表
2. 每个步骤涉及的关键字段
3. 如有对应代码模块，请指出类或方法

**Timestamp:** 2026-05-18T06:38:27.565991

---

# 应付管理（Accounts Payable）完整业务流程

基于文档证据及知识图谱，应付管理系统（属于 iMaps 主系统）涉及 **MS系统**、**iMaps** 和 **SUN ERP** 三个系统集成，完整流程分为以下 **6个步骤**：

---

## 流程总览

```
MS系统 →(HULFT)→ JOURNAL_BASE → RECEIVING_LIST → PAYMENT_REQ → SUN_REQUEST →(HULFT)→ SUN ERP
                     Step 1          Step 2           Step 3/4        Step 5         Step 6
```

---

## Step 1：外部数据导入

### 业务说明
MS（資材/采购）系统在检收完了后，通过 **HULFT** 文件传输中间件，将采购/收货数据推送至 iMaps 数据库。iMaps 被动接收，无主动触发代码。

### 数据库表

| 表名 | 角色 |
|------|------|
| `JOURNAL_BASE` | 目标表，存储原始采购收货数据（31字段） |

### 关键字段

| 字段名 | 说明 |
|--------|------|
| `OTHER_SYSTEM_NO` | 主键，来自 MS 系统的唯一编号 |
| `VENDOR_CD` | 供应商编码 |
| `ID_NO1_CODE` | PO 号（采购订单号） |
| `TRANSACTION_AMOUNT` | 交易金额 |
| `TAX_RATE` | 税率 |
| `CPL_MK` | 检收标记，**= 8 表示検收完了**（触发条件） |
| `LIST_TYPE` | 状态标记，**= 0 表示未生成对账单** |
| `CURRENCY_CODE` | 币种 |
| `TRANSACTION_DATE` | 交易日期 |
| `RECEIVED_DATE` | 收货日期 |

### 代码模块
> **无对应代码**（外部系统通过 HULFT 自动推送，iMaps 被动接收）

---

## Step 2：对账单生成（Receiving List）

### 业务说明
财务/采购人员在 **Receiving 画面**，按供应商+币种+税率等条件查询 `JOURNAL_BASE` 中未处理的记录（`LIST_TYPE=0`），勾选后合并生成**对账单**（`RECEIVING_LIST`），系统自动生成 `PAY_NO`。

### 数据库表

| 表名 | 角色 |
|------|------|
| `JOURNAL_BASE` | 源数据表，查询条件：`CPL_MK=8 AND LIST_TYPE=0` |
| `RECEIVING_LIST` | 对账单主表，生成后 `PAY_NO` 自动编号 |
| `RECEIVING_JOURNAL` | **桥接表**，实现 `JOURNAL_BASE` ↔ `RECEIVING_LIST` 的 M:N 关联 |

### 关键字段

| 表 | 字段名 | 说明 |
|----|--------|------|
| `JOURNAL_BASE` | `LIST_TYPE` | **状态变更：0 → 1**（已生成对账单） |
| `RECEIVING_LIST` | `PAY_NO` | 对账单主键（自增） |
| `RECEIVING_LIST` | `VENDOR_CD` | 供应商编码 |
| `RECEIVING_LIST` | `TOTAL_AMT` | 合计金额 |
| `RECEIVING_LIST` | `CURRENCY` | 币种 |
| `RECEIVING_LIST` | `TRADE_RATE` | 汇率 |
| `RECEIVING_LIST` | `STATUS` | 对账单状态（初始=1，可编辑） |
| `RECEIVING_JOURNAL` | `PAY_NO` | 关联 `RECEIVING_LIST` |
| `RECEIVING_JOURNAL` | `OTHER_SYSTEM_NO` | 关联 `JOURNAL_BASE` |
| `RECEIVING_JOURNAL` | `TRANSACTION_REFERENCE` | 交易参考号 |

### 代码模块

```
【入口控制器】
JournalBaseAction.registReceiving()
    └──▶ 【业务服务层】
         ReceivingServiceImpl.saveReceivingList()
```

> 来源：文档证据1、5（`MDW支払依頼_V3.1.pptx`）

---

## Step 3：付款申请创建（Payment Request）

### 业务说明
在 **Payment Request 画面**，用户选择供应商，系统列出该供应商下 `STATUS=1` 的可用对账单，勾选后自动汇总金额。用户可修改税额（`N_VAT`）及含税总额（`N_TOTAL_AMT`），若与系统计算值有差异须填写 `DIFFERENCE_NOTE`。操作分两步：
- **Save**（保存草稿，`STATUS=1`）
- **Register**（注册提交，`STATUS=2`，进入审批，对账单被锁定）

### 数据库表

| 表名 | 角色 |
|------|------|
| `PAYMENT_REQ` | 付款申请主表（27字段） |
| `PAYMENT_RECEIVING` | **桥接表**，实现 `PAYMENT_REQ` ↔ `RECEIVING_LIST` 的 M:N 关联 |
| `RECEIVING_LIST` | 被引用后锁定（`STATUS → 0`） |

### 关键字段

| 表 | 字段名 | 说明 |
|----|--------|------|
| `PAYMENT_REQ` | `BILL_NO` | 业务主键，格式：`"PR" + 时间戳` |
| `PAYMENT_REQ` | `VENDOR_CD` | 供应商编码 |
| `PAYMENT_REQ` | `O_VAT` | 系统计算税额（Original） |
| `PAYMENT_REQ` | `N_VAT` | 实际税额（可修改） |
| `PAYMENT_REQ` | `O_TOTAL_AMT` | 系统计算含税总额 |
| `PAYMENT_REQ` | `N_TOTAL_AMT` | 实际含税总额（可修改） |
| `PAYMENT_REQ` | `SLIP_DATE` | 传票日期 |
| `PAYMENT_REQ` | `STATUS` | **状态机：1=保存 / 2=注册待审批** |
| `PAYMENT_REQ` | `DIFFERENCE_NOTE` | 差额说明（金额不一致时必填） |
| `PAYMENT_RECEIVING` | `PAY_NO` | 关联 `RECEIVING_LIST` |
| `PAYMENT_RECEIVING` | `BILL_NO` | 关联 `PAYMENT_REQ` |
| `RECEIVING_LIST` | `STATUS` | **Register 后：1 → 0**（锁定） |

### 代码模块

```
【入口控制器】
PaymentReqAction.savePaymentReq()
    └──▶ 【业务服务层】
         PaymentReqServiceImpl.savePaymentReq()
```

> 来源：文档证据1、5、9（`MDW支払依頼_V3.1.pptx`、`付款申请画面需求.xlsx`）

---

## Step 4：审批（Approval）

### 业务说明
具有 **調達（Procurement）** 或 **経理（Accounting）** 角色的审批人进入 **Payment Request Manage 画面**，查询 `STATUS=2` 的待审批申请，查看详情后填写审批意见，执行**承認**或**否認**。

- **承認**（`STATUS → 3`）：不可逆，自动触发 Step 5 GL 记账
- **否認**（`STATUS → 4`）：退回，申请人可重新编辑后再次提交（`STATUS → 2`）

### 数据库表

| 表名 | 角色 |
|------|------|
| `PAYMENT_REQ` | 更新审批状态及审批信息 |

### 关键字段

| 字段名 | 说明 |
|--------|------|
| `STATUS` | **状态变更：2 → 3（承認）或 2 → 4（否認）** |
| `APPROVAL_BY` | 审批人 |
| `APPROVAL_TIME` | 审批时间 |
| `APPROVAL_REMARK` | 审批意见（最长500字符） |

### 状态机全貌（基于知识图谱证据）

```
STATUS=1(保存) ──▶ STATUS=2(注册/待审批)
                        ├──▶ STATUS=3(承認完了) ──▶ STATUS=5(取消)
                        ├──▶ STATUS=4(否認)     ──▶ STATUS=2(重新提交)
                        └──▶ STATUS=6(删除)
STATUS=1/2/4 可 ──▶ STATUS=6(删除，DEL_FLG=1)
```

### 代码模块

```
【入口控制器】
PaymentReqAction.updateByBillNos()
```

> 来源：文档证据1、5（`MDW支払依頼_V3.1.pptx`），知识图谱实体 `PAYMENT_REQ_STATUS_*`

---

## Step 5：GL 记账 / 支付（GL Posting）

### 业务说明
审批通过（`STATUS=3`）后，系统**自动触发**生成会计分录，写入 `SUN_REQUEST` 表，再经由 **HULFT** 传输至 **SUN ERP** 完成总账记账。涉及借方（Request1）和贷方（Request2）两条分录，若存在 VAT 差额则额外生成一条差额传票（`ACCOUNT_CODE='04991'`）。

### 数据库表

| 表名 | 角色 |
|------|------|
| `SUN_REQUEST` | GL 分录表（ERP 接口表，25字段） |

### 关键字段

| 字段名 | 说明 |
|--------|------|
| `ACCOUNT_CODE` | 勘定科目（会计科目代码） |
| `TRANSACTION_AMOUNT` | 分录金额 |
| `JOURNAL_NO` | 仕訳番号（分录编号） |
| `OTHER_SYSTEM_NO` | 关联 `RECEIVING_JOURNAL`（通过 **SUBSTR 子串匹配**） |

### 数据关联特殊说明

```
SUN_REQUEST.OTHER_SYSTEM_NO
    └──(SUBSTR匹配)──▶ RECEIVING_JOURNAL.OTHER_SYSTEM_NO
                              └──(PAY_NO)──▶ RECEIVING_LIST
```

### 代码模块
> 审批通过后**自动触发**，由服务层内部调用生成 GL 分录，文档中未单独列出方法名。

> 来源：文档证据1、4、8（`MDW支払依頼_V3.1.pptx`、`村田.xlsx`），知识图谱 `PAYMENT_REQ_STATUS_3 —[generates]→ SUN_REQUEST`

---

## Step 6：报表输出（Report）

### 业务说明
在 **Payment List 画面（PRSG0251）**，用户可查询已审批的付款申请并下载报表，支持 **PDF**（JasperReport 引擎）和 **Excel**（Apache POI）两种格式，数据来源为封装完整 JOIN 的视图 `V_PAYMENT_REQ_FILE`。

### 数据库表

| 表名 | 角色 |
|------|------|
| `V_PAYMENT_REQ_FILE` | 报表视图，覆盖从 `PAYMENT_REQ` 到 `JOURNAL_BASE` 的完整 JOIN |

### 关键字段
> 视图包含所有明细字段（`PAYMENT_REQ` → `PAYMENT_RECEIVING` → `RECEIVING_LIST` → `RECEIVING_JOURNAL` → `JOURNAL_BASE` 的完整关联字段）

### 代码模块

```
【入口控制器】
PaymentReqAction.downloadPdfFile()    ──▶ PaymentFileUtil.createPDFModel()   (JasperReport)
PaymentReqAction.downloadExcelFile()  ──▶ PaymentFileUtil.createExcel()      (Apache POI)
```

> 来源：文档证据1、5（`MDW支払依頼_V3.1.pptx`）

---

## 完整流程汇总表

| 步骤 | 业务动作 | 核心数据库表 | 关键状态字段变更 | 代码模块 |
|------|---------|------------|----------------|---------|
| **Step 1** | 外部数据导入 | `JOURNAL_BASE` | `CPL_MK=8`, `LIST_TYPE=0` | 无（HULFT被动接收） |
| **Step 2** | 对账单生成 | `RECEIVING_LIST`<br>`RECEIVING_JOURNAL`<br>`JOURNAL_BASE` | `LIST_TYPE: 0→1` | `JournalBaseAction.registReceiving()`<br>`ReceivingServiceImpl.saveReceivingList()` |
| **Step 3** | 付款申请创建 | `PAYMENT_REQ`<br>`PAYMENT_RECEIVING`<br>`RECEIVING_LIST` | `PAYMENT_REQ.STATUS: →1/2`<br>`RECEIVING_LIST.STATUS: 1→0` | `PaymentReqAction.savePaymentReq()`<br>`PaymentReqServiceImpl.savePaymentReq()` |
| **Step 4** | 审批 | `PAYMENT_REQ` | `STATUS: 2→3(承認)/4(否認)` | `PaymentReqAction.updateByBillNos()` |
| **Step 5** | GL记账/支付 | `SUN_REQUEST` | `STATUS=3` 触发生成 | 自动触发（内部服务） |
| **Step 6** | 报表输出 | `V_PAYMENT_REQ_FILE`（视图） | — | `PaymentReqAction.downloadPdfFile()`<br>`PaymentReqAction.downloadExcelFile()` |

---

## 系统集成架构

```
┌─────────────────────────────────────────────────────────────┐
│                    iMaps 应付管理模块                         │
│  JOURNAL_BASE → RECEIVING_LIST → PAYMENT_
