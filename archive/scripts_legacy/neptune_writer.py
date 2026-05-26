#!/usr/bin/env python3
"""
Neptune Analytics Graph Writer
================================
将 graph_data.json 中的节点和关系写入 Neptune Analytics (Amazon Neptune Analytics)

连接方式: Neptune Analytics SDK (boto3 neptune-graph) via execute_query (openCypher)
端点类型: Private Graph Endpoint (VPC 内部) — 需要 SG 放行及 IAM 权限

IAM 所需权限:
  neptune-graph:ExecuteQuery  on  arn:aws:neptune-graph:...:graph/g-ci7fl1gkn9
  neptune-graph:GetGraphSummary (可选，用于验证)

安全组要求:
  EC2 安全组出站规则需允许访问 Neptune Analytics private endpoint (10.0.142.50:443)

用法:
  uv run python scripts/neptune_writer.py [--dry-run] [--batch-size 50]
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import boto3
import botocore.exceptions

# ── 配置 ──────────────────────────────────────────────────────────────────────
GRAPH_ID       = "g-ci7fl1gkn9"
REGION         = "ap-northeast-1"
GRAPH_DATA     = Path.home() / "hermes_graph_project/data/graph_data.json"
DEFAULT_BATCH  = 50        # 每批 openCypher UNWIND 语句的节点/边数量
SLEEP_BETWEEN  = 0.1       # 批次间休眠（避免节流）
MAX_LABEL_LEN  = 256       # 截断过长的标签/属性

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)


# ── openCypher 辅助 ───────────────────────────────────────────────────────────

def cypher_str(s: str) -> str:
    """转义 openCypher 字符串中的特殊字符"""
    if not isinstance(s, str):
        s = str(s)
    return s.replace("\\", "\\\\").replace("'", "\\'")[:MAX_LABEL_LEN]


# ── Neptune 客户端 ─────────────────────────────────────────────────────────────

class NeptuneClient:
    def __init__(self, graph_id: str, region: str, dry_run: bool = False):
        self.graph_id = graph_id
        self.dry_run  = dry_run
        self.client   = boto3.client("neptune-graph", region_name=region)
        self._ok  = 0
        self._err = 0

    def run(self, query: str, params: dict | None = None) -> dict | None:
        """执行 openCypher 查询，含重试 + 去重逻辑"""
        if self.dry_run:
            log.debug(f"[DRY-RUN] {query[:120]}")
            return {"results": []}

        for attempt in range(3):
            try:
                kwargs: dict = dict(
                    graphIdentifier=self.graph_id,
                    queryString=query,
                    language="OPEN_CYPHER",
                )
                if params:
                    kwargs["parameters"] = json.dumps(params)

                resp = self.client.execute_query(**kwargs)
                body = json.loads(resp["payload"].read())
                self._ok += 1
                return body

            except botocore.exceptions.ClientError as e:
                code = e.response["Error"]["Code"]
                if code == "ThrottlingException":
                    wait = 2 ** attempt
                    log.warning(f"Throttled — sleeping {wait}s (attempt {attempt+1}/3)")
                    time.sleep(wait)
                elif code == "ConflictException":
                    # 重复写入，忽略
                    self._ok += 1
                    return None
                else:
                    log.error(f"ClientError {code}: {e}")
                    self._err += 1
                    return None
            except Exception as e:
                log.error(f"Unexpected error (attempt {attempt+1}/3): {e}")
                if attempt == 2:
                    self._err += 1
                    return None
                time.sleep(1)
        return None

    def count_nodes(self) -> int:
        r = self.run("MATCH (n) RETURN count(n) AS total")
        if r and r.get("results"):
            return r["results"][0].get("total", 0)
        return -1

    def count_edges(self) -> int:
        r = self.run("MATCH ()-[r]->() RETURN count(r) AS total")
        if r and r.get("results"):
            return r["results"][0].get("total", 0)
        return -1

    @property
    def stats(self):
        return {"ok": self._ok, "errors": self._err}


# ── Vertex 写入 ───────────────────────────────────────────────────────────────

def write_vertices_batch(client: NeptuneClient, nodes: list[dict]) -> int:
    """
    使用 UNWIND 批量 MERGE 节点（MERGE 保证幂等，不会重复插入）
    Document 节点额外携带 embedding（存为 JSON 字符串）
    """
    written = 0
    batch_size = DEFAULT_BATCH

    for i in range(0, len(nodes), batch_size):
        chunk = nodes[i : i + batch_size]

        # 分两类：有 embedding 的 Document，以及普通实体节点
        plain_nodes  = [n for n in chunk if not isinstance(n.get("embedding"), list)
                        or len(n.get("embedding", [])) == 0]
        embed_nodes  = [n for n in chunk if isinstance(n.get("embedding"), list)
                        and len(n["embedding"]) == 256]

        # ── 普通节点 MERGE ────────────────────────────────────────────────
        if plain_nodes:
            clauses = []
            for n in plain_nodes:
                nid   = cypher_str(n["id"])
                label = cypher_str(n.get("label", ""))
                ntype = cypher_str(n.get("type",  "Unknown"))
                props_extra = ""
                if n.get("category"):
                    props_extra += f", category: '{cypher_str(n['category'])}'"
                if n.get("s3_path"):
                    props_extra += f", s3_path: '{cypher_str(n['s3_path'])}'"
                clauses.append(
                    f"MERGE (v {{node_id: '{nid}'}}) "
                    f"ON CREATE SET v.label = '{label}', v.type = '{ntype}'"
                    f"{props_extra}"
                )
            # Neptune Analytics 不支持多语句，逐条执行
            for stmt in clauses:
                client.run(stmt)
            written += len(plain_nodes)

        # ── 带 embedding 的 Document 节点 ────────────────────────────────
        for n in embed_nodes:
            nid     = cypher_str(n["id"])
            label   = cypher_str(n.get("label", ""))
            ntype   = cypher_str(n.get("type", "Document"))
            cat     = cypher_str(n.get("category", ""))
            s3path  = cypher_str(n.get("s3_path", ""))
            rel_path= cypher_str(n.get("relative_path", ""))
            size_kb = n.get("size_kb", 0)
            chars   = n.get("char_count", 0)
            mod     = cypher_str(n.get("modified_utc", ""))
            # embedding 存为 JSON 字符串 (Neptune Analytics 支持 list 属性)
            emb_json = json.dumps(n["embedding"])

            stmt = (
                f"MERGE (v {{node_id: '{nid}'}}) "
                f"ON CREATE SET "
                f"  v.label = '{label}', "
                f"  v.type = '{ntype}', "
                f"  v.category = '{cat}', "
                f"  v.s3_path = '{s3path}', "
                f"  v.relative_path = '{rel_path}', "
                f"  v.size_kb = {size_kb}, "
                f"  v.char_count = {chars}, "
                f"  v.modified_utc = '{mod}', "
                f"  v.embedding = '{emb_json[:8000]}' "   # 截断防超长
                f"ON MATCH SET "
                f"  v.label = '{label}', "
                f"  v.embedding = '{emb_json[:8000]}'"
            )
            client.run(stmt)
            written += 1

        log.info(f"  Vertices {min(i+batch_size, len(nodes))}/{len(nodes)} written")
        time.sleep(SLEEP_BETWEEN)

    return written


# ── Edge 写入 ────────────────────────────────────────────────────────────────

def write_edges_batch(client: NeptuneClient, triples: list[dict]) -> int:
    """
    MERGE 边（MERGE on node_id → MERGE edge 保证幂等）
    只处理 predicate != CONTAINS_ENTITY 的跨文档关系，以及全部关系（可选）
    """
    written = 0

    for i, t in enumerate(triples):
        subj  = cypher_str(t["subject"])
        obj   = cypher_str(t["object"])
        pred  = t["predicate"].replace(" ", "_").replace("-", "_")
        ev    = cypher_str(t.get("evidence", ""))

        # MERGE edge via matched nodes (幂等)
        stmt = (
            f"MATCH (s {{node_id: '{subj}'}}), (o {{node_id: '{obj}'}}) "
            f"MERGE (s)-[r:{pred}]->(o) "
            f"ON CREATE SET r.evidence = '{ev}'"
        )
        client.run(stmt)
        written += 1

        if (i + 1) % 200 == 0:
            log.info(f"  Edges {i+1}/{len(triples)} written")
            time.sleep(SLEEP_BETWEEN)

    return written


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Write graph_data.json to Neptune Analytics")
    parser.add_argument("--dry-run",    action="store_true", help="Print queries, no execution")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--skip-edges", action="store_true", help="Only write vertices")
    parser.add_argument("--only-edges", action="store_true", help="Only write edges (vertices must exist)")
    args = parser.parse_args()

    batch_size = args.batch_size

    # ── 加载数据 ──────────────────────────────────────────────────────────────
    log.info(f"Loading {GRAPH_DATA} ...")
    g = json.loads(GRAPH_DATA.read_text(encoding="utf-8"))
    nodes   = g["nodes"]
    triples = g["triples"]
    log.info(f"Loaded {len(nodes)} nodes, {len(triples)} triples")

    # ── 初始化客户端 ──────────────────────────────────────────────────────────
    nc = NeptuneClient(GRAPH_ID, REGION, dry_run=args.dry_run)

    # ── 连接检查 ──────────────────────────────────────────────────────────────
    log.info("Checking Neptune connection ...")
    if not args.dry_run:
        before_nodes = nc.count_nodes()
        before_edges = nc.count_edges()
        if before_nodes == -1:
            log.error(
                "Cannot connect to Neptune Analytics!\n"
                "  Checklist:\n"
                "  [1] IAM Role needs: neptune-graph:ExecuteQuery on graph/g-ci7fl1gkn9\n"
                "  [2] EC2 SG (sg-00abc6bc5fbcad128) egress must allow TCP/443 to 10.0.142.50\n"
                "  [3] Neptune private endpoint must exist in VPC vpc-02a1ca09a0b51966e\n"
                "  [4] Neptune SG must allow ingress TCP/443 from EC2 SG\n"
                "  Current: endpoint 10.0.142.50:443 is BLOCKED (nc test timed out)"
            )
            sys.exit(1)
        log.info(f"  Before write — Nodes: {before_nodes}, Edges: {before_edges}")
    else:
        log.info("  [DRY-RUN] Skipping connection check")
        before_nodes = before_edges = 0

    # ── 写入节点 ──────────────────────────────────────────────────────────────
    if not args.only_edges:
        log.info(f"Writing {len(nodes)} vertices ...")
        t0 = time.time()
        v_written = write_vertices_batch(nc, nodes)
        log.info(f"Vertices done: {v_written} written in {time.time()-t0:.1f}s")

    # ── 写入边 ────────────────────────────────────────────────────────────────
    if not args.skip_edges:
        log.info(f"Writing {len(triples)} edges ...")
        t0 = time.time()
        e_written = write_edges_batch(nc, triples)
        log.info(f"Edges done: {e_written} written in {time.time()-t0:.1f}s")

    # ── 验证 ──────────────────────────────────────────────────────────────────
    if not args.dry_run:
        log.info("Verifying ...")
        after_nodes = nc.count_nodes()
        after_edges = nc.count_edges()

        print()
        print("=" * 60)
        print(" NEPTUNE WRITE COMPLETE")
        print("=" * 60)
        print(f"  Graph ID       : {GRAPH_ID}")
        print(f"  Region         : {REGION}")
        print()
        print(f"  Nodes before   : {before_nodes}")
        print(f"  Nodes after    : {after_nodes}")
        print(f"  Net new nodes  : {after_nodes - before_nodes}")
        print()
        print(f"  Edges before   : {before_edges}")
        print(f"  Edges after    : {after_edges}")
        print(f"  Net new edges  : {after_edges - before_edges}")
        print()
        print(f"  API calls OK   : {nc.stats['ok']}")
        print(f"  API errors     : {nc.stats['errors']}")
        print("=" * 60)

        # sample query output
        print()
        print("-- Sample: MATCH (n) RETURN n.type, count(*) as cnt --")
        r = nc.run("MATCH (n) RETURN n.type AS type, count(*) AS cnt ORDER BY cnt DESC")
        if r and r.get("results"):
            for row in r["results"][:10]:
                print(f"  {str(row.get('type','?')):20s}  {row.get('cnt',0):5d}")

        print()
        print("-- Sample: top relationships --")
        r2 = nc.run("MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt ORDER BY cnt DESC LIMIT 10")
        if r2 and r2.get("results"):
            for row in r2["results"]:
                print(f"  {str(row.get('rel','?')):30s}  {row.get('cnt',0):5d}")
    else:
        print()
        print("[DRY-RUN COMPLETE] No data was written to Neptune.")
        print("Queries were generated and logged (use --verbose to see all).")


if __name__ == "__main__":
    main()
