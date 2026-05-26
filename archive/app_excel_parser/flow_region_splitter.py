"""Flow region splitter - identifies logical regions/containers in Excel flowchart.

Regions are functional modules (機能No), swim lanes, or spatially clustered groups.
Shapes within a container's bounding box belong to that region.
"""
import re
import logging
from typing import Optional
from .models import ExcelShape, ExcelConnector, SheetData
from .flow_spec_models import RegionSpec

logger = logging.getLogger(__name__)


def split_into_regions(sheet: SheetData) -> list[RegionSpec]:
    """Identify and split a sheet into logical regions.
    
    Strategy:
    1. Find container shapes (機能No pattern + large area)
    2. Assign smaller shapes to containers by bounding box containment
    3. Shapes not in any container go into "main_flow" region
    4. Connectors assigned to the region containing their endpoints
    """
    containers = _find_containers(sheet.shapes)
    
    if not containers:
        # No explicit containers - treat entire sheet as one region
        return [RegionSpec(
            region_id="main_flow",
            sheet_name=sheet.sheet_name,
            title=f"{sheet.sheet_name} - Main Flow",
            shape_ids=[s.shape_id for s in sheet.shapes],
            connector_ids=[c.connector_id for c in sheet.connectors],
            bbox=_compute_bbox(sheet.shapes),
            region_type="full_sheet",
            confidence=0.9,
            reason="No container shapes found, treating as single region"
        )]
    
    # Sort containers by x position (left to right) then y
    containers.sort(key=lambda c: (c[1].get("x", 0), c[1].get("y", 0)))
    
    regions = []
    assigned_shapes = set()
    
    # Create a region for each container
    for i, (container_shape, bbox) in enumerate(containers, 1):
        region_id = f"region_{i:03d}"
        title = _extract_region_title(container_shape)
        
        # Find shapes within this container's bbox
        contained_shapes = _find_contained_shapes(
            sheet.shapes, bbox, container_shape.shape_id, assigned_shapes
        )
        contained_shape_ids = [s.shape_id for s in contained_shapes]
        assigned_shapes.update(contained_shape_ids)
        assigned_shapes.add(container_shape.shape_id)
        
        # Find connectors with both endpoints in this region
        region_connectors = _find_region_connectors(
            sheet.connectors, contained_shape_ids + [container_shape.shape_id]
        )
        
        regions.append(RegionSpec(
            region_id=region_id,
            sheet_name=sheet.sheet_name,
            title=title,
            container_shape_id=container_shape.shape_id,
            bbox=bbox,
            shape_ids=contained_shape_ids,
            connector_ids=[c.connector_id for c in region_connectors],
            region_type="function_module",
            confidence=0.85,
            reason=f"Container shape '{container_shape.text}' with {len(contained_shapes)} children"
        ))
    
    # Collect unassigned shapes into main_flow region
    unassigned = [s for s in sheet.shapes 
                  if s.shape_id not in assigned_shapes]
    if unassigned:
        # Find connectors for unassigned shapes
        unassigned_ids = [s.shape_id for s in unassigned]
        main_connectors = _find_region_connectors(sheet.connectors, unassigned_ids)
        
        # Also add cross-region connectors
        all_assigned_connector_ids = set()
        for r in regions:
            all_assigned_connector_ids.update(r.connector_ids)
        cross_connectors = [c for c in sheet.connectors 
                           if c.connector_id not in all_assigned_connector_ids]
        
        main_connector_ids = list(set(
            [c.connector_id for c in main_connectors] +
            [c.connector_id for c in cross_connectors]
        ))
        
        regions.insert(0, RegionSpec(
            region_id="main_flow",
            sheet_name=sheet.sheet_name,
            title=f"{sheet.sheet_name} - Main Flow (Spine)",
            shape_ids=unassigned_ids,
            connector_ids=main_connector_ids,
            bbox=_compute_bbox(unassigned),
            region_type="main_flow",
            confidence=0.9,
            reason=f"Unassigned shapes forming main flow spine ({len(unassigned)} shapes)"
        ))
    
    logger.info(f"Split sheet '{sheet.sheet_name}' into {len(regions)} regions")
    return regions


def _find_containers(shapes: list[ExcelShape]) -> list[tuple[ExcelShape, dict]]:
    """Find shapes that are containers (機能No boxes)."""
    containers = []
    
    for shape in shapes:
        text = (shape.text or "").strip()
        # Check for 機能No pattern
        if not re.search(r"機能No|機能Ｎｏ", text):
            continue
        
        # Check area - containers should be large
        w = shape.width or 0
        h = shape.height or 0
        area = w * h
        
        if area < 1000000:  # Too small to be a real container
            continue
        
        bbox = {
            "x": shape.from_col or 0,
            "y": shape.from_row or 0,
            "x2": shape.to_col or 0,
            "y2": shape.to_row or 0,
            "emu_x": shape.x or 0,
            "emu_y": shape.y or 0,
            "emu_x2": (shape.x or 0) + w,
            "emu_y2": (shape.y or 0) + h,
        }
        containers.append((shape, bbox))
    
    return containers


def _find_contained_shapes(shapes: list[ExcelShape], bbox: dict,
                           container_id: str, 
                           already_assigned: set[str]) -> list[ExcelShape]:
    """Find shapes that fall within the container's bounding box."""
    contained = []
    
    for shape in shapes:
        if shape.shape_id == container_id:
            continue
        if shape.shape_id in already_assigned:
            continue
        
        # Check if shape center is within container bbox (using EMU coordinates)
        sx = shape.x or 0
        sy = shape.y or 0
        sw = shape.width or 0
        sh = shape.height or 0
        cx = sx + sw / 2
        cy = sy + sh / 2
        
        if (bbox["emu_x"] <= cx <= bbox["emu_x2"] and
            bbox["emu_y"] <= cy <= bbox["emu_y2"]):
            contained.append(shape)
    
    return contained


def _find_region_connectors(connectors: list[ExcelConnector],
                           shape_ids: list[str]) -> list[ExcelConnector]:
    """Find connectors with at least one endpoint in the given shape set."""
    shape_set = set(shape_ids)
    result = []
    for conn in connectors:
        start_in = conn.start_shape_id in shape_set
        end_in = conn.end_shape_id in shape_set
        if start_in or end_in:
            result.append(conn)
    return result


def _extract_region_title(shape: ExcelShape) -> str:
    """Extract clean title from a container shape."""
    text = (shape.text or "").strip()
    # Clean up multi-line: take first meaningful line
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        return lines[0]
    return text


def _compute_bbox(shapes: list[ExcelShape]) -> dict:
    """Compute bounding box for a list of shapes."""
    if not shapes:
        return {"x": 0, "y": 0, "x2": 0, "y2": 0}
    
    min_x = min((s.x or 0) for s in shapes)
    min_y = min((s.y or 0) for s in shapes)
    max_x = max((s.x or 0) + (s.width or 0) for s in shapes)
    max_y = max((s.y or 0) + (s.height or 0) for s in shapes)
    
    return {
        "emu_x": min_x, "emu_y": min_y,
        "emu_x2": max_x, "emu_y2": max_y,
    }
