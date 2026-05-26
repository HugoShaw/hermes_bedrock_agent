"""
Excel OOXML visual parser — xl/drawings/ のXMLからシェイプ・コネクター・チャートを抽出する。

出力:
  - drawing_objects.jsonl  … テキストを含むシェイプ
  - connectors.jsonl       … コネクター・矢印 (from/toアンカー付き)
  - chart_objects.jsonl    … チャート参照
"""
from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

_NS = {
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}

_REL_DRAWING = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
_REL_CHART = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart"


class ExcelOOXMLVisualParser:
    """OOXMLのdrawing XMLからビジュアルオブジェクトを抽出するパーサー。"""

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_evidence_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def parse_workbook(
        self,
        file_path: str,
        sheet_records: list[dict[str, Any]],
        prescan_records: list[dict[str, Any]],
        source_s3_uri: str = "",
    ) -> dict[str, Any]:
        """ワークブック内の全drawingを解析する。

        Returns
        -------
        dict with keys: drawing_objects, connectors, chart_objects
        """
        path = Path(file_path)
        drawing_objects: list[dict[str, Any]] = []
        connectors: list[dict[str, Any]] = []
        chart_objects: list[dict[str, Any]] = []

        if not zipfile.is_zipfile(file_path):
            logger.warning("Not a ZIP/OOXML file: %s", file_path)
            return {"drawing_objects": [], "connectors": [], "chart_objects": []}

        # prescan_records をシートIDでインデックス化
        prescan_by_sheet_id = {r["sheet_id"]: r for r in prescan_records}
        sheet_by_idx = {r["sheet_index"]: r for r in sheet_records}

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                zip_names = set(zf.namelist())
                sheet_drawing_map = _build_sheet_drawing_map(zf, zip_names)

                for sheet_idx, sheet_rec in enumerate(sheet_records):
                    sheet_key = f"sheet{sheet_idx + 1}"
                    drawing_paths = sheet_drawing_map.get(sheet_key, [])
                    prescan = prescan_by_sheet_id.get(sheet_rec["sheet_id"], {})

                    for drawing_path in drawing_paths:
                        if drawing_path not in zip_names:
                            continue
                        try:
                            xml_data = zf.read(drawing_path)
                        except KeyError:
                            continue

                        # drawing XML の rel ファイルを読んでチャートR_ID→パスを解決
                        rel_path = _drawing_rel_path(drawing_path)
                        chart_rel_map: dict[str, str] = {}
                        if rel_path in zip_names:
                            try:
                                chart_rel_map = _parse_chart_rels(zf.read(rel_path))
                            except Exception:
                                pass

                        d_objs, d_conns, d_charts = _parse_drawing_xml(
                            xml_data=xml_data,
                            chart_rel_map=chart_rel_map,
                            sheet_rec=sheet_rec,
                            drawing_path=drawing_path,
                            dataset=self.dataset,
                            run_id=self.run_id,
                            source_file=str(path),
                            source_s3_uri=source_s3_uri,
                        )
                        drawing_objects.extend(d_objs)
                        connectors.extend(d_conns)
                        chart_objects.extend(d_charts)
        except (zipfile.BadZipFile, ET.ParseError) as exc:
            logger.error("OOXML visual parse failed for %s: %s", file_path, exc)

        logger.info(
            "OOXML parse %s: %d shapes, %d connectors, %d charts",
            path.name, len(drawing_objects), len(connectors), len(chart_objects),
        )
        return {
            "drawing_objects": drawing_objects,
            "connectors": connectors,
            "chart_objects": chart_objects,
        }

    def write_jsonl(
        self,
        drawing_objects: list[dict[str, Any]],
        connectors: list[dict[str, Any]],
        chart_objects: list[dict[str, Any]],
        output_dir: str,
    ) -> dict[str, str]:
        """各レコードをJSONLファイルに書き出す。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths: dict[str, str] = {}

        for records, filename in [
            (drawing_objects, "drawing_objects.jsonl"),
            (connectors, "connectors.jsonl"),
            (chart_objects, "chart_objects.jsonl"),
        ]:
            p = str(out / filename)
            with open(p, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
            logger.info("Wrote %d records → %s", len(records), p)
            paths[filename.replace(".jsonl", "_path")] = p

        return paths


# ---- XML parsing helpers ----------------------------------------------

def _parse_drawing_xml(
    xml_data: bytes,
    chart_rel_map: dict[str, str],
    sheet_rec: dict[str, Any],
    drawing_path: str,
    dataset: str,
    run_id: str,
    source_file: str,
    source_s3_uri: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """drawing XMLを解析してシェイプ・コネクター・チャートを抽出する。"""
    try:
        root = ET.fromstring(xml_data)
    except ET.ParseError as exc:
        logger.debug("XML parse error in %s: %s", drawing_path, exc)
        return [], [], []

    drawing_objects: list[dict[str, Any]] = []
    connectors: list[dict[str, Any]] = []
    chart_objects: list[dict[str, Any]] = []

    sheet_id = sheet_rec["sheet_id"]
    workbook_id = sheet_rec["workbook_id"]
    base_meta = {
        "dataset": dataset,
        "run_id": run_id,
        "source_file": source_file,
        "source_s3_uri": source_s3_uri,
        "workbook_name": sheet_rec.get("workbook_name", ""),
        "sheet_name": sheet_rec["sheet_name"],
        "sheet_index": sheet_rec["sheet_index"],
        "sheet_id": sheet_id,
        "workbook_id": workbook_id,
        "drawing_xml_path": drawing_path,
    }

    xdr = _NS["xdr"]
    a_ns = _NS["a"]

    # --- シェイプ (sp) ---
    for sp in root.iter(f"{{{xdr}}}sp"):
        anchor = _extract_anchor(sp)
        text = _extract_text(sp, a_ns)
        shape_type = _infer_shape_type(sp, xdr)
        obj_id = _gen_id("dobj", sheet_id, drawing_path, str(anchor.get("from", "")), text[:50])
        rec = {
            "object_id": obj_id,
            "object_type": "shape",
            "shape_type": shape_type,
            "text": text,
            "anchor": anchor,
            **base_meta,
        }
        drawing_objects.append(rec)

    # --- コネクター (cxnSp) ---
    for cxn in root.iter(f"{{{xdr}}}cxnSp"):
        from_anchor = _extract_anchor_from_element(cxn, f"{{{xdr}}}from")
        to_anchor = _extract_anchor_from_element(cxn, f"{{{xdr}}}to")
        cxn_id = cxn.find(f".//{{{xdr}}}cNvPr")
        cxn_name = cxn_id.get("name", "") if cxn_id is not None else ""
        obj_id = _gen_id("conn", sheet_id, drawing_path, str(from_anchor), str(to_anchor))
        rec = {
            "connector_id": obj_id,
            "connector_name": cxn_name,
            "from_anchor": from_anchor,
            "to_anchor": to_anchor,
            **base_meta,
        }
        connectors.append(rec)

    # --- グラフィックフレーム (graphicFrame → chart) ---
    for gf in root.iter(f"{{{xdr}}}graphicFrame"):
        anchor = _extract_anchor(gf)
        chart_ref = gf.find(f".//{{{_NS['c']}}}chart")
        if chart_ref is None:
            continue
        r_id = chart_ref.get(f"{{{_NS['r']}}}id", "")
        chart_path = chart_rel_map.get(r_id, "")
        obj_id = _gen_id("chart", sheet_id, drawing_path, r_id)
        rec = {
            "chart_id": obj_id,
            "chart_rel_id": r_id,
            "chart_xml_path": chart_path,
            "anchor": anchor,
            **base_meta,
        }
        chart_objects.append(rec)

    return drawing_objects, connectors, chart_objects


def _extract_anchor(elem: ET.Element) -> dict[str, Any]:
    """シェイプのアンカー座標を抽出する。"""
    xdr = _NS["xdr"]
    from_elem = elem.find(f"{{{xdr}}}from")
    to_elem = elem.find(f"{{{xdr}}}to")
    return {
        "from": _parse_cell_anchor(from_elem),
        "to": _parse_cell_anchor(to_elem),
    }


def _extract_anchor_from_element(parent: ET.Element, tag: str) -> dict[str, Any]:
    elem = parent.find(tag)
    return _parse_cell_anchor(elem)


def _parse_cell_anchor(elem: Any) -> dict[str, Any]:
    if elem is None:
        return {}
    xdr = _NS["xdr"]
    col_elem = elem.find(f"{{{xdr}}}col")
    row_elem = elem.find(f"{{{xdr}}}row")
    return {
        "col": int(col_elem.text or 0) if col_elem is not None else None,
        "row": int(row_elem.text or 0) if row_elem is not None else None,
    }


def _extract_text(elem: ET.Element, a_ns: str) -> str:
    """シェイプ内の全テキストを結合して返す。"""
    parts: list[str] = []
    for t in elem.iter(f"{{{a_ns}}}t"):
        if t.text:
            parts.append(t.text)
    return "".join(parts).strip()


def _infer_shape_type(sp: ET.Element, xdr: str) -> str:
    """cNvSpPr 属性からシェイプ種別を推定する。"""
    cNvSpPr = sp.find(f".//{{{xdr}}}cNvSpPr")
    if cNvSpPr is not None:
        if cNvSpPr.get("txBox") == "1":
            return "textbox"
    return "shape"


def _build_sheet_drawing_map(zf: zipfile.ZipFile, zip_names: set[str]) -> dict[str, list[str]]:
    """xl/worksheets/_rels/sheetN.xml.rels からシート→drawingのマッピングを構築する。"""
    result: dict[str, list[str]] = {}
    for name in zip_names:
        if not name.startswith("xl/worksheets/_rels/") or not name.endswith(".rels"):
            continue
        stem = Path(name).stem.replace(".xml", "")
        try:
            xml = zf.read(name)
            root = ET.fromstring(xml)
        except (ET.ParseError, KeyError):
            continue
        drawings: list[str] = []
        ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        for rel in root.iter(f"{{{ns}}}Relationship"):
            if _REL_DRAWING in rel.get("Type", ""):
                target = rel.get("Target", "")
                drawing_path = "xl/" + target.lstrip("../")
                drawings.append(drawing_path)
        if drawings:
            result[stem] = drawings
    return result


def _drawing_rel_path(drawing_path: str) -> str:
    """xl/drawings/drawing1.xml → xl/drawings/_rels/drawing1.xml.rels"""
    p = Path(drawing_path)
    return str(p.parent / "_rels" / (p.name + ".rels"))


def _parse_chart_rels(xml_data: bytes) -> dict[str, str]:
    """drawing rels XMLからチャートのR_ID→パスマッピングを返す。"""
    result: dict[str, str] = {}
    try:
        root = ET.fromstring(xml_data)
        ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        for rel in root.iter(f"{{{ns}}}Relationship"):
            if _REL_CHART in rel.get("Type", ""):
                r_id = rel.get("Id", "")
                target = rel.get("Target", "")
                path = "xl/" + target.lstrip("../")
                result[r_id] = path
    except ET.ParseError:
        pass
    return result


def _gen_id(prefix: str, *parts: str) -> str:
    raw = "|".join(parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"
