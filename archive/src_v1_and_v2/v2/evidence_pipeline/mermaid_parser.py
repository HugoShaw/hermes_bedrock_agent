"""
Mermaid parser — .mmd/.mermaid ファイルを解析してグラフ構造を抽出する。

サポートするグラフ種別:
  graph TD, graph LR, flowchart TD, flowchart LR

出力:
  - mermaid_files.jsonl   … ファイルメタデータ
  - mermaid_graphs.jsonl  … グラフ定義
  - mermaid_nodes.jsonl   … ノード定義
  - mermaid_edges.jsonl   … エッジ定義
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---- regex patterns ---------------------------------------------------

# グラフ宣言行: graph TD / flowchart LR / sequenceDiagram etc.
_RE_GRAPH_DECL = re.compile(
    r"^\s*(graph|flowchart)\s+(TD|LR|BT|RL|TB)\b",
    re.IGNORECASE,
)
_RE_SEQUENCE_DECL = re.compile(r"^\s*sequenceDiagram\b", re.IGNORECASE)
_RE_CLASS_DECL = re.compile(r"^\s*classDiagram\b", re.IGNORECASE)
_RE_ER_DECL = re.compile(r"^\s*erDiagram\b", re.IGNORECASE)
_RE_GANTT_DECL = re.compile(r"^\s*gantt\b", re.IGNORECASE)
_RE_MINDMAP_DECL = re.compile(r"^\s*mindmap\b", re.IGNORECASE)

# ノード定義パターン (flowchart/graph 内)
# A[label]  A(label)  A{label}  A((label))  A>label]  A([label])
_RE_NODE = re.compile(
    r"""
    (?:^|\s)                         # 行頭か空白
    ([A-Za-z0-9_\-]+)                # ノードID
    (?:
        \[\[([^\]]*)\]\]             # A[[label]] — subroutine
      | \(\(([^)]*)\)\)             # A((label)) — circle
      | \(\[([^\]]*)\]\)            # A([label]) — stadium
      | \[([^\]]*)\]                # A[label]   — rect
      | \(([^)]*)\)                 # A(label)   — rounded
      | \{([^}]*)\}                 # A{label}   — diamond
      | >([^\]]*)\]                 # A>label]   — asymmetric
    )
    """,
    re.VERBOSE,
)

# エッジパターン
# A --> B
# A -->|label| B
# A -- text --> B
# A --- B
# A -.-> B
# A ==> B
_RE_EDGE = re.compile(
    r"""
    ^\s*
    ([A-Za-z0-9_\-]+)                              # from ID
    \s*
    (?:--\s*([^->\|]+?)\s*-->|                     # A -- text --> B
       -\.->|-->|==>|---|-\.-|~~>|--x|--o)        # arrow types
    \|([^\|]*)\|\s*                                # optional |label|
    ([A-Za-z0-9_\-]+)                              # to ID
    """,
    re.VERBOSE,
)

# Simpler edge pattern to capture all variants
_RE_EDGE_SIMPLE = re.compile(
    r"^\s*"
    r"([A-Za-z0-9_\-]+)"               # from
    r"\s*"
    r"(?:--[>x o]?-*[>x o]?|==+>?|-\.->|~~>)"  # arrow
    r"\s*"
    r"(?:\|([^\|]*)\|)?"               # optional |label|
    r"\s*"
    r"([A-Za-z0-9_\-]+)"               # to
)

# A -- text --> B  (labeled undirected to directed)
_RE_EDGE_LABELED = re.compile(
    r"^\s*([A-Za-z0-9_\-]+)\s+--\s+(.+?)\s+-->\s+([A-Za-z0-9_\-]+)"
)

# subgraph label
_RE_SUBGRAPH = re.compile(r"^\s*subgraph\s+(.*)", re.IGNORECASE)


class MermaidParser:
    """Mermaid ファイルを解析してグラフ構造を抽出するパーサー。

    Parameters
    ----------
    dataset, run_id:
        パイプライン識別子。
    """

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_evidence_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def parse_files(
        self,
        file_paths: list[str],
        workbook_records: list[dict[str, Any]] | None = None,
        source_s3_uris: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """複数の Mermaid ファイルを解析する。

        Parameters
        ----------
        file_paths:
            ローカルの .mmd/.mermaid ファイルパスのリスト。
        workbook_records:
            excel_parser が返したワークブックレコード (ファイル名マッチング用)。
        source_s3_uris:
            {local_path: s3_uri} マッピング。

        Returns
        -------
        dict with keys: file_records, graph_records, node_records, edge_records
        """
        source_s3_uris = source_s3_uris or {}
        workbook_records = workbook_records or []
        wb_names = {Path(wb["file_name"]).stem.lower() for wb in workbook_records}

        file_records: list[dict[str, Any]] = []
        graph_records: list[dict[str, Any]] = []
        node_records: list[dict[str, Any]] = []
        edge_records: list[dict[str, Any]] = []

        for file_path in file_paths:
            path = Path(file_path)
            if not path.exists():
                logger.warning("Mermaid file not found: %s", file_path)
                continue

            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.error("Failed to read %s: %s", file_path, exc)
                continue

            s3_uri = source_s3_uris.get(file_path, "")
            associated_wb = _find_associated_workbook(path.stem, wb_names)

            file_rec, graphs, nodes, edges = self._parse_source(
                source=source,
                file_path=str(path),
                s3_uri=s3_uri,
                associated_wb=associated_wb,
            )
            file_records.append(file_rec)
            graph_records.extend(graphs)
            node_records.extend(nodes)
            edge_records.extend(edges)

        logger.info(
            "Mermaid parse: %d files → %d graphs, %d nodes, %d edges",
            len(file_records), len(graph_records), len(node_records), len(edge_records),
        )
        return {
            "file_records": file_records,
            "graph_records": graph_records,
            "node_records": node_records,
            "edge_records": edge_records,
        }

    def _parse_source(
        self,
        source: str,
        file_path: str,
        s3_uri: str,
        associated_wb: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """1ファイル分の Mermaid ソースを解析する。"""
        path = Path(file_path)
        graph_type = _detect_graph_type(source)
        lines = source.splitlines()
        line_count = len(lines)

        file_id = _fid(self.dataset, file_path)
        file_rec: dict[str, Any] = {
            "file_id": file_id,
            "dataset": self.dataset,
            "run_id": self.run_id,
            "source_file": file_path,
            "source_s3_uri": s3_uri,
            "file_name": path.name,
            "file_stem": path.stem,
            "extension": path.suffix.lower(),
            "graph_type": graph_type,
            "line_count": line_count,
            "associated_workbook": associated_wb,
        }

        if graph_type in ("flowchart", "graph"):
            nodes, edges = _parse_flowchart(lines, file_id, self.dataset, self.run_id, file_path, s3_uri)
        else:
            nodes, edges = [], []

        graph_id = _gid(file_id, graph_type)
        graph_rec: dict[str, Any] = {
            "graph_id": graph_id,
            "file_id": file_id,
            "dataset": self.dataset,
            "run_id": self.run_id,
            "source_file": file_path,
            "source_s3_uri": s3_uri,
            "file_name": path.name,
            "graph_type": graph_type,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "mermaid_source": source,
            "associated_workbook": associated_wb,
        }

        return file_rec, [graph_rec], nodes, edges

    def write_jsonl(
        self,
        file_records: list[dict[str, Any]],
        graph_records: list[dict[str, Any]],
        node_records: list[dict[str, Any]],
        edge_records: list[dict[str, Any]],
        output_dir: str,
    ) -> dict[str, str]:
        """各レコードをJSONLファイルに書き出す。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths: dict[str, str] = {}

        for records, filename in [
            (file_records, "mermaid_files.jsonl"),
            (graph_records, "mermaid_graphs.jsonl"),
            (node_records, "mermaid_nodes.jsonl"),
            (edge_records, "mermaid_edges.jsonl"),
        ]:
            p = str(out / filename)
            with open(p, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            logger.info("Wrote %d records → %s", len(records), p)
            paths[filename.replace(".jsonl", "_path")] = p

        return paths


# ---- flowchart/graph parser ------------------------------------------

def _parse_flowchart(
    lines: list[str],
    file_id: str,
    dataset: str,
    run_id: str,
    source_file: str,
    s3_uri: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """flowchart / graph 宣言以降の行を解析してノードとエッジを返す。"""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    in_graph = False
    subgraph_stack: list[str] = []

    for line_num, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue

        # グラフ宣言行を検出
        if _RE_GRAPH_DECL.match(line):
            in_graph = True
            continue
        if not in_graph:
            continue

        # subgraph 追跡
        sg_m = _RE_SUBGRAPH.match(line)
        if sg_m:
            subgraph_stack.append(sg_m.group(1).strip())
            continue
        if line.lower() == "end":
            if subgraph_stack:
                subgraph_stack.pop()
            continue

        current_subgraph = subgraph_stack[-1] if subgraph_stack else ""

        # エッジ検出 (ノードより先に試みる)
        edge = _try_parse_edge(line, file_id, dataset, run_id, source_file, s3_uri, line_num)
        if edge:
            edges.append(edge)
            # エッジ端点をノードとして登録 (ラベルなし)
            for nid in (edge["from_id"], edge["to_id"]):
                if nid not in nodes:
                    nodes[nid] = _make_node(nid, nid, "inferred", file_id, dataset, run_id, source_file, s3_uri, current_subgraph)
            continue

        # ノード定義
        for m in _RE_NODE.finditer(raw_line):
            nid = m.group(1)
            # グループ 2-8 のうち最初に一致したものをラベルとする
            label = next((m.group(i) for i in range(2, 9) if m.group(i) is not None), nid)
            shape = _infer_shape(m)
            if nid not in nodes:
                nodes[nid] = _make_node(nid, label, shape, file_id, dataset, run_id, source_file, s3_uri, current_subgraph)

    # 重複エッジを除去
    seen_edges: set[str] = set()
    deduped_edges: list[dict[str, Any]] = []
    for e in edges:
        key = f"{e['from_id']}->{e['to_id']}:{e['edge_label']}"
        if key not in seen_edges:
            seen_edges.add(key)
            deduped_edges.append(e)

    return list(nodes.values()), deduped_edges


def _try_parse_edge(
    line: str,
    file_id: str,
    dataset: str,
    run_id: str,
    source_file: str,
    s3_uri: str,
    line_num: int,
) -> dict[str, Any] | None:
    # A -- text --> B
    m = _RE_EDGE_LABELED.match(line)
    if m:
        return _make_edge(m.group(1), m.group(3), m.group(2).strip(), file_id, dataset, run_id, source_file, s3_uri, line_num)

    # A -->|label| B  or  A --> B
    m = _RE_EDGE_SIMPLE.match(line)
    if m:
        return _make_edge(m.group(1), m.group(3), m.group(2) or "", file_id, dataset, run_id, source_file, s3_uri, line_num)

    return None


def _make_node(
    node_id: str,
    label: str,
    shape: str,
    file_id: str,
    dataset: str,
    run_id: str,
    source_file: str,
    s3_uri: str,
    subgraph: str,
) -> dict[str, Any]:
    raw = f"node:{file_id}:{node_id}"
    rec_id = "nd_" + hashlib.sha256(raw.encode()).hexdigest()[:16]
    return {
        "node_record_id": rec_id,
        "file_id": file_id,
        "dataset": dataset,
        "run_id": run_id,
        "source_file": source_file,
        "source_s3_uri": s3_uri,
        "node_id": node_id,
        "label": label,
        "shape": shape,
        "subgraph": subgraph,
    }


def _make_edge(
    from_id: str,
    to_id: str,
    label: str,
    file_id: str,
    dataset: str,
    run_id: str,
    source_file: str,
    s3_uri: str,
    line_num: int,
) -> dict[str, Any]:
    raw = f"edge:{file_id}:{from_id}:{to_id}:{label}:{line_num}"
    rec_id = "ed_" + hashlib.sha256(raw.encode()).hexdigest()[:16]
    return {
        "edge_record_id": rec_id,
        "file_id": file_id,
        "dataset": dataset,
        "run_id": run_id,
        "source_file": source_file,
        "source_s3_uri": s3_uri,
        "from_id": from_id,
        "to_id": to_id,
        "edge_label": label,
        "line_number": line_num,
    }


def _infer_shape(m: re.Match) -> str:
    """正規表現マッチからノードシェイプを推定する。"""
    shapes = ["subroutine", "circle", "stadium", "rect", "rounded", "diamond", "asymmetric"]
    for i, shape in enumerate(shapes):
        if m.group(i + 2) is not None:
            return shape
    return "unknown"


# ---- graph type detection --------------------------------------------

def _detect_graph_type(source: str) -> str:
    for line in source.splitlines():
        if _RE_GRAPH_DECL.match(line):
            return "flowchart" if "flowchart" in line.lower() else "graph"
        if _RE_SEQUENCE_DECL.match(line):
            return "sequence"
        if _RE_CLASS_DECL.match(line):
            return "class"
        if _RE_ER_DECL.match(line):
            return "er"
        if _RE_GANTT_DECL.match(line):
            return "gantt"
        if _RE_MINDMAP_DECL.match(line):
            return "mindmap"
    return "unknown"


# ---- workbook association -------------------------------------------

def _find_associated_workbook(file_stem: str, wb_stems: set[str]) -> str:
    stem_lower = file_stem.lower()
    for wb in wb_stems:
        if wb in stem_lower or stem_lower in wb:
            return wb
    return ""


# ---- ID helpers -----------------------------------------------------

def _fid(dataset: str, file_path: str) -> str:
    raw = f"mmd:{dataset}:{file_path}"
    return "mf_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _gid(file_id: str, graph_type: str) -> str:
    raw = f"graph:{file_id}:{graph_type}"
    return "mg_" + hashlib.sha256(raw.encode()).hexdigest()[:16]
