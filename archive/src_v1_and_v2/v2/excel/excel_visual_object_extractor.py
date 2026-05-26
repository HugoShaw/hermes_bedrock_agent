"""
Excel Visual Object Extractor — extracts images, shapes, drawings from Excel ZIP.

Uses both openpyxl API and raw ZIP/XML inspection to find all visual objects.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import openpyxl

from hermes_bedrock_agent.v2.excel.excel_visual_schema import (
    ExcelVisualObjectRecord,
    ExcelVisualSheetRecord,
    ExcelVisualWorkbookRecord,
)

logger = logging.getLogger(__name__)

# XML namespaces used in Excel drawings
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "v": "urn:schemas-microsoft-com:vml",
    "o": "urn:schemas-microsoft-com:office:office",
    "x": "urn:schemas-microsoft-com:office:excel",
}


def _gen_id(prefix: str, *parts: str) -> str:
    h = hashlib.md5("|".join(parts).encode()).hexdigest()[:16]
    return f"{prefix}_{h}"


class ExcelVisualObjectExtractor:
    """Extract visual objects from an Excel workbook file."""

    def __init__(
        self,
        workbook_path: str,
        output_dir: str,
        workbook_name: str = "",
        dataset: str = "",
        run_id: str = "",
    ):
        self.workbook_path = workbook_path
        self.output_dir = Path(output_dir)
        self.workbook_name = workbook_name or os.path.basename(workbook_path)
        self.dataset = dataset
        self.run_id = run_id
        self.workbook_id = _gen_id("wb", self.workbook_name, run_id)

        # Output subdirs
        self.raw_media_dir = self.output_dir / "raw_media"
        self.object_images_dir = self.output_dir / "object_images"
        self.raw_media_dir.mkdir(parents=True, exist_ok=True)
        self.object_images_dir.mkdir(parents=True, exist_ok=True)

        # Results
        self.workbook_record: ExcelVisualWorkbookRecord | None = None
        self.sheet_records: list[ExcelVisualSheetRecord] = []
        self.object_records: list[ExcelVisualObjectRecord] = []
        self.warnings: list[dict[str, Any]] = []

    def extract_all(self) -> dict[str, Any]:
        """Run full extraction pipeline."""
        logger.info("Extracting visuals from: %s", self.workbook_name)

        # Step 1: Extract media files from ZIP
        media_files = self._extract_media_from_zip()

        # Step 2: Parse drawing XMLs from ZIP
        drawing_objects = self._parse_drawing_xmls()

        # Step 3: Parse VML drawings
        vml_objects = self._parse_vml_drawings()

        # Step 4: Map sheets to drawings via relationships
        sheet_drawing_map = self._map_sheets_to_drawings()

        # Step 5: Use openpyxl for images and sheet info
        openpyxl_info = self._inspect_with_openpyxl()

        # Step 6: Build records
        self._build_records(media_files, drawing_objects, vml_objects,
                           sheet_drawing_map, openpyxl_info)

        return {
            "workbook_record": asdict(self.workbook_record) if self.workbook_record else {},
            "sheet_records": [asdict(r) for r in self.sheet_records],
            "object_records": [asdict(r) for r in self.object_records],
            "warnings": self.warnings,
        }

    def _extract_media_from_zip(self) -> list[dict[str, str]]:
        """Extract all media files from xl/media/."""
        media_files = []
        try:
            with zipfile.ZipFile(self.workbook_path) as z:
                for name in z.namelist():
                    if name.startswith("xl/media/"):
                        basename = os.path.basename(name)
                        if not basename:
                            continue
                        out_name = f"{self.workbook_id}__{basename}"
                        out_path = self.raw_media_dir / out_name
                        with z.open(name) as src, open(out_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        media_files.append({
                            "zip_path": name,
                            "local_path": str(out_path),
                            "filename": basename,
                        })
                        logger.debug("Extracted media: %s → %s", name, out_path)
        except Exception as e:
            self.warnings.append({"type": "media_extraction_error", "message": str(e)})
            logger.warning("Failed to extract media: %s", e)
        return media_files

    def _parse_drawing_xmls(self) -> list[dict[str, Any]]:
        """Parse xl/drawings/drawing*.xml for shapes, images, connectors."""
        objects = []
        try:
            with zipfile.ZipFile(self.workbook_path) as z:
                # Get drawing rels
                drawing_rels = {}
                for name in z.namelist():
                    if re.match(r"xl/drawings/_rels/drawing\d+\.xml\.rels", name):
                        drawing_num = re.search(r"drawing(\d+)", name).group(1)
                        tree = ET.parse(z.open(name))
                        rels = {}
                        for rel in tree.getroot():
                            rid = rel.get("Id", "")
                            target = rel.get("Target", "")
                            rel_type = rel.get("Type", "")
                            rels[rid] = {"target": target, "type": rel_type}
                        drawing_rels[drawing_num] = rels

                # Parse each drawing XML
                for name in sorted(z.namelist()):
                    if re.match(r"xl/drawings/drawing\d+\.xml$", name):
                        drawing_num = re.search(r"drawing(\d+)", name).group(1)
                        rels = drawing_rels.get(drawing_num, {})
                        content = z.read(name)
                        objs = self._parse_single_drawing_xml(
                            content, name, rels, drawing_num
                        )
                        objects.extend(objs)
        except Exception as e:
            self.warnings.append({"type": "drawing_xml_error", "message": str(e)})
            logger.warning("Failed to parse drawing XMLs: %s", e)
        return objects

    def _parse_single_drawing_xml(
        self, content: bytes, xml_path: str, rels: dict, drawing_num: str
    ) -> list[dict[str, Any]]:
        """Parse a single drawing XML file."""
        objects = []
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            self.warnings.append({"type": "xml_parse_error", "path": xml_path, "message": str(e)})
            return objects

        # Find all anchors (twoCellAnchor, oneCellAnchor, absoluteAnchor)
        for anchor_tag in ["twoCellAnchor", "oneCellAnchor", "absoluteAnchor"]:
            for anchor in root.findall(f"xdr:{anchor_tag}", NS):
                obj = self._parse_anchor(anchor, xml_path, rels, drawing_num)
                if obj:
                    objects.append(obj)
        return objects

    def _parse_anchor(
        self, anchor: ET.Element, xml_path: str, rels: dict, drawing_num: str
    ) -> dict[str, Any] | None:
        """Parse a single anchor element."""
        obj: dict[str, Any] = {
            "xml_path": xml_path,
            "drawing_num": drawing_num,
            "anchor_from_cell": "",
            "anchor_to_cell": "",
            "object_type": "unknown_visual",
            "object_name": "",
            "text": "",
            "alt_text": "",
            "shape_type": "",
            "relationship_id": "",
            "image_target": "",
        }

        # Parse from/to cells
        from_elem = anchor.find("xdr:from", NS)
        to_elem = anchor.find("xdr:to", NS)
        if from_elem is not None:
            col = from_elem.findtext("xdr:col", "", NS)
            row = from_elem.findtext("xdr:row", "", NS)
            if col and row:
                obj["anchor_from_cell"] = f"R{int(row)+1}C{int(col)+1}"
        if to_elem is not None:
            col = to_elem.findtext("xdr:col", "", NS)
            row = to_elem.findtext("xdr:row", "", NS)
            if col and row:
                obj["anchor_to_cell"] = f"R{int(row)+1}C{int(col)+1}"

        # Check for picture (image)
        pic = anchor.find("xdr:pic", NS)
        if pic is not None:
            obj["object_type"] = "embedded_image"
            # Get name
            nv = pic.find("xdr:nvPicPr", NS)
            if nv is not None:
                cnv = nv.find("xdr:cNvPr", NS)
                if cnv is not None:
                    obj["object_name"] = cnv.get("name", "")
                    obj["alt_text"] = cnv.get("descr", "")
            # Get relationship
            blip_fill = pic.find("xdr:blipFill", NS)
            if blip_fill is not None:
                blip = blip_fill.find("a:blip", NS)
                if blip is not None:
                    embed = blip.get(f"{{{NS['r']}}}embed", "")
                    obj["relationship_id"] = embed
                    if embed in rels:
                        obj["image_target"] = rels[embed]["target"]
            return obj

        # Check for shape (sp)
        sp = anchor.find("xdr:sp", NS)
        if sp is not None:
            obj["object_type"] = "shape"
            # Get name and type
            nv = sp.find("xdr:nvSpPr", NS)
            if nv is not None:
                cnv = nv.find("xdr:cNvPr", NS)
                if cnv is not None:
                    obj["object_name"] = cnv.get("name", "")
                    obj["alt_text"] = cnv.get("descr", "")
            # Check shape properties for preset geometry
            sp_pr = sp.find("xdr:spPr", NS)
            if sp_pr is not None:
                prst = sp_pr.find("a:prstGeom", NS)
                if prst is not None:
                    obj["shape_type"] = prst.get("prst", "")
            # Determine if connector/arrow/textbox
            shape_type = obj["shape_type"]
            if shape_type in ("line", "straightConnector1", "bentConnector3",
                              "curvedConnector3", "bentConnector2"):
                obj["object_type"] = "connector"
            elif shape_type in ("rightArrow", "leftArrow", "downArrow", "upArrow",
                                "leftRightArrow", "notchedRightArrow"):
                obj["object_type"] = "arrow"
            elif "TextBox" in obj["object_name"] or shape_type == "rect":
                # Check if it has text
                pass  # Will classify after text extraction

            # Extract text
            txBody = sp.find("xdr:txBody", NS)
            if txBody is not None:
                texts = []
                for p in txBody.findall("a:p", NS):
                    para_texts = []
                    for r_elem in p.findall("a:r", NS):
                        t = r_elem.findtext("a:t", "", NS)
                        if t:
                            para_texts.append(t)
                    if para_texts:
                        texts.append("".join(para_texts))
                obj["text"] = "\n".join(texts)
                if obj["text"] and obj["object_type"] == "shape":
                    obj["object_type"] = "textbox"
            return obj

        # Check for connection shape (cxnSp)
        cxn = anchor.find("xdr:cxnSp", NS)
        if cxn is not None:
            obj["object_type"] = "connector"
            nv = cxn.find("xdr:nvCxnSpPr", NS)
            if nv is not None:
                cnv = nv.find("xdr:cNvPr", NS)
                if cnv is not None:
                    obj["object_name"] = cnv.get("name", "")
            sp_pr = cxn.find("xdr:spPr", NS)
            if sp_pr is not None:
                prst = sp_pr.find("a:prstGeom", NS)
                if prst is not None:
                    obj["shape_type"] = prst.get("prst", "")
            return obj

        # Check for group shape
        grp = anchor.find("xdr:grpSp", NS)
        if grp is not None:
            obj["object_type"] = "group"
            nv = grp.find("xdr:nvGrpSpPr", NS)
            if nv is not None:
                cnv = nv.find("xdr:cNvPr", NS)
                if cnv is not None:
                    obj["object_name"] = cnv.get("name", "")
            # Extract all text from group children
            texts = []
            for sp_child in grp.iter(f"{{{NS['xdr']}}}sp"):
                txBody = sp_child.find("xdr:txBody", NS)
                if txBody is not None:
                    for p in txBody.findall("a:p", NS):
                        para_texts = []
                        for r_elem in p.findall("a:r", NS):
                            t = r_elem.findtext("a:t", "", NS)
                            if t:
                                para_texts.append(t)
                        if para_texts:
                            texts.append("".join(para_texts))
            obj["text"] = "\n".join(texts)
            return obj

        # Check for graphicFrame (chart)
        gf = anchor.find("xdr:graphicFrame", NS)
        if gf is not None:
            obj["object_type"] = "chart"
            nv = gf.find("xdr:nvGraphicFramePr", NS)
            if nv is not None:
                cnv = nv.find("xdr:cNvPr", NS)
                if cnv is not None:
                    obj["object_name"] = cnv.get("name", "")
            return obj

        return None

    def _parse_vml_drawings(self) -> list[dict[str, Any]]:
        """Parse VML drawing files for shapes/comments."""
        objects = []
        try:
            with zipfile.ZipFile(self.workbook_path) as z:
                for name in sorted(z.namelist()):
                    if re.match(r"xl/drawings/vmlDrawing\d+\.vml$", name):
                        content = z.read(name)
                        objs = self._parse_vml_content(content, name)
                        objects.extend(objs)
        except Exception as e:
            self.warnings.append({"type": "vml_parse_error", "message": str(e)})
        return objects

    def _parse_vml_content(self, content: bytes, xml_path: str) -> list[dict[str, Any]]:
        """Parse VML content for shapes."""
        objects = []
        try:
            # VML may not be well-formed XML; try parsing
            text = content.decode("utf-8", errors="replace")
            # Fix common VML issues
            if not text.strip().startswith("<?xml"):
                text = '<?xml version="1.0"?>\n<root xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">' + text + "</root>"

            root = ET.fromstring(text)
            # Find shapes
            for shape in root.iter(f"{{{NS['v']}}}shape"):
                obj = {
                    "xml_path": xml_path,
                    "object_type": "shape",
                    "object_name": shape.get("id", ""),
                    "shape_type": shape.get("type", ""),
                    "text": "",
                    "anchor_from_cell": "",
                    "anchor_to_cell": "",
                }
                # Get text from textbox
                for tb in shape.iter(f"{{{NS['v']}}}textbox"):
                    if tb.text:
                        obj["text"] = tb.text.strip()
                    # Also check for div children
                    for div in tb:
                        if div.text:
                            obj["text"] += div.text.strip() + " "
                # Get anchor info from ClientData
                for cd in shape.iter(f"{{{NS['x']}}}ClientData"):
                    anchor_elem = cd.find(f"{{{NS['x']}}}Anchor")
                    if anchor_elem is not None and anchor_elem.text:
                        obj["anchor_from_cell"] = anchor_elem.text.strip()[:50]
                if obj["text"]:
                    obj["object_type"] = "textbox"
                objects.append(obj)
        except ET.ParseError:
            # VML can be malformed, just note it
            self.warnings.append({"type": "vml_xml_malformed", "path": xml_path})
        return objects

    def _map_sheets_to_drawings(self) -> dict[int, list[str]]:
        """Map sheet indices to their drawing XML files via relationships."""
        sheet_map: dict[int, list[str]] = {}
        try:
            with zipfile.ZipFile(self.workbook_path) as z:
                for name in sorted(z.namelist()):
                    match = re.match(r"xl/worksheets/_rels/sheet(\d+)\.xml\.rels", name)
                    if match:
                        sheet_num = int(match.group(1))
                        tree = ET.parse(z.open(name))
                        drawings = []
                        for rel in tree.getroot():
                            target = rel.get("Target", "")
                            rel_type = rel.get("Type", "")
                            if "drawing" in rel_type.lower() or "drawing" in target.lower():
                                drawings.append(target)
                            elif "vml" in target.lower():
                                drawings.append(target)
                        if drawings:
                            sheet_map[sheet_num] = drawings
        except Exception as e:
            self.warnings.append({"type": "sheet_rels_error", "message": str(e)})
        return sheet_map

    def _inspect_with_openpyxl(self) -> dict[str, Any]:
        """Use openpyxl to get sheet info and images."""
        info: dict[str, Any] = {"sheets": [], "images": []}
        try:
            wb = openpyxl.load_workbook(self.workbook_path, read_only=False, data_only=True)
            for idx, ws in enumerate(wb.worksheets):
                sheet_info = {
                    "name": ws.title,
                    "index": idx,
                    "image_count": len(ws._images) if hasattr(ws, '_images') else 0,
                    "chart_count": len(ws._charts) if hasattr(ws, '_charts') else 0,
                }
                info["sheets"].append(sheet_info)
                # Extract images via openpyxl
                if hasattr(ws, '_images'):
                    for img_idx, img in enumerate(ws._images):
                        img_info = {
                            "sheet_name": ws.title,
                            "sheet_index": idx,
                            "anchor": str(img.anchor) if hasattr(img, 'anchor') else "",
                        }
                        info["images"].append(img_info)
            wb.close()
        except Exception as e:
            self.warnings.append({"type": "openpyxl_error", "message": str(e)})
        return info

    def _build_records(
        self,
        media_files: list[dict],
        drawing_objects: list[dict],
        vml_objects: list[dict],
        sheet_drawing_map: dict[int, list[str]],
        openpyxl_info: dict[str, Any],
    ):
        """Build structured records from extraction results."""
        # Build sheet records
        sheets_info = openpyxl_info.get("sheets", [])
        total_images = 0
        total_charts = 0
        total_shapes = 0
        total_connectors = 0
        visual_sheets = 0

        # Map drawing objects to sheets
        for sheet_data in sheets_info:
            idx = sheet_data["index"]
            name = sheet_data["name"]
            sheet_id = _gen_id("sh", self.workbook_name, name, str(idx))

            # Count objects for this sheet
            sheet_num = idx + 1  # xlsx uses 1-based
            sheet_drawings = sheet_drawing_map.get(sheet_num, [])
            sheet_objects = []
            for dobj in drawing_objects:
                drawing_file = os.path.basename(dobj.get("xml_path", ""))
                for sd in sheet_drawings:
                    if drawing_file in sd or os.path.basename(sd) == drawing_file:
                        sheet_objects.append(dobj)
                        break

            img_count = sum(1 for o in sheet_objects if o.get("object_type") == "embedded_image")
            chart_count = sum(1 for o in sheet_objects if o.get("object_type") == "chart")
            shape_count = sum(1 for o in sheet_objects if o.get("object_type") in ("shape", "textbox", "group"))
            conn_count = sum(1 for o in sheet_objects if o.get("object_type") in ("connector", "arrow"))

            has_visual = bool(sheet_objects) or sheet_data.get("image_count", 0) > 0
            if has_visual:
                visual_sheets += 1

            total_images += img_count
            total_charts += chart_count
            total_shapes += shape_count
            total_connectors += conn_count

            rec = ExcelVisualSheetRecord(
                sheet_visual_id=_gen_id("sv", self.workbook_name, name),
                workbook_id=self.workbook_id,
                workbook_name=self.workbook_name,
                sheet_id=sheet_id,
                sheet_name=name,
                sheet_index=idx,
                has_visual_objects=has_visual,
                has_images=img_count > 0 or sheet_data.get("image_count", 0) > 0,
                has_charts=chart_count > 0 or sheet_data.get("chart_count", 0) > 0,
                has_shapes=shape_count > 0,
                has_drawings=bool(sheet_drawings),
                object_count=len(sheet_objects),
                image_count=img_count,
                chart_count=chart_count,
                shape_count=shape_count,
                connector_count=conn_count,
            )
            self.sheet_records.append(rec)

            # Build object records for this sheet
            for obj_idx, dobj in enumerate(sheet_objects):
                # Resolve image path
                image_path = ""
                if dobj.get("image_target"):
                    target = dobj["image_target"]
                    # Target is relative like ../media/image1.png
                    basename = os.path.basename(target)
                    for mf in media_files:
                        if mf["filename"] == basename:
                            image_path = mf["local_path"]
                            break

                obj_rec = ExcelVisualObjectRecord(
                    visual_object_id=_gen_id("vo", self.workbook_name, name, str(obj_idx)),
                    workbook_id=self.workbook_id,
                    workbook_name=self.workbook_name,
                    sheet_id=sheet_id,
                    sheet_name=name,
                    sheet_index=idx,
                    object_type=dobj.get("object_type", "unknown_visual"),
                    object_name=dobj.get("object_name", ""),
                    anchor_from_cell=dobj.get("anchor_from_cell", ""),
                    anchor_to_cell=dobj.get("anchor_to_cell", ""),
                    anchor_range=f"{dobj.get('anchor_from_cell', '')}:{dobj.get('anchor_to_cell', '')}",
                    text=dobj.get("text", ""),
                    alt_text=dobj.get("alt_text", ""),
                    shape_type=dobj.get("shape_type", ""),
                    image_path=image_path,
                    relationship_id=dobj.get("relationship_id", ""),
                    xml_path=dobj.get("xml_path", ""),
                    extraction_method="drawing_xml",
                    run_id=self.run_id,
                    dataset=self.dataset,
                )
                self.object_records.append(obj_rec)

        # Also add VML objects (usually not mapped to specific sheets easily)
        for vml_idx, vobj in enumerate(vml_objects):
            obj_rec = ExcelVisualObjectRecord(
                visual_object_id=_gen_id("vml", self.workbook_name, str(vml_idx)),
                workbook_id=self.workbook_id,
                workbook_name=self.workbook_name,
                object_type=vobj.get("object_type", "shape"),
                object_name=vobj.get("object_name", ""),
                anchor_from_cell=vobj.get("anchor_from_cell", ""),
                text=vobj.get("text", ""),
                shape_type=vobj.get("shape_type", ""),
                xml_path=vobj.get("xml_path", ""),
                extraction_method="vml",
                run_id=self.run_id,
                dataset=self.dataset,
            )
            self.object_records.append(obj_rec)

        # Build workbook record
        self.workbook_record = ExcelVisualWorkbookRecord(
            workbook_id=self.workbook_id,
            workbook_name=self.workbook_name,
            source_path=self.workbook_path,
            dataset=self.dataset,
            run_id=self.run_id,
            sheet_count=len(sheets_info),
            visual_sheet_count=visual_sheets,
            image_count=total_images + len(media_files),
            chart_count=total_charts,
            drawing_object_count=len(drawing_objects) + len(vml_objects),
        )
