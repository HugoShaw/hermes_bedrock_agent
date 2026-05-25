# QA Answer — q4

**Question:** 请围绕'应付管理完整业务流程'，构建一个 Semantic Map，输出 Neptune CSV。
已知业务主流程为：
订单 → 对账单 → 审批 → 付款申请 → 审批 → 支付 → 报表

要求：
1. 必须覆盖以上完整流程链，不得缺失步骤
2. 输出 nodes.csv，字段：id,label,type
3. 输出 edges.csv，字段：from,to,relation
4. 关系仅允许：generates, depends_on, relates_to
5. 必须体现一条清晰主链，至少包含连续路径 A → B → C → D
6. 不要解释，只输出 CSV

**Timestamp:** 2026-05-18T06:49:37.233642

---

```csv
id,label,type
N01,MS系统(外部订单),ExternalSystem
N02,HULFT,Middleware
N03,JOURNAL_BASE,Table
N04,对账单生成(Receiving List),BusinessStep
N05,RECEIVING_LIST,Table
N06,RECEIVING_JOURNAL,Table
N07,对账单审批,BusinessStep
N08,付款申请创建(Payment Request),BusinessStep
N09,PAYMENT_REQ,Table
N10,PAYMENT_RECEIVING,Table
N11,付款申请审批(Approval),BusinessStep
N12,支付/GL记账,BusinessStep
N13,SUN_REQUEST,Table
N14,SUN ERP,ExternalSystem
N15,报表输出(Report),BusinessStep
N16,V_PAYMENT_REQ_FILE,View
N17,JournalBaseAction,Action
N18,PaymentReqAction,Action
N19,PaymentReqServiceImpl,ServiceImpl
N20,ReceigIngServiceImpl,ServiceImpl
N21,HULFT_DICT,Table
```

```csv
from,to,relation
N01,N02,generates
N02,N03,generates
N03,N04,generates
N04,N05,generates
N04,N06,generates
N05,N07,generates
N07,N08,generates
N08,N09,generates
N08,N10,generates
N09,N11,generates
N10,N11,depends_on
N11,N12,generates
N12,N13,generates
N13,N14,generates
N14,N15,generates
N15,N16,depends_on
N06,N05,relates_to
N06,N03,depends_on
N10,N09,relates_to
N10,N05,relates_to
N17,N04,relates_to
N20,N04,relates_to
N18,N08,relates_to
N18,N11,relates_to
N19,N08,relates_to
N19,N11,relates_to
N21,N03,relates_to
N21,N05,relates_to
N16,N09,depends_on
N16,N06,depends_on
N16,N03,depends_on
```
