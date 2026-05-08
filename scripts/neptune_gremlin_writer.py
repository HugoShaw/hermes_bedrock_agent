#!/usr/bin/env python3
"""
Neptune Analytics Graph Writer
=================================
将 graph_data.json 中的节点和关系通过 openCypher REST API (SigV4) 写入 Neptune Analytics。

Neptune Analytics 不支持 Gremlin WebSocket，使用 openCypher over HTTPS with SigV4。

IAM 所需权限 (在 IAM Role hulftchina-ec2-ssm-role 中添加):
  neptune-graph:ReadDataViaQuery
  neptune-graph:WriteDataViaQuery
  Resource: arn:aws:neptune-graph:ap-northeast-1:522814722466:graph/g-ci7fl1gkn9

用法:
  uv run python scripts/neptune_gremlin_writer.py [--dry-run] [--count-only]
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import boto3
import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import nest_asyncio
nest_asyncio.apply()

# ── 配置 ──────────────────────────────────────────────────────────────────────
HOST       = "g-ci7fl1gkn9.ap-northeast-1.neptune-graph.amazonaws.com"
PORT       = 8182
REGION     = "ap-northeast-1"
SERVICE    = "neptune-graph"
GRAPH_DATA = Path.home() / "hermes_graph_project/data/graph_data.json"
BATCH_SIZE = 50
SLEEP_BTW  = 0.05   # 批次间隔(秒)

BASE_URL   = f"https://{HOST}:{PORT}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)


# ── SigV4 签名 HTTP 客户端 ────────────────────────────────────────────────────

class NeptuneHTTPClient:
    """openCypher over HTTPS with SigV4 Auth"""

    def __init__(self, dry_run: bool = False):
        self.session = boto3.Session()
        self.creds   = self.session.get_credentials()
        self.dry_run = dry_run
        self._ok     = 0
        self._err    = 0

    def _signed_request(self, path: str, body: str) -> requests.Response:
        url = f"{BASE_URL}{path}"
        req = AWSRequest(
            method="POST",
            url=url,
            data=body,
            headers={"Content-Type": "application/json", "host": HOST},
        )
        SigV4Auth(self.creds, SERVICE, REGION).add_auth(req)
        return requests.post(
            url,
            headers=dict(req.headers),
            data=body,
            timeout=30,
            stream=True,
        )

    def query(self, cypher: str, params: dict | None = None) -> dict | None:
        """执行 openCypher 查询，含重试"""
        if self.dry_run:
            log.debug(f"[DRY-RUN] {cypher[:100]}")
            return {"results": []}

        body_obj = {"query": cypher}
        if params:
            body_obj["parameters"] = params
        body = json.dumps(body_obj)

        for attempt in range(3):
            try:
                r = self._signed_request("/openCypher", body)
                raw = b"".join(r.iter_content(65536)).decode("utf-8")

                if r.status_code == 200:
                    self._ok += 1
                    return json.loads(raw)
                elif r.status_code == 429:
                    wait = 2 ** attempt
                    log.warning(f"Throttled — retrying in {wait}s")
                    time.sleep(wait)
                    continue
                else:
                    log.error(f"HTTP {r.status_code}: {raw[:200]}")
                    self._err += 1
                    return None

            except Exception as e:
                log.error(f"Request error (attempt {attempt+1}/3): {e}")
                if attempt == 2:
                    self._err += 1
                    return None
                time.sleep(1)
        return None

    def count_nodes(self) -> int:
        r = self.query("MATCH (n) RETURN count(n) AS total")
        if r and r.get("results"):
            return r["results"][0].get("total", -1)
        return -1

    def count_edges(self) -> int:
        r = self.query("MATCH ()-[r]->() RETURN count(r) AS total")
        if r and r.get("results"):
            return r["results"][0].get("total", -1)
        return -1

    @property
    def stats(self):
        return {"ok": self._ok, "errors": self._err}


# ── openCypher 安全转义 ───────────────────────────────────────────────────────

def esc(s, maxlen: int = 500) -> str:
    if not isinstance(s, str):
        s = str(s)
    return s.replace("\\", "\\\\").replace("'", "\\'")[:maxlen]


# ── Vertex 写入 ───────────────────────────────────────────────────────────────

def write_vertices(client: NeptuneHTTPClient, nodes: list[dict]) -> int:
    """
    MERGE 节点 — 幂等，不重复插入。
    Document 节点额外存储 embedding (截断到 500 维 JSON 字符串)。
    """
    written = 0
    for i, n in enumerate(nodes):
        nid   = esc(n["id"])
        label = esc(n.get("label", ""))
        ntype = esc(n.get("type", "Unknown"))
        cat   = esc(n.get("category", ""))
        s3p   = esc(n.get("s3_path", ""))

        # 基础 MERGE
        set_clause = (
            f"n.label = '{label}', "
            f"n.type = '{ntype}', "
            f"n.category = '{cat}', "
            f"n.s3_path = '{s3p}'"
        )

        # embedding
        emb = n.get("embedding", [])
        if isinstance(emb, list) and len(emb) > 0:
            emb_str = esc(json.dumps(emb[:256]), maxlen=4000)
            set_clause += f", n.embedding = '{emb_str}'"

        # 额外属性
        for key in ("relative_path", "modified_utc"):
            val = n.get(key, "")
            if val:
                set_clause += f", n.{key} = '{esc(val)}'"
        for key in ("size_kb", "char_count"):
            val = n.get(key, 0)
            if val:
                set_clause += f", n.{key} = {int(val)}"

        cypher = (
            f"MERGE (n {{node_id: '{nid}'}}) "
            f"ON CREATE SET {set_clause} "
            f"ON MATCH  SET {set_clause}"
        )
        client.query(cypher)
        written += 1

        if (i + 1) % 50 == 0:
            log.info(f"  Vertices {i+1}/{len(nodes)}")
            time.sleep(SLEEP_BTW)

    return written


# ── Edge 写入 ────────────────────────────────────────────────────────────────

def write_edges(client: NeptuneHTTPClient, triples: list[dict]) -> int:
    """
    MERGE 边 — 幂等。先 MATCH 两端节点，再 MERGE 关系。
    """
    written = 0
    for i, t in enumerate(triples):
        subj = esc(t["subject"])
        obj  = esc(t["object"])
        pred = t["predicate"].replace(" ", "_").replace("-", "_")
        ev   = esc(t.get("evidence", ""))

        cypher = (
            f"MATCH (s {{node_id: '{subj}'}}), (o {{node_id: '{obj}'}}) "
            f"MERGE (s)-[r:{pred}]->(o) "
            f"ON CREATE SET r.evidence = '{ev}'"
        )
        client.query(cypher)
        written += 1

        if (i + 1) % 100 == 0:
            log.info(f"  Edges {i+1}/{len(triples)}")
            time.sleep(SLEEP_BTW)

    return written


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",    action="store_true")
    parser.add_argument("--count-only", action="store_true", help="只查询节点数，不写入")
    parser.add_argument("--skip-edges", action="store_true")
    args = parser.parse_args()

    # ── 加载数据 ──────────────────────────────────────────────────────────────
    log.info(f"Loading {GRAPH_DATA}")
    g       = json.loads(GRAPH_DATA.read_text(encoding="utf-8"))
    nodes   = g["nodes"]
    triples = g["triples"]
    log.info(f"  {len(nodes)} nodes, {len(triples)} triples")

    # ── 初始化客户端 ──────────────────────────────────────────────────────────
    nc = NeptuneHTTPClient(dry_run=args.dry_run)

    # ── 连接 & 前置计数 ───────────────────────────────────────────────────────
    log.info("Connecting to Neptune Analytics ...")
    if not args.dry_run:
        before_v = nc.count_nodes()
        if before_v == -1:
            log.error(
                "Connection failed!\n"
                "  IAM Role hulftchina-ec2-ssm-role needs:\n"
                "    neptune-graph:ReadDataViaQuery\n"
                "    neptune-graph:WriteDataViaQuery\n"
                "  Resource: arn:aws:neptune-graph:ap-northeast-1:522814722466:graph/g-ci7fl1gkn9"
            )
            sys.exit(1)
        before_e = nc.count_edges()
        log.info(f"  Current graph: {before_v} nodes, {before_e} edges")

        if args.count_only:
            print(f"\ng.V().count() = {before_v}")
            print(f"g.E().count() = {before_e}")
            return
    else:
        before_v = before_e = 0
        log.info("  [DRY-RUN] skipping connection check")

    # ── 写入 Vertex ───────────────────────────────────────────────────────────
    log.info(f"Writing {len(nodes)} vertices ...")
    t0 = time.time()
    v_written = write_vertices(nc, nodes)
    log.info(f"  Done: {v_written} vertices in {time.time()-t0:.1f}s")

    # ── 写入 Edge ─────────────────────────────────────────────────────────────
    if not args.skip_edges:
        log.info(f"Writing {len(triples)} edges ...")
        t0 = time.time()
        e_written = write_edges(nc, triples)
        log.info(f"  Done: {e_written} edges in {time.time()-t0:.1f}s")

    # ── 验证 ──────────────────────────────────────────────────────────────────
    if not args.dry_run:
        log.info("Verifying ...")
        after_v = nc.count_nodes()
        after_e = nc.count_edges()

        print()
        print("=" * 60)
        print("  NEPTUNE WRITE COMPLETE")
        print("=" * 60)
        print(f"  Graph   : {HOST}")
        print(f"  Protocol: openCypher HTTPS + SigV4")
        print()
        print(f"  g.V().count()  before: {before_v:>6}  after: {after_v:>6}  (+{after_v-before_v})")
        print(f"  g.E().count()  before: {before_e:>6}  after: {after_e:>6}  (+{after_e-before_e})")
        print()
        print(f"  API calls OK   : {nc.stats['ok']}")
        print(f"  API errors     : {nc.stats['errors']}")
        print("=" * 60)

        # 节点类型分布
        print()
        print("-- Node type distribution --")
        r = nc.query("MATCH (n) RETURN n.type AS type, count(*) AS cnt ORDER BY cnt DESC LIMIT 15")
        if r and r.get("results"):
            for row in r["results"]:
                print(f"  {str(row.get('type','?')):25s}  {row.get('cnt',0):5d}")

        # 关系类型分布
        print()
        print("-- Relationship type distribution --")
        r2 = nc.query("MATCH ()-[r]->() RETURN type(r) AS rel, count(*) AS cnt ORDER BY cnt DESC LIMIT 10")
        if r2 and r2.get("results"):
            for row in r2["results"]:
                print(f"  {str(row.get('rel','?')):30s}  {row.get('cnt',0):5d}")
    else:
        print("\n[DRY-RUN COMPLETE] No data written.")


if __name__ == "__main__":
    main()
