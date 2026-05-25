# QA Answer — q5

**Question:** 当前系统中，付款申请在应付系统内完成审批。
现在需要进行系统改造：
- 做单仍在应付系统，Payment Request
- 审批流程迁移到 OA 系统
- 审批完成后，审批结果需要回写应付系统。

请完成以下内容：
1. 设计新的业务流程
2. 描述数据流转关系
3. 给出系统改造清单
4. 说明对现有业务流程的影响

要求：
- 结合现有表结构，如 PAYMENT_REQ、PAYMENT_RECEIVING 等
- 尽量具体，不要泛泛而谈
- 不要只写概念，需要有结构化内容

**Timestamp:** 2026-05-18T06:54:29.746378

---

# 付款申请审批迁移至OA系统 — 系统改造方案

---

## 一、新业务流程设计

### 1.1 全流程总览（改造后）

```
[申请人 - 应付系统]          [OA系统]              [应付系统 - 回写]
        │                        │                        │
  做单/保存                       │                        │
  STATUS=1                       │                        │
        │                        │                        │
  Register提交                    │                        │
  STATUS=2                       │                        │
        │──── POST /api/oa/ ────►│                        │
        │     approval/submit    │                        │
        │     (推送审批申请)       │                        │
        │◄─── oaTaskId ─────────│                        │
        │                        │                        │
        │              OA内部审批流转                       │
        │              (调达 → 経理)                       │
        │                        │                        │
        │                        │──── POST /api/ap/ ────►│
        │                        │     oa/callback        │
        │                        │     (回调结果)          │
        │                        │                  更新PAYMENT_REQ
        │                        │                  STATUS=3/4
        │                        │                  APPROVAL_BY
        │                        │                  APPROVAL_TIME
        │                        │                  APPROVAL_REMARK
        │                        │                        │
        │                        │              [STATUS=3] 触发
        │                        │               SUN_REQUEST生成
        │                        │               → SUN ERP
```

### 1.2 分角色操作步骤

| 步骤 | 角色 | 系统 | 操作 | 结果 |
|------|------|------|------|------|
| 1 | 申请人 | 应付系统 | 选择Vendor → 勾选对账单 → 填写金额 | RECEIVING_LIST关联 |
| 2 | 申请人 | 应付系统 | 点击Save | PAYMENT_REQ.STATUS=1，BILL_NO生成 |
| 3 | 申请人 | 应付系统 | 点击Register | STATUS=1→2，触发推送OA |
| 4 | 应付系统 | 应付系统→OA | 自动调用OA推送接口 | OA创建审批任务，返回oaTaskId |
| 5 | 应付系统 | 应付系统DB | 记录oaTaskId到PAYMENT_REQ新增字段 | OA任务与单据绑定 |
| 6 | 审批人 | **OA系统** | 查看审批任务，填写意见，承认/否认 | OA内完成审批 |
| 7 | OA系统 | OA→应付系统 | 调用回调接口 | 写入STATUS=3/4及审批信息 |
| 8 | 系统自动 | 应付系统 | STATUS=3触发GL分录 | 生成SUN_REQUEST → SUN ERP |
| 9 | 申请人 | 应付系统 | 查看审批结果（只读） | Payment List展示最终状态 |

---

## 二、数据流转关系

### 2.1 推送阶段：应付系统 → OA

**触发时机：** `PaymentReqAction.savePaymentReq()` 执行 Register（STATUS=2）时

**推送数据包（POST /api/oa/approval/submit）：**

```json
{
  "billNo":       "PR20240115143022",    // PAYMENT_REQ.BILL_NO
  "vendorCd":     "V001",                // PAYMENT_REQ.VENDOR_CD
  "vendorName":   "供应商名称",           // PAYMENT_REQ.VENDOR_NAME
  "currency":     "CNY",                 // PAYMENT_REQ.CURRENCY
  "totalAmount":  "100000.00",           // PAYMENT_REQ.N_TOTAL_AMT
  "vatAmount":    "9000.00",             // PAYMENT_REQ.N_VAT
  "slipDate":     "2024-01-15",          // PAYMENT_REQ.SLIP_DATE
  "requester":    "USER001",             // PAYMENT_REQ.CREATE_BY
  "differenceNote": "税额差异说明",       // PAYMENT_REQ.DIFFERENCE_NOTE
  "payNos":       ["P20240101", "P20240102"] // PAYMENT_RECEIVING.PAY_NO列表
}
```

**OA返回：**

```json
{
  "success": true,
  "oaTaskId": "OA-2024-00123"           // 写入PAYMENT_REQ.OA_TASK_ID（新增字段）
}
```

---

### 2.2 回调阶段：OA → 应付系统

**触发时机：** OA审批完成（通过/拒绝）后，OA主动调用

**回调数据包（POST /api/ap/oa/callback）：**

```json
{
  "oaTaskId":     "OA-2024-00123",       // 用于定位PAYMENT_REQ记录
  "billNo":       "PR20240115143022",    // 双重校验
  "result":       "APPROVED",           // APPROVED / REJECTED
  "approver":     "MGR001",             // → PAYMENT_REQ.APPROVAL_BY
  "approvalTime": "2024-01-16T10:30:00",// → PAYMENT_REQ.APPROVAL_TIME
  "remark":       "金额核实无误，同意付款" // → PAYMENT_REQ.APPROVAL_REMARK
}
```

**回调处理逻辑（新增 OaCallbackAction）：**

```
1. 校验 oaTaskId + billNo 匹配
2. 校验当前 STATUS=2（防止重复回调）
3. 校验签名/Token（安全认证）
4. 执行更新：
   - APPROVED → STATUS='3', APPROVAL_BY, APPROVAL_TIME, APPROVAL_REMARK
   - REJECTED → STATUS='4', APPROVAL_BY, APPROVAL_TIME, APPROVAL_REMARK
5. STATUS=3 时触发 SUN_REQUEST 生成（原有逻辑保持不变）
6. 返回 {"success": true}
```

---

### 2.3 完整数据流图

```
JOURNAL_BASE
    ↓ (HULFT导入)
RECEIVING_LIST ←──────────────── PAYMENT_RECEIVING ──── PAYMENT_REQ
(STATUS: 1→0锁定)  桥接关联(PAY_NO/BILL_NO)           (STATUS: 1→2→3/4)
                                                              │
                                                    ┌─────────┴──────────┐
                                               推送OA(STATUS=2时)    OA回调(审批完成)
                                                    │                    │
                                               OA系统审批          写入APPROVAL_BY
                                               (内部流转)           APPROVAL_TIME
                                                                   APPROVAL_REMARK
                                                                   OA_TASK_STATUS
                                                              │
                                                         STATUS=3
                                                              ↓
                                                        SUN_REQUEST
                                                              ↓
                                                         SUN ERP
```

---

## 三、系统改造清单

### 3.1 数据库改造

#### PAYMENT_REQ 表新增字段

```sql
ALTER TABLE PAYMENT_REQ ADD (
  OA_TASK_ID      VARCHAR2(50),      -- OA系统返回的审批任务ID
  OA_TASK_STATUS  VARCHAR2(20),      -- OA任务状态: PENDING/APPROVED/REJECTED/CANCELLED
  OA_SUBMIT_TIME  TIMESTAMP,         -- 推送OA的时间
  OA_CALLBACK_TIME TIMESTAMP         -- OA回调时间（用于对账/排查）
);

COMMENT ON COLUMN PAYMENT_REQ.OA_TASK_ID      IS 'OA系统审批任务ID，Register后写入';
COMMENT ON COLUMN PAYMENT_REQ.OA_TASK_STATUS  IS 'OA端任务状态，与STATUS字段协同使用';
COMMENT ON COLUMN PAYMENT_REQ.OA_SUBMIT_TIME  IS '推送OA时间';
COMMENT ON COLUMN PAYMENT_REQ.OA_CALLBACK_TIME IS 'OA回调写入时间';
```

> **说明：** 原有 `STATUS`、`APPROVAL_BY`、`APPROVAL_TIME`、`APPROVAL_REMARK` 字段**不变**，回调后仍写入这些字段，保持下游逻辑（GL分录生成、报表视图）兼容。

---

### 3.2 后端代码改造

#### 改造项目 1：`PaymentReqAction.savePaymentReq()`

**改造内容：** Register 时（STATUS=2）新增推送 OA 逻辑

```java
// 改造前（伪代码）
public JsonModel savePaymentReq(...) {
    paymentReqService.savePaymentReq(paymentReq, payNos, user);
    // 仅做单，无后续推送
}

// 改造后（伪代码）
public JsonModel savePaymentReq(...) {
    JsonModel result = paymentReqService.savePaymentReq(paymentReq, payNos, user);
    
    // 新增：Register时推送OA
    if ("2".equals(paymentReq.getStatus())) {
        OaSubmitRequest oaReq = buildOaRequest(paymentReq, payNos);
        OaSubmitResponse oaResp = oaIntegrationService.submitToOA(oaReq);
        
        if (oaResp.isSuccess()) {
            // 写入OA任务ID
            paymentReqService.updateOaTaskId(
                paymentReq.getBillNo(), 
                oaResp.getOaTaskId(),
                new Date()
            );
        } else {
            // 推送失败处理：回滚STATUS或记录异常
            // 建议：记录失败日志 + 告警，不阻断用户操作（异步重试）
        }
    }
    return result;
}
```

---

#### 改造项目 2：`PaymentReqAction.updateByBillNos()`

**改造内容：** 原审批入口**禁用前端直接调用**，改为仅供 OA 回调路径使用（或废弃后由新接口替代）

```java
// 改造后：增加调用来源校验，拒绝前端直接触发
@RequestMapping("/updateByBillNos")
public JsonModel updateByBillNos(...) {
    // 新增：拒绝非OA回调来源的审批操作
    throw new UnsupportedOperationException(
        "审批已迁移至OA系统，请通过OA完成审批操作");
}
```

---

#### 改造项目 3：新增 `OaCallbackAction.java`（核心新增）

```java
/**
 * OA审批结果回调接口
 * POST /api/ap/oa/callback
 */
@RequestMapping("/api/ap/oa/callback")
public JsonModel oaApprovalCallback(@RequestBody OaCallbackRequest request) {
    
    // Step 1: 安全认证（API Key校验）
    if (!authService.validateOaToken(request.getToken())) {
        return JsonModel.error("认证失败");
    }
    
    // Step 2: 查询目标记录
    // 查询条件: DEL_FLG='0' AND STATUS='2' AND BILL_NO=? AND OA_TASK_ID=?
    PaymentReq payReq = paymentReqService.findByBillNoAndOaTaskId(
        request.getBillNo(), request.getOaTaskId());
    
    if (payReq == null) {
        return JsonModel.error("单据不存在或状态不符（当前非待审批状态）");
    }
    
    // Step 3: 写入审批结果（复用原有字段）
    String newStatus = "APPROVED".equals(request.getResult()) ? "3" : "4";
    payReq.setStatus(newStatus);
    payReq.setApprovalBy(request.getApprover());
    payReq.setApprovalTime(request.getApprovalTime());
    payReq.setApproveRemark(request.getRemark());
    payReq.setOaTaskStatus(request.getResult());
    payReq.setOaCallbackTime(new Date());
    
    // Step 4: 持久化（@Transactional保证一致性）
    paymentReqService.saveOrUpdate(payReq);
    
    // Step 5: STATUS=3时触发GL分录（原有逻辑不变）
    if ("3".equals(newStatus)) {
        sunRequestService.generateSunRequest(payReq);
    }
    
    return JsonModel.success();
}
```

---

#### 改造项目 4：新增 `OaIntegrationService.java`（OA推送服务）

```java
public interface OaIntegrationService {
    /**
     * 向OA发起审批申请
     * @param request 包含billNo、金额、供应商等信息
     * @return OA返回的taskId
     */
    OaSubmitResponse submitToOA(OaSubmitRequest request);
    
    /**
     * 撤回OA审批任务（取消付款申请时调用）
     */
    boolean cancelOaTask(String oaTaskId);
}
```

---

#### 改造项目 5：`PaymentReqAction.updatePaymentByCancel()`

**改造内容：** 取消操作时，若 OA_TASK_STATUS=PENDING，需同步撤回 OA 任务

```java
public JsonModel updatePaymentByCancel(...) {
    // 原有取消逻辑
    paymentReqService.deleteOrCanclePaymentReq(arrayIds, user, "CANCLE");
    
    // 新增：通知OA撤回审批任务
    for (String billNo : arrayIds) {
        PaymentReq payReq = paymentReqService.findByBillNo(billNo);
        if (payReq.getOaTaskId() != null 
            && "PENDING".equals(payReq.getOaTaskStatus())) {
            oaIntegrationService.cancelOaTask(payReq.getOaTaskId());
        }
    }
}
```

---

### 3.3 前端改造

| 画面 | 改造内容 | 改造方向 |
|------|----------|----------|
| Payment Request Manage | 移除 [Approve] / [Reject] 按钮 | 展示型：显示"审批中-请前往O
