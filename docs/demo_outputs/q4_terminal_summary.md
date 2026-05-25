# Terminal Summary — q4

| Metric | Value |
|--------|-------|
| Question Length | 287 chars |
| Vector Hits | 10 |
| Graph Entities | 6 |
| Graph Neighbors | 29 |
| Answer Length | 1227 chars |
| Latency (total) | 8.43s |
| Input Tokens | 7402 |
| Output Tokens | 568 |

## Search Terms

付款, 审批

## Top 3 Vector Sources

1. combined_process_chain (dist=0.527)
2. 村田.xlsx (dist=0.898)
3. MDW支払依頼_V3.1.pptx (dist=0.928)

## Answer Preview

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
N...
