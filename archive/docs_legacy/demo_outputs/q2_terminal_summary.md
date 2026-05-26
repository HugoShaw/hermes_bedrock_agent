# Terminal Summary — q2

| Metric | Value |
|--------|-------|
| Question Length | 64 chars |
| Vector Hits | 10 |
| Graph Entities | 6 |
| Graph Neighbors | 46 |
| Answer Length | 3659 chars |
| Latency (total) | 40.27s |
| Input Tokens | 8603 |
| Output Tokens | 2292 |

## Search Terms

JOURNAL_BASE, Journal

## Top 3 Vector Sources

1. MURATA_20180530.sql (dist=0.563)
2. MURATA_20180530.sql (dist=0.644)
3. JournalBaseAction.java (dist=0.709)

## Answer Preview

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
| `TRANSACTION_DATE` | TIMESTAMP | 交易日期（Slip Date...
