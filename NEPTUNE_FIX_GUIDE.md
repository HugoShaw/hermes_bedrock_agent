# Neptune Analytics 写入阻断原因 & 修复清单

## 当前状态

| 检查项 | 状态 | 说明 |
|--------|------|------|
| DNS 解析 | OK | g-ci7fl1gkn9.ap-northeast-1.neptune-graph.amazonaws.com -> 10.0.142.50 |
| EC2 出站 TCP/443 -> 10.0.142.50 | **BLOCKED** | 安全组出站规则未放行 |
| IAM neptune-graph:ExecuteQuery | **未验证** | 网络层先被阻断，无法测试 |
| IAM neptune-graph:ListGraphs | **拒绝** | Role 缺少此权限 |
| 写入脚本 (dry-run) | OK | 511 nodes + 1821 edges 全部解析正确 |

---

## 修复步骤（需要 AWS 控制台权限）

### 1. 修改 EC2 安全组出站规则

安全组 ID: sg-00abc6bc5fbcad128
VPC: vpc-02a1ca09a0b51966e

在 EC2 控制台 -> Security Groups -> sg-00abc6bc5fbcad128 -> Outbound rules，添加：

```
Type:        Custom TCP
Port range:  443
Destination: 10.0.142.50/32   (Neptune Analytics private endpoint)
Description: Neptune Analytics private endpoint
```

或（推荐）使用 Neptune SG 的安全组 ID 作为目标：
```
Type:        Custom TCP
Port range:  443
Destination: <neptune-sg-id>
```

### 2. Neptune 安全组入站规则

Neptune Analytics graph 的安全组需允许来自 EC2 的流量：

```
Type:        Custom TCP
Port range:  443
Source:      sg-00abc6bc5fbcad128   (EC2 安全组 ID)
```

### 3. 补充 IAM Role 权限

Role: hulftchina-ec2-ssm-role
Account: 522814722466

在 IAM 控制台 -> Roles -> hulftchina-ec2-ssm-role -> Add inline policy：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "neptune-graph:ExecuteQuery",
        "neptune-graph:GetGraph",
        "neptune-graph:GetGraphSummary"
      ],
      "Resource": "arn:aws:neptune-graph:ap-northeast-1:522814722466:graph/g-ci7fl1gkn9"
    }
  ]
}
```

---

## 修复后执行写入

```bash
cd ~/projects/hermes_bedrock_agent

# 验证连通
uv run python -c "
import boto3, json
c = boto3.client('neptune-graph', region_name='ap-northeast-1')
r = c.execute_query(graphIdentifier='g-ci7fl1gkn9',
    queryString='MATCH (n) RETURN count(n) AS total',
    language='OPEN_CYPHER')
print(json.loads(r['payload'].read()))
"

# 正式写入 (511 nodes + 1821 edges)
uv run python scripts/neptune_writer.py

# 验证写入结果
# 预期: Nodes=511, Edges=1821
```

---

## 写入脚本路径

~/projects/hermes_bedrock_agent/scripts/neptune_writer.py

功能:
- MERGE 语义 (幂等，不重复插入)
- Document 节点携带 256-dim embedding 属性
- 错误重试 (ThrottlingException x3, 指数退避)
- 写入前后自动执行 count 验证
- 支持 --dry-run / --skip-edges / --only-edges 参数

---

## 本地文件清单（清理后）

保留:
  ~/hermes_graph_project/data/graph_data.json           (2.0 MB, 511 nodes, 1821 triples)
  ~/hermes_graph_project/data/manifest.json
  ~/hermes_graph_project/data/Murata/semantic_map_output/*.png  (语义图PNG)
  ~/hermes_graph_project/data/Murata/semantic_map_output/*.mmd  (Mermaid源码)
  ~/hermes_graph_project/data/Murata/semantic_map_output/semantic_map_advanced.json
  ~/hermes_graph_project/data/Murata/semantic_map_output/murata_semantic_report.txt

已删除:
  /tmp/murata_docs/           (S3原始下载，38 MB)
  ~/hermes_graph_project/data/Murata/代码_muratapr/
  ~/hermes_graph_project/data/Murata/文档/
  ~/hermes_graph_project/data/Murata/数据库设计/
  ~/hermes_graph_project/data/Murata/操作手册/
  ~/hermes_graph_project/data/extracted/             (中间提取文本)

磁盘占用: 42 MB -> 3.4 MB (释放约 38.6 MB)
