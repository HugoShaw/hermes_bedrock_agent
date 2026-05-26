"""OOXML Drawing XML parser for Excel shapes, connectors, and pictures.

Directly parses xl/drawings/drawing*.xml to extract:
- Shape objects (sp) with text, geometry, position
- Connector objects (cxnSp) with start/end connections
- Picture objects (pic) with media references
- Group objects (grpSp)
"""
import zipfile
import logging
import shutil
from pathlib import Path
from lxml import etree

from .models import (
    ExcelShape, ExcelConnector, ExcelPicture, ExcelGroup, SheetData
)

logger = logging.getLogger(__name__)

# OOXML namespaces
NS = {
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}

# Standard column width in EMU (approx 64px = 609600 EMU)
COL_WIDTH_EMU = 609600
# Standard row height in EMU (approx 20px = 190500 EMU)
ROW_HEIGHT_EMU = 190500


def parse_drawings(excel_path: str, sheets: list[SheetData], images_dir: str) -> None:
    """Parse all drawings from Excel OOXML and populate sheet data.
    
    Modifies sheets in-place, adding shapes, connectors, pictures.
    """
    images_path = Path(images_dir)
    images_path.mkdir(parents=True, exist_ok=True)
    
    with zipfile.ZipFile(excel_path) as zf:
        # Map sheet index to drawing file
        sheet_drawing_map = _get_sheet_drawing_map(zf)
        
        for i, sheet in enumerate(sheets):
            sheet_idx = i + 1
            drawing_file = sheet_drawing_map.get(sheet_idx)
            if not drawing_file:
                continue
            
            sheet.has_drawing = True
            logger.info(f"Parsing drawing for sheet '{sheet.name}': {drawing_file}")
            
            # Get relationship map for this drawing
            rels_file = drawing_file.replace("xl/drawings/", "xl/drawings/_rels/") + ".rels"
            rels_map = {}
            if rels_file in zf.namelist():
                rels_map = _parse_rels(zf, rels_file)
            
            # Parse the drawing XML
            drawing_xml = etree.parse(zf.open(drawing_file))
            root = drawing_xml.getroot()
            
            # Process all anchors
            for anchor in root.findall(f"{{{NS['xdr']}}}twoCellAnchor"):
                _process_anchor(anchor, sheet, rels_map, zf, images_path)
            
            for anchor in root.findall(f"{{{NS['xdr']}}}oneCellAnchor"):
                _process_anchor(anchor, sheet, rels_map, zf, images_path)
            
            # For connectors without explicit stCxn/endCxn, infer by position
            _infer_missing_connections(sheet)
            
            logger.info(
                f"  Sheet '{sheet.name}': {len(sheet.shapes)} shapes, "
                f"{len(sheet.connectors)} connectors, {len(sheet.pictures)} pictures"
            )


def _get_sheet_drawing_map(zf: zipfile.ZipFile) -> dict[int, str]:
    """Map sheet index to drawing file path."""
    mapping = {}
    for i in range(1, 20):
        rels_path = f"xl/worksheets/_rels/sheet{i}.xml.rels"
        if rels_path not in zf.namelist():
            continue
        rels_tree = etree.parse(zf.open(rels_path))
        for rel in rels_tree.getroot():
            rtype = rel.get("Type", "")
            if "drawing" in rtype:
                target = rel.get("Target", "")
                # Resolve relative path
                if target.startswith("../"):
                    target = "xl/" + target[3:]
                elif not target.startswith("xl/"):
                    target = "xl/drawings/" + target
                mapping[i] = target
                break
    return mapping


def _parse_rels(zf: zipfile.ZipFile, rels_path: str) -> dict[str, str]:
    """Parse relationship file into {rId: target_path} map."""
    rels = {}
    tree = etree.parse(zf.open(rels_path))
    for rel in tree.getroot():
        rid = rel.get("Id", "")
        target = rel.get("Target", "")
        rels[rid] = target
    return rels


def _process_anchor(anchor, sheet: SheetData, rels_map: dict, 
                    zf: zipfile.ZipFile, images_path: Path) -> None:
    """Process a twoCellAnchor or oneCellAnchor element."""
    # Get position
    from_elem = anchor.find(f"{{{NS['xdr']}}}from")
    to_elem = anchor.find(f"{{{NS['xdr']}}}to")
    
    from_col, from_row, from_col_off, from_row_off = _parse_position(from_elem)
    to_col, to_row, to_col_off, to_row_off = _parse_position(to_elem)
    
    # Check for shape
    sp = anchor.find(f"{{{NS['xdr']}}}sp")
    if sp is not None:
        shape = _parse_shape(sp, sheet.name, from_row, from_col, to_row, to_col,
                            from_row_off, from_col_off, to_row_off, to_col_off)
        if shape:
            sheet.shapes.append(shape)
        return
    
    # Check for connector
    cxn = anchor.find(f"{{{NS['xdr']}}}cxnSp")
    if cxn is not None:
        connector = _parse_connector(cxn, sheet.name, from_row, from_col, to_row, to_col,
                                     from_row_off, from_col_off, to_row_off, to_col_off)
        if connector:
            sheet.connectors.append(connector)
        return
    
    # Check for picture
    pic = anchor.find(f"{{{NS['xdr']}}}pic")
    if pic is not None:
        picture = _parse_picture(pic, sheet.name, from_row, from_col, rels_map, zf, images_path)
        if picture:
            sheet.pictures.append(picture)
        return
    
    # Check for group
    grp = anchor.find(f"{{{NS['xdr']}}}grpSp")
    if grp is not None:
        _parse_group(grp, sheet, from_row, from_col, to_row, to_col,
                    from_row_off, from_col_off, to_row_off, to_col_off)


def _parse_position(pos_elem) -> tuple[int, int, int, int]:
    """Parse from/to position element. Returns (col, row, col_off, row_off)."""
    if pos_elem is None:
        return 0, 0, 0, 0
    
    col = int(pos_elem.findtext(f"{{{NS['xdr']}}}col", "0"))
    row = int(pos_elem.findtext(f"{{{NS['xdr']}}}row", "0"))
    col_off = int(pos_elem.findtext(f"{{{NS['xdr']}}}colOff", "0"))
    row_off = int(pos_elem.findtext(f"{{{NS['xdr']}}}rowOff", "0"))
    return col, row, col_off, row_off


def _parse_shape(sp, sheet_name: str, from_row, from_col, to_row, to_col,
                 from_row_off, from_col_off, to_row_off, to_col_off) -> ExcelShape | None:
    """Parse a shape (sp) element."""
    nvSpPr = sp.find(f"{{{NS['xdr']}}}nvSpPr")
    if nvSpPr is None:
        return None
    
    cNvPr = nvSpPr.find(f"{{{NS['xdr']}}}cNvPr")
    if cNvPr is None:
        return None
    
    shape_id = cNvPr.get("id", "")
    name = cNvPr.get("name", "")
    
    # Get geometry and xfrm (absolute position/size)
    geometry = None
    xfrm_x = 0
    xfrm_y = 0
    xfrm_cx = 0
    xfrm_cy = 0
    spPr = sp.find(f"{{{NS['xdr']}}}spPr")
    if spPr is not None:
        prstGeom = spPr.find(f"{{{NS['a']}}}prstGeom")
        if prstGeom is not None:
            geometry = prstGeom.get("prst")
        
        # Get xfrm (transform) for absolute position
        xfrm = spPr.find(f"{{{NS['a']}}}xfrm")
        if xfrm is not None:
            off = xfrm.find(f"{{{NS['a']}}}off")
            ext = xfrm.find(f"{{{NS['a']}}}ext")
            if off is not None:
                xfrm_x = int(off.get("x", "0"))
                xfrm_y = int(off.get("y", "0"))
            if ext is not None:
                xfrm_cx = int(ext.get("cx", "0"))
                xfrm_cy = int(ext.get("cy", "0"))
        
        # Get fill color
        solidFill = spPr.find(f"{{{NS['a']}}}solidFill")
        fill_color = None
        if solidFill is not None:
            srgb = solidFill.find(f"{{{NS['a']}}}srgbClr")
            if srgb is not None:
                fill_color = srgb.get("val")
    else:
        fill_color = None
    
    # Get text
    text = _extract_text(sp)
    
    # Compute center position (approximate, in EMU)
    # Use xfrm if available (more accurate), otherwise compute from row/col
    if xfrm_x or xfrm_y:
        center_x = xfrm_x + xfrm_cx / 2
        center_y = xfrm_y + xfrm_cy / 2
    else:
        center_x = from_col * COL_WIDTH_EMU + from_col_off + \
                   (to_col - from_col) * COL_WIDTH_EMU / 2
        center_y = from_row * ROW_HEIGHT_EMU + from_row_off + \
                   (to_row - from_row) * ROW_HEIGHT_EMU / 2
    
    return ExcelShape(
        sheet_name=sheet_name,
        shape_id=shape_id,
        name=name,
        text=text,
        geometry=geometry,
        from_row=from_row,
        from_col=from_col,
        to_row=to_row,
        to_col=to_col,
        from_row_off=from_row_off,
        from_col_off=from_col_off,
        to_row_off=to_row_off,
        to_col_off=to_col_off,
        fill_color=fill_color,
        center_x=center_x,
        center_y=center_y,
        xfrm_x=xfrm_x,
        xfrm_y=xfrm_y,
        xfrm_cx=xfrm_cx,
        xfrm_cy=xfrm_cy,
    )


def _parse_connector(cxn, sheet_name: str, from_row, from_col, to_row, to_col,
                     from_row_off, from_col_off, to_row_off, to_col_off) -> ExcelConnector | None:
    """Parse a connector (cxnSp) element."""
    nvCxnSpPr = cxn.find(f"{{{NS['xdr']}}}nvCxnSpPr")
    if nvCxnSpPr is None:
        return None
    
    cNvPr = nvCxnSpPr.find(f"{{{NS['xdr']}}}cNvPr")
    if cNvPr is None:
        return None
    
    connector_id = cNvPr.get("id", "")
    name = cNvPr.get("name", "")
    
    # Get connection endpoints
    start_shape_id = None
    end_shape_id = None
    start_idx = None
    end_idx = None
    
    cNvCxnSpPr = nvCxnSpPr.find(f"{{{NS['xdr']}}}cNvCxnSpPr")
    if cNvCxnSpPr is not None:
        stCxn = cNvCxnSpPr.find(f"{{{NS['a']}}}stCxn")
        endCxn = cNvCxnSpPr.find(f"{{{NS['a']}}}endCxn")
        
        if stCxn is not None:
            start_shape_id = stCxn.get("id")
            start_idx = int(stCxn.get("idx", "0"))
        if endCxn is not None:
            end_shape_id = endCxn.get("id")
            end_idx = int(endCxn.get("idx", "0"))
    
    # Get label text if any
    label = _extract_text(cxn)
    
    return ExcelConnector(
        sheet_name=sheet_name,
        connector_id=connector_id,
        name=name,
        start_shape_id=start_shape_id,
        end_shape_id=end_shape_id,
        start_idx=start_idx,
        end_idx=end_idx,
        from_row=from_row,
        from_col=from_col,
        to_row=to_row,
        to_col=to_col,
        from_row_off=from_row_off,
        from_col_off=from_col_off,
        to_row_off=to_row_off,
        to_col_off=to_col_off,
        label=label if label else None,
    )


def _parse_picture(pic, sheet_name: str, from_row, from_col,
                   rels_map: dict, zf: zipfile.ZipFile, 
                   images_path: Path) -> ExcelPicture | None:
    """Parse a picture (pic) element and extract the image file."""
    nvPicPr = pic.find(f"{{{NS['xdr']}}}nvPicPr")
    if nvPicPr is None:
        return None
    
    cNvPr = nvPicPr.find(f"{{{NS['xdr']}}}cNvPr")
    if cNvPr is None:
        return None
    
    pic_id = cNvPr.get("id", "")
    name = cNvPr.get("name", "")
    
    # Get image reference
    blipFill = pic.find(f"{{{NS['xdr']}}}blipFill")
    if blipFill is None:
        return None
    
    blip = blipFill.find(f"{{{NS['a']}}}blip")
    if blip is None:
        return None
    
    embed_id = blip.get(f"{{{NS['r']}}}embed", "")
    if not embed_id or embed_id not in rels_map:
        return None
    
    media_rel_path = rels_map[embed_id]
    # Resolve to full zip path
    if media_rel_path.startswith("../"):
        media_path = "xl/" + media_rel_path[3:]
    else:
        media_path = "xl/drawings/" + media_rel_path
    
    # Extract image
    output_filename = Path(media_path).name
    output_path = images_path / output_filename
    
    if media_path in zf.namelist():
        with zf.open(media_path) as src, open(output_path, "wb") as dst:
            dst.write(src.read())
        logger.info(f"  Extracted image: {output_path}")
    
    return ExcelPicture(
        sheet_name=sheet_name,
        picture_id=pic_id,
        name=name,
        media_path=media_path,
        relationship_id=embed_id,
        from_row=from_row,
        from_col=from_col,
        output_path=str(output_path),
    )


def _parse_group(grp, sheet: SheetData, from_row, from_col, to_row, to_col,
                 from_row_off, from_col_off, to_row_off, to_col_off) -> None:
    """Parse a group (grpSp) element and extract child shapes/connectors."""
    nvGrpSpPr = grp.find(f"{{{NS['xdr']}}}nvGrpSpPr")
    if nvGrpSpPr is None:
        return
    
    cNvPr = nvGrpSpPr.find(f"{{{NS['xdr']}}}cNvPr")
    group_id = cNvPr.get("id", "") if cNvPr is not None else ""
    group_name = cNvPr.get("name", "") if cNvPr is not None else ""
    
    child_shape_ids = []
    child_connector_ids = []
    
    # Parse child shapes within group
    for child_sp in grp.findall(f"{{{NS['xdr']}}}sp"):
        shape = _parse_shape(child_sp, sheet.name, from_row, from_col, to_row, to_col,
                            from_row_off, from_col_off, to_row_off, to_col_off)
        if shape:
            sheet.shapes.append(shape)
            child_shape_ids.append(shape.shape_id)
    
    # Parse child connectors within group
    for child_cxn in grp.findall(f"{{{NS['xdr']}}}cxnSp"):
        conn = _parse_connector(child_cxn, sheet.name, from_row, from_col, to_row, to_col,
                               from_row_off, from_col_off, to_row_off, to_col_off)
        if conn:
            sheet.connectors.append(conn)
            child_connector_ids.append(conn.connector_id)
    
    # Also check for nested groups
    for nested_grp in grp.findall(f"{{{NS['xdr']}}}grpSp"):
        _parse_group(nested_grp, sheet, from_row, from_col, to_row, to_col,
                    from_row_off, from_col_off, to_row_off, to_col_off)
    
    sheet.groups.append(ExcelGroup(
        sheet_name=sheet.name,
        group_id=group_id,
        name=group_name,
        child_shape_ids=child_shape_ids,
        child_connector_ids=child_connector_ids,
    ))


def _extract_text(element) -> str:
    """Extract all text from a shape or connector's txBody."""
    # Try xdr:txBody first
    txBody = element.find(f"{{{NS['xdr']}}}txBody")
    if txBody is None:
        # Try under spPr level
        txBody = element.find(f".//{{{NS['a']}}}txBody")
    if txBody is None:
        return ""
    
    paragraphs = []
    for p in txBody.findall(f"{{{NS['a']}}}p"):
        para_text = ""
        for r in p.findall(f"{{{NS['a']}}}r"):
            t = r.find(f"{{{NS['a']}}}t")
            if t is not None and t.text:
                para_text += t.text
        # Also check for field elements
        for fld in p.findall(f"{{{NS['a']}}}fld"):
            t = fld.find(f"{{{NS['a']}}}t")
            if t is not None and t.text:
                para_text += t.text
        if para_text:
            paragraphs.append(para_text)
    
    return "\n".join(paragraphs)


def _infer_missing_connections(sheet: SheetData) -> None:
    """For connectors without stCxn/endCxn, infer connections by position."""
    if not sheet.shapes:
        return
    
    # Build shape position index
    shape_positions = {}
    for shape in sheet.shapes:
        if shape.from_row is not None and shape.from_col is not None:
            shape_positions[shape.shape_id] = (
                shape.center_x,
                shape.center_y,
            )
    
    for conn in sheet.connectors:
        if conn.start_shape_id and conn.end_shape_id:
            continue  # Already has explicit connections
        
        # Compute connector start and end positions
        start_x = (conn.from_col or 0) * COL_WIDTH_EMU + conn.from_col_off
        start_y = (conn.from_row or 0) * ROW_HEIGHT_EMU + conn.from_row_off
        end_x = (conn.to_col or 0) * COL_WIDTH_EMU + conn.to_col_off
        end_y = (conn.to_row or 0) * ROW_HEIGHT_EMU + conn.to_row_off
        
        # Find nearest shape to start point
        if not conn.start_shape_id:
            nearest_start = _find_nearest_shape(start_x, start_y, shape_positions)
            if nearest_start:
                conn.start_shape_id = nearest_start
                conn.inferred = True
        
        # Find nearest shape to end point
        if not conn.end_shape_id:
            nearest_end = _find_nearest_shape(end_x, end_y, shape_positions)
            if nearest_end and nearest_end != conn.start_shape_id:
                conn.end_shape_id = nearest_end
                conn.inferred = True


def _find_nearest_shape(x: float, y: float, 
                        shape_positions: dict[str, tuple[float, float]],
                        max_distance: float = 5_000_000) -> str | None:
    """Find the nearest shape to a point within max_distance (EMU)."""
    best_id = None
    best_dist = max_distance
    
    for sid, (sx, sy) in shape_positions.items():
        dist = ((x - sx) ** 2 + (y - sy) ** 2) ** 0.5
        if dist < best_dist:
            best_dist = dist
            best_id = sid
    
    return best_id
