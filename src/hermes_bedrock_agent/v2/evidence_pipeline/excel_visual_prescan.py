"""
Excel visual prescan — OOXMLのZIPを検査して各シートのビジュアルオブジェクトを事前スキャンする。

LibreOfficeやレンダリングは不要。ZIPのXMLを直接解析する。

出力:
  - visual_prescan.jsonl … シートごとのビジュアル有無フラグ
"""
from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# OOXMLの主要名前空間
_NS = {
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
}

_REL_DRAWING = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
_REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_REL_CHART = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart"


class ExcelVisualPrescan:
    """OOXMLを検査してシートのビジュアル要素有無を事前スキャンする。"""

    def __init__(
        self,
        dataset: str = "sample_20260519",
        run_id: str = "sample_20260519_evidence_v1",
    ) -> None:
        self.dataset = dataset
        self.run_id = run_id

    def scan_workbook(
        self,
        file_path: str,
        sheet_records: list[dict[str, Any]],
        source_s3_uri: str = "",
    ) -> list[dict[str, Any]]:
        """ワークブック内の全シートをビジュアルスキャンする。

        Parameters
        ----------
        file_path:
            ローカルのExcelファイルパス (.xlsx/.xlsm)。
        sheet_records:
            excel_parser.py が返したシートレコードのリスト。
        source_s3_uri:
            元ファイルのS3 URI。

        Returns
        -------
        シートごとの prescan レコードのリスト。
        """
        path = Path(file_path)
        results: list[dict[str, Any]] = []

        if not zipfile.is_zipfile(file_path):
            logger.warning("Not a ZIP/OOXML file: %s", file_path)
            return results

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                zip_names = set(zf.namelist())
                # シート→drawing マッピングを構築
                sheet_drawing_map = _build_sheet_drawing_map(zf, zip_names)
                # xl/media/ 配下の画像一覧
                media_files = [n for n in zip_names if n.startswith("xl/media/")]

                for sheet_rec in sheet_records:
                    prescan = self._scan_sheet(
                        zf=zf,
                        zip_names=zip_names,
                        sheet_rec=sheet_rec,
                        sheet_drawing_map=sheet_drawing_map,
                        media_files=media_files,
                        file_path=str(path),
                        source_s3_uri=source_s3_uri,
                    )
                    results.append(prescan)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            logger.error("Visual prescan failed for %s: %s", file_path, exc)

        return results

    def _scan_sheet(
        self,
        zf: zipfile.ZipFile,
        zip_names: set[str],
        sheet_rec: dict[str, Any],
        sheet_drawing_map: dict[str, list[str]],
        media_files: list[str],
        file_path: str,
        source_s3_uri: str,
    ) -> dict[str, Any]:
        """1シートのビジュアル要素を検査する。"""
        sheet_name = sheet_rec["sheet_name"]
        sheet_idx = sheet_rec["sheet_index"]
        sheet_id = sheet_rec["sheet_id"]
        workbook_id = sheet_rec["workbook_id"]

        # このシートに紐づくdrawing XMLパスを取得
        drawing_paths = sheet_drawing_map.get(f"sheet{sheet_idx + 1}", [])

        has_images = False
        has_charts = False
        has_shapes = False
        has_textboxes = False
        has_connectors = False
        has_drawings = len(drawing_paths) > 0
        shape_count = 0
        connector_count = 0
        chart_count = 0
        image_count = 0

        for drawing_path in drawing_paths:
            if drawing_path not in zip_names:
                continue
            try:
                xml_data = zf.read(drawing_path)
                root = ET.fromstring(xml_data)
            except (ET.ParseError, KeyError) as exc:
                logger.debug("Failed to parse drawing %s: %s", drawing_path, exc)
                continue

            # sp (shape/textbox) — 矩形、テキストボックス等
            for sp in root.iter(f"{{{_NS['xdr']}}}sp"):
                has_shapes = True
                shape_count += 1
                # nvSpPr/cNvSpPr[@txBox='1'] → テキストボックス
                txbox = sp.find(f".//{{{_NS['xdr']}}}cNvSpPr[@txBox='1']")
                if txbox is not None:
                    has_textboxes = True

            # cxnSp (connector) — 矢印・コネクター
            for _ in root.iter(f"{{{_NS['xdr']}}}cxnSp"):
                has_connectors = True
                connector_count += 1

            # pic (embedded picture)
            for _ in root.iter(f"{{{_NS['xdr']}}}pic"):
                has_images = True
                image_count += 1

            # graphicFrame — chart や smart art
            for gf in root.iter(f"{{{_NS['xdr']}}}graphicFrame"):
                chart_elem = gf.find(f".//{{{_NS['c']}}}chart")
                if chart_elem is not None:
                    has_charts = True
                    chart_count += 1

        # VML形式のドローイングも確認
        vml_path = f"xl/drawings/vmlDrawing{sheet_idx + 1}.vml"
        has_vml = vml_path in zip_names

        # シート関連media確認 (xl/media/ 配下の全ファイル)
        # 簡易チェック: media が1件でもあれば画像有り
        if media_files and not has_images:
            has_images = len(media_files) > 0

        # VLM解析が必要か判断
        visual_parse_required = has_connectors or has_charts or (has_images and sheet_rec.get("non_empty_cell_count", 0) < 10)

        # 推奨戦略
        if has_connectors and connector_count > 0:
            suggested_strategy = "ooxml_connector_parse"
        elif has_charts:
            suggested_strategy = "ooxml_chart_parse"
        elif has_images:
            suggested_strategy = "image_reference_only"
        elif has_textboxes:
            suggested_strategy = "ooxml_shape_parse"
        else:
            suggested_strategy = "cell_only"

        return {
            "prescan_id": _prescan_id(sheet_id),
            "sheet_id": sheet_id,
            "workbook_id": workbook_id,
            "dataset": self.dataset,
            "run_id": self.run_id,
            "source_file": file_path,
            "source_s3_uri": source_s3_uri,
            "workbook_name": sheet_rec.get("workbook_name", ""),
            "sheet_name": sheet_name,
            "sheet_index": sheet_idx,
            "has_visual_objects": has_drawings or has_vml,
            "has_images": has_images,
            "has_charts": has_charts,
            "has_shapes": has_shapes,
            "has_textboxes": has_textboxes,
            "has_connectors": has_connectors,
            "has_drawings": has_drawings,
            "has_vml": has_vml,
            "shape_count": shape_count,
            "connector_count": connector_count,
            "chart_count": chart_count,
            "image_count": image_count,
            "drawing_xml_paths": drawing_paths,
            "visual_parse_required": visual_parse_required,
            "suggested_strategy": suggested_strategy,
        }

    def write_jsonl(self, records: list[dict[str, Any]], output_dir: str) -> str:
        """prescanレコードをJSONLファイルに書き出す。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        path = str(out / "visual_prescan.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        logger.info("Wrote %d prescan records → %s", len(records), path)
        return path


# ---- Internal helpers -------------------------------------------------

def _build_sheet_drawing_map(zf: zipfile.ZipFile, zip_names: set[str]) -> dict[str, list[str]]:
    """xl/worksheets/_rels/sheetN.xml.rels からシート→drawingのマッピングを構築する。"""
    result: dict[str, list[str]] = {}
    for name in zip_names:
        if not name.startswith("xl/worksheets/_rels/") or not name.endswith(".rels"):
            continue
        # xl/worksheets/_rels/sheet1.xml.rels → sheet1
        stem = Path(name).stem.replace(".xml", "")
        try:
            xml = zf.read(name)
            root = ET.fromstring(xml)
        except (ET.ParseError, KeyError):
            continue
        drawings: list[str] = []
        ns = "http://schemas.openxmlformats.org/package/2006/relationships"
        for rel in root.iter(f"{{{ns}}}Relationship"):
            rel_type = rel.get("Type", "")
            target = rel.get("Target", "")
            if _REL_DRAWING in rel_type:
                # Target は ../drawings/drawing1.xml 形式が多い
                drawing_path = "xl/" + target.lstrip("../")
                drawings.append(drawing_path)
        if drawings:
            result[stem] = drawings
    return result


def _prescan_id(sheet_id: str) -> str:
    import hashlib
    raw = f"prescan:{sheet_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
