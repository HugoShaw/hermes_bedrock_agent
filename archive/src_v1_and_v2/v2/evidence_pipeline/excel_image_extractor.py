"""
Excel image extractor — xl/media/ 配下に埋め込まれた画像を抽出・保存する。

出力:
  - images/          … 抽出画像ファイル
  - embedded_images.jsonl … 画像メタデータレコード
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

_NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
_REL_IMAGE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
_REL_DRAWING = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"

# xl/media/ 内で扱う画像フォーマット
_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif", ".emf", ".wmf", ".svg"})


class ExcelImageExtractor:
    """OOXMLファイルから埋め込み画像を抽出して保存するクラス。

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

    def extract(
        self,
        file_path: str,
        output_dir: str,
        sheet_records: list[dict[str, Any]],
        source_s3_uri: str = "",
    ) -> list[dict[str, Any]]:
        """ワークブックから全埋め込み画像を抽出する。

        Parameters
        ----------
        file_path:
            ローカルの .xlsx/.xlsm ファイルパス。
        output_dir:
            出力ディレクトリ (images/ サブディレクトリに保存)。
        sheet_records:
            excel_parser.py が返したシートレコード。
        source_s3_uri:
            元ファイルの S3 URI。

        Returns
        -------
        画像レコードのリスト。
        """
        path = Path(file_path)
        images_dir = Path(output_dir) / "images"
        images_dir.mkdir(parents=True, exist_ok=True)

        if not zipfile.is_zipfile(file_path):
            logger.warning("Not a ZIP/OOXML file: %s", file_path)
            return []

        records: list[dict[str, Any]] = []

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                zip_names = set(zf.namelist())
                media_files = sorted(n for n in zip_names if n.startswith("xl/media/") and Path(n).suffix.lower() in _IMAGE_EXTS)

                # シート→drawing マッピングと drawing→画像 マッピングを構築
                sheet_drawing_map = _build_sheet_drawing_map(zf, zip_names)
                drawing_image_map = _build_drawing_image_map(zf, zip_names)

                # 各 media ファイルのアンカー情報を逆引き
                media_anchor_index = _build_media_anchor_index(drawing_image_map, sheet_drawing_map, sheet_records)

                for idx, media_path in enumerate(media_files):
                    ext = Path(media_path).suffix.lower()
                    try:
                        img_bytes = zf.read(media_path)
                    except KeyError:
                        continue

                    size_bytes = len(img_bytes)
                    fmt = ext.lstrip(".")

                    # ファイル名: workbook_stem__media_N.ext
                    out_name = f"{path.stem}__{Path(media_path).name}"
                    out_path = images_dir / out_name
                    out_path.write_bytes(img_bytes)

                    anchor_info = media_anchor_index.get(media_path, {})
                    rec = _make_image_record(
                        idx=idx,
                        media_path=media_path,
                        local_path=str(out_path),
                        fmt=fmt,
                        size_bytes=size_bytes,
                        anchor_info=anchor_info,
                        workbook_name=path.stem,
                        source_file=str(path),
                        source_s3_uri=source_s3_uri,
                        dataset=self.dataset,
                        run_id=self.run_id,
                    )
                    records.append(rec)

        except zipfile.BadZipFile as exc:
            logger.error("BadZipFile for %s: %s", file_path, exc)

        logger.info("Extracted %d images from %s → %s", len(records), path.name, images_dir)
        return records

    def write_jsonl(self, records: list[dict[str, Any]], output_dir: str) -> str:
        """画像レコードを embedded_images.jsonl に書き出す。"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        jsonl_path = str(out / "embedded_images.jsonl")
        with open(jsonl_path, "w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        logger.info("Wrote %d image records → %s", len(records), jsonl_path)
        return jsonl_path


# ---- internal helpers -------------------------------------------------

def _make_image_record(
    idx: int,
    media_path: str,
    local_path: str,
    fmt: str,
    size_bytes: int,
    anchor_info: dict[str, Any],
    workbook_name: str,
    source_file: str,
    source_s3_uri: str,
    dataset: str,
    run_id: str,
) -> dict[str, Any]:
    raw = f"img:{dataset}:{source_file}:{media_path}:{idx}"
    image_id = "img_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return {
        "image_id": image_id,
        "image_index": idx,
        "media_zip_path": media_path,
        "local_path": local_path,
        "format": fmt,
        "size_bytes": size_bytes,
        "anchor_sheet": anchor_info.get("sheet_name", ""),
        "anchor_sheet_index": anchor_info.get("sheet_index", None),
        "anchor_cell_from": anchor_info.get("from", ""),
        "anchor_cell_to": anchor_info.get("to", ""),
        "workbook_name": workbook_name,
        "source_file": source_file,
        "source_s3_uri": source_s3_uri,
        "dataset": dataset,
        "run_id": run_id,
    }


def _build_sheet_drawing_map(zf: zipfile.ZipFile, zip_names: set[str]) -> dict[str, list[str]]:
    """sheet キー (e.g. 'sheet1') → drawing XML パスのマップ。"""
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
        for rel in root.iter(f"{{{_NS_PKG}}}Relationship"):
            if _REL_DRAWING in rel.get("Type", ""):
                target = rel.get("Target", "")
                drawing_path = "xl/" + target.lstrip("../")
                drawings.append(drawing_path)
        if drawings:
            result[stem] = drawings
    return result


def _build_drawing_image_map(zf: zipfile.ZipFile, zip_names: set[str]) -> dict[str, dict[str, str]]:
    """drawing XML パス → {r:id → xl/media/... パス} のマップ。"""
    result: dict[str, dict[str, str]] = {}
    for name in zip_names:
        if not name.startswith("xl/drawings/") or not name.endswith(".rels"):
            continue
        drawing_xml = name.replace("_rels/", "").replace(".rels", "")
        try:
            xml = zf.read(name)
            root = ET.fromstring(xml)
        except (ET.ParseError, KeyError):
            continue
        id_map: dict[str, str] = {}
        for rel in root.iter(f"{{{_NS_PKG}}}Relationship"):
            if _REL_IMAGE in rel.get("Type", ""):
                r_id = rel.get("Id", "")
                target = rel.get("Target", "")
                media_path = "xl/" + target.lstrip("../")
                id_map[r_id] = media_path
        if id_map:
            result[drawing_xml] = id_map
    return result


def _build_media_anchor_index(
    drawing_image_map: dict[str, dict[str, str]],
    sheet_drawing_map: dict[str, list[str]],
    sheet_records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """xl/media/... パス → アンカー情報 (sheet_name, from, to) の逆引きマップ。"""
    result: dict[str, dict[str, Any]] = {}

    # sheet_key → sheet_record
    sheet_by_key: dict[str, dict[str, Any]] = {}
    for idx, rec in enumerate(sheet_records):
        sheet_by_key[f"sheet{idx + 1}"] = rec

    for sheet_key, drawing_paths in sheet_drawing_map.items():
        sheet_rec = sheet_by_key.get(sheet_key, {})
        for drawing_path in drawing_paths:
            id_map = drawing_image_map.get(drawing_path, {})
            for media_path in id_map.values():
                if media_path not in result:
                    result[media_path] = {
                        "sheet_name": sheet_rec.get("sheet_name", ""),
                        "sheet_index": sheet_rec.get("sheet_index"),
                        "from": "",
                        "to": "",
                    }
    return result
