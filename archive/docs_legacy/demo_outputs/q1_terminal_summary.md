# Terminal Summary — q1

| Metric | Value |
|--------|-------|
| Question Length | 69 chars |
| Vector Hits | 10 |
| Graph Entities | 8 |
| Graph Neighbors | 51 |
| Answer Length | 6862 chars |
| Latency (total) | 61.49s |
| Input Tokens | 8101 |
| Output Tokens | 4096 |

## Search Terms

JOURNAL_BASE, PAYMENT_REQ, 応付

## Top 3 Vector Sources

1. MDW支払依頼_V3.1.pptx (dist=0.860)
2. combined_process_chain (dist=0.892)
3. MDW支払依頼_V3.1.pptx (dist=0.935)

## Answer Preview

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
| `OTHER_SYSTEM_NO` | 主键，来自 MS ...
