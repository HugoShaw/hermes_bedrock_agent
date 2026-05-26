"""Flow semantic builder - constructs flow_spec from classified objects.

This is the CORE semantic layer that transforms raw shapes/connectors
into a meaningful flow specification with:
- Properly classified nodes (not edge labels!)
- Edges with labels from nearby text shapes
- Decision branches with conditions
- Main flow spine identification
- Confidence scoring
"""
import re
import logging
from typing import Optional
from .models import ExcelShape, ExcelConnector, SheetData
from .flow_spec_models import (
    FlowSpec, FlowNode, FlowEdge, FlowLane, ExcludedObject, FlowWarning,
    Evidence, NodeType, NodeRole, EdgeType, ReviewStatus, RegionSpec
)
from .object_classifier import classify_shape, generate_semantic_id

logger = logging.getLogger(__name__)


def build_flow_spec(sheet: SheetData, regions: list[RegionSpec],
                    source_excel: str = "") -> FlowSpec:
    """Build complete flow specification for a sheet.
    
    Pipeline:
    1. Classify all shapes
    2. Identify edge labels vs flow nodes
    3. Build nodes from flow-role shapes
    4. Build edges from connectors + attach labels
    5. Identify main flow spine
    6. Score confidence
    """
    # Step 1: Classify all shapes
    classifications = {}
    for shape in sheet.shapes:
        classifications[shape.shape_id] = classify_shape(
            shape, sheet.shapes, sheet.connectors
        )
    
    # Step 2: Separate nodes from edge labels
    flow_shapes = []  # Will become nodes
    edge_label_shapes = []  # Will become edge labels
    excluded = []
    
    for shape in sheet.shapes:
        cls = classifications[shape.shape_id]
        if cls["role"] == "edge_label":
            edge_label_shapes.append(shape)
        elif cls["role"] == "container":
            excluded.append(ExcludedObject(
                object_id=shape.shape_id,
                object_type="shape",
                text=shape.text or "",
                exclude_reason="Container/region boundary"
            ))
        elif cls["role"] == "ignored":
            excluded.append(ExcludedObject(
                object_id=shape.shape_id,
                object_type="shape",
                text=shape.text or "",
                exclude_reason=cls["reason"]
            ))
        elif cls["is_flow_node"]:
            flow_shapes.append(shape)
        else:
            excluded.append(ExcludedObject(
                object_id=shape.shape_id,
                object_type="shape",
                text=shape.text or "",
                exclude_reason=cls["reason"]
            ))
    
    # Step 3: Build flow nodes
    existing_ids = set()
    nodes = []
    shape_to_node = {}  # shape_id -> node_id mapping
    
    for shape in flow_shapes:
        cls = classifications[shape.shape_id]
        text = (shape.text or "").strip()
        
        node_id = generate_semantic_id(text, existing_ids)
        node_type = NodeType(cls["node_type"]) if cls["node_type"] in [e.value for e in NodeType] else NodeType.PROCESS
        role = NodeRole(cls["role"]) if cls["role"] in [e.value for e in NodeRole] else NodeRole.BUSINESS_STEP
        
        # Find which region this shape belongs to
        region_id = _find_shape_region(shape.shape_id, regions)
        
        node = FlowNode(
            node_id=node_id,
            original_shape_id=shape.shape_id,
            text=text,
            normalized_text=_normalize_text(text),
            node_type=node_type,
            role=role,
            region_id=region_id,
            bbox={"x": shape.x or 0, "y": shape.y or 0,
                  "w": shape.width or 0, "h": shape.height or 0},
            evidence=Evidence(
                shape_ids=[shape.shape_id],
                text_source=text,
                geometry=shape.geometry or "",
                position=f"({shape.x},{shape.y})"
            ),
            confidence=cls["confidence"],
            review_status=ReviewStatus.OK if cls["confidence"] >= 0.8 else ReviewStatus.UNCERTAIN,
            reason=cls["reason"]
        )
        nodes.append(node)
        shape_to_node[shape.shape_id] = node_id
    
    # Step 4: Build edge label lookup (shape_id -> label text + position)
    edge_label_lookup = {}
    for shape in edge_label_shapes:
        edge_label_lookup[shape.shape_id] = {
            "text": (shape.text or "").strip(),
            "x": shape.center_x or shape.x,
            "y": shape.center_y or shape.y,
            "shape_id": shape.shape_id,
        }
    
    # Step 5: Build edges from connectors (two-pass for exclusive label assignment)
    edges = []
    warnings = []
    edge_idx = 0
    used_label_shape_ids = set()  # Track exclusively assigned labels
    
    # --- Pass 1: resolve direct connector->label connections ---
    for conn in sheet.connectors:
        edge_idx += 1
        
        start_id = conn.start_shape_id
        end_id = conn.end_shape_id
        
        # Resolve connector endpoints to flow nodes
        from_node = shape_to_node.get(start_id)
        to_node = shape_to_node.get(end_id)
        
        # If endpoint is an edge label, follow through to next connector
        # or use the label as the edge's label text
        label = ""
        edge_type = EdgeType.NORMAL
        
        # Check if either endpoint is actually an edge label
        if start_id in edge_label_lookup:
            label = edge_label_lookup[start_id]["text"]
            edge_type = _classify_edge_type(label)
            # The actual source is something else - try to find it
            resolved_source = _find_actual_source(start_id, sheet.connectors, shape_to_node)
            if resolved_source:
                from_node = resolved_source
                used_label_shape_ids.add(start_id)
            else:
                # Cannot resolve source - don't consume the label
                label = ""
                edge_type = EdgeType.NORMAL
        
        if end_id in edge_label_lookup:
            label = edge_label_lookup[end_id]["text"]
            edge_type = _classify_edge_type(label)
            # The actual target is something else - try to find it
            resolved_target = _find_actual_target(end_id, sheet.connectors, shape_to_node)
            if resolved_target:
                to_node = resolved_target
                used_label_shape_ids.add(end_id)
            else:
                # Cannot resolve target - don't consume the label
                label = ""
                edge_type = EdgeType.NORMAL
        
        if not from_node or not to_node:
            # Unresolvable edge
            if from_node or to_node:
                warnings.append(FlowWarning(
                    warning_id=f"w_edge_{edge_idx}",
                    message=f"Connector {conn.connector_id}: partially resolved "
                            f"(from={from_node}, to={to_node})",
                    severity="medium",
                    related_objects=[conn.connector_id]
                ))
            continue
        
        edge = FlowEdge(
            edge_id=f"e_{edge_idx:03d}",
            from_node_id=from_node,
            to_node_id=to_node,
            label=label,
            condition=label if edge_type != EdgeType.NORMAL else "",
            edge_type=edge_type,
            evidence=Evidence(
                connector_ids=[conn.connector_id],
                text_source=label,
                ooxml_reason=f"stCxn={start_id} endCxn={end_id}",
                visual_reason=f"arrow={'→' if conn.has_arrow else '—'}"
            ),
            confidence=0.8 if from_node and to_node else 0.5,
            review_status=ReviewStatus.OK if label or (from_node and to_node) else ReviewStatus.UNCERTAIN,
            reason=f"From connector {conn.connector_id}"
        )
        edges.append(edge)
    
    # --- Pass 2: exclusive spatial assignment of remaining labels to unlabeled decision edges ---
    remaining_labels = [
        edge_label_lookup[sid] for sid in edge_label_lookup
        if sid not in used_label_shape_ids
    ]
    
    if remaining_labels:
        # Find unlabeled edges from decision nodes
        unlabeled_decision_edges = []
        for edge in edges:
            if edge.label:
                continue
            src_node = next((n for n in nodes if n.node_id == edge.from_node_id), None)
            if src_node and src_node.node_type == NodeType.DECISION:
                unlabeled_decision_edges.append(edge)
        
        if unlabeled_decision_edges:
            # Compute all (label, edge) distances for optimal assignment
            assignments = _optimal_label_assignment(
                remaining_labels, unlabeled_decision_edges, nodes, sheet.shapes
            )
            for label_info, edge in assignments:
                edge.label = label_info["text"]
                edge.condition = label_info["text"]
                edge.edge_type = _classify_edge_type(label_info["text"])
                edge.evidence.text_source = label_info["text"]
                edge.confidence = max(edge.confidence, 0.75)
                used_label_shape_ids.add(label_info["shape_id"])
    
    # Step 6: Try to infer missing edges from spatial layout
    inferred_edges = _infer_edges_from_layout(nodes, edges, regions, sheet.shapes)
    edges.extend(inferred_edges)
    
    # Build lanes from regions
    lanes = []
    for region in regions:
        lanes.append(FlowLane(
            lane_id=region.region_id,
            title=region.title,
            bbox=region.bbox,
            evidence_shape_ids=[region.container_shape_id] if region.container_shape_id else []
        ))
    
    # Assemble flow spec
    flow_spec = FlowSpec(
        source_excel=source_excel,
        sheet_name=sheet.sheet_name,
        region_id="full_sheet",
        region_title=sheet.sheet_name,
        confidence=_compute_overall_confidence(nodes, edges),
        lanes=lanes,
        nodes=nodes,
        edges=edges,
        excluded_objects=excluded,
        warnings=warnings
    )
    
    logger.info(
        f"Built flow_spec: {len(nodes)} nodes, {len(edges)} edges, "
        f"{len(excluded)} excluded, {len(warnings)} warnings"
    )
    return flow_spec


def _find_shape_region(shape_id: str, regions: list[RegionSpec]) -> str:
    """Find which region a shape belongs to."""
    for region in regions:
        if shape_id in region.shape_ids:
            return region.region_id
    return "main_flow"


def _normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    result = text.replace("\n", " ").strip()
    for fw, hw in zip("０１２３４５６７８９", "0123456789"):
        result = result.replace(fw, hw)
    return result


def _classify_edge_type(label: str) -> EdgeType:
    """Classify edge type from label text."""
    if not label:
        return EdgeType.NORMAL
    
    label_lower = label.lower()
    
    if any(kw in label for kw in ["正常終了の場合", "正常", "成功"]):
        return EdgeType.OK_BRANCH
    if any(kw in label for kw in ["正常終了ではない場合", "異常", "失敗"]):
        return EdgeType.NG_BRANCH
    if any(kw in label for kw in ["エラー", "例外"]):
        return EdgeType.ERROR_BRANCH
    if label_lower in ("yes", "はい", "ok"):
        return EdgeType.YES_BRANCH
    if label_lower in ("no", "いいえ", "ng"):
        return EdgeType.NO_BRANCH
    if "の場合" in label:
        return EdgeType.CONDITION
    
    return EdgeType.NORMAL


def _find_actual_source(label_shape_id: str, connectors: list[ExcelConnector],
                       shape_to_node: dict) -> Optional[str]:
    """If a connector points TO an edge-label shape, find what actually feeds it."""
    for conn in connectors:
        if conn.end_shape_id == label_shape_id:
            if conn.start_shape_id in shape_to_node:
                return shape_to_node[conn.start_shape_id]
    return None


def _find_actual_target(label_shape_id: str, connectors: list[ExcelConnector],
                       shape_to_node: dict) -> Optional[str]:
    """If a connector points FROM an edge-label shape, find what it feeds into."""
    for conn in connectors:
        if conn.start_shape_id == label_shape_id:
            if conn.end_shape_id in shape_to_node:
                return shape_to_node[conn.end_shape_id]
    return None


def _optimal_label_assignment(remaining_labels: list[dict], 
                              unlabeled_edges: list[FlowEdge],
                              nodes: list[FlowNode],
                              shapes: list[ExcelShape]) -> list[tuple[dict, FlowEdge]]:
    """Greedy optimal assignment of edge labels to unlabeled decision edges.
    
    Algorithm:
    1. For each (label, edge) pair, compute a distance score.
    2. Sort all pairs by score (ascending = closer = better).
    3. Greedy assign: pick best unassigned pair, mark both as used.
    
    Returns list of (label_info, edge) tuples.
    """
    if not remaining_labels or not unlabeled_edges:
        return []
    
    # Build node position lookup
    node_positions = {}
    for node in nodes:
        node_positions[node.node_id] = (
            node.bbox.get("x", 0),
            node.bbox.get("y", 0)
        )
    
    # Compute all (label, edge, score) triples
    candidates = []
    for label_info in remaining_labels:
        lx = label_info["x"]
        ly = label_info["y"]
        if lx == 0 and ly == 0:
            continue  # Skip labels with no position
        
        for edge in unlabeled_edges:
            # Get source decision position
            src_pos = node_positions.get(edge.from_node_id, (0, 0))
            tgt_pos = node_positions.get(edge.to_node_id, (0, 0))
            
            sx, sy = src_pos
            tx, ty = tgt_pos
            
            # Mid-point of edge
            mx = (sx + tx) / 2
            my = (sy + ty) / 2
            
            # Distance from label to edge midpoint
            dist_mid = ((lx - mx) ** 2 + (ly - my) ** 2) ** 0.5
            
            # Distance from label to source (labels are often near source)
            dist_src = ((lx - sx) ** 2 + (ly - sy) ** 2) ** 0.5
            
            # Distance from label to target (labels sometimes closer to target)
            dist_tgt = ((lx - tx) ** 2 + (ly - ty) ** 2) ** 0.5
            
            # Score: prefer label near the edge path
            # In LR flowcharts, x-alignment with target is strongest signal
            x_align_tgt = abs(lx - tx)
            y_align_mid = abs(ly - my)
            
            # Combined score: x-alignment to target is primary, y-proximity to midpoint is secondary
            score = min(
                dist_mid,
                dist_src * 1.1,
                dist_tgt * 1.3,
                x_align_tgt + y_align_mid * 2  # Favor x-aligned labels
            )
            
            candidates.append((score, label_info, edge))
    
    # Sort by score
    candidates.sort(key=lambda x: x[0])
    
    # Greedy exclusive assignment
    used_labels = set()
    used_edges = set()
    assignments = []
    
    for score, label_info, edge in candidates:
        lid = label_info["shape_id"]
        eid = edge.edge_id
        if lid in used_labels or eid in used_edges:
            continue
        # Only assign if within reasonable distance (10M EMU ~ roughly half the chart width)
        if score > 10000000:
            continue
        assignments.append((label_info, edge))
        used_labels.add(lid)
        used_edges.add(eid)
    
    return assignments


def _find_nearby_label(conn: ExcelConnector, label_shapes: list[ExcelShape],
                      all_shapes: list[ExcelShape]) -> str:
    """Find the nearest edge-label shape to a connector.
    
    Strategy: Find label shapes that are positioned between the start and end shapes,
    or very close to the connector path. Uses both midpoint proximity and 
    direction-aware matching.
    """
    # Get connector endpoint shapes
    start_shape = next((s for s in all_shapes if s.shape_id == conn.start_shape_id), None)
    end_shape = next((s for s in all_shapes if s.shape_id == conn.end_shape_id), None)
    
    if not start_shape or not end_shape:
        return ""
    
    # Use center positions (prefer center_x/y which includes xfrm data)
    sx = start_shape.center_x or start_shape.x
    sy = start_shape.center_y or start_shape.y
    ex = end_shape.center_x or end_shape.x
    ey = end_shape.center_y or end_shape.y
    
    # Midpoint of the connector
    mid_x = (sx + ex) / 2
    mid_y = (sy + ey) / 2
    
    # Connector length for scale
    conn_len = ((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5
    if conn_len == 0:
        conn_len = 1000000  # default 1M EMU
    
    # Find closest label shape
    best_label = ""
    best_score = float("inf")
    
    # Threshold: max distance from midpoint (adaptive: 60% of connector length, min 3M EMU)
    max_dist = max(conn_len * 0.6, 3000000)
    
    for label_shape in label_shapes:
        lx = label_shape.center_x or label_shape.x
        ly = label_shape.center_y or label_shape.y
        
        if lx == 0 and ly == 0:
            continue  # Skip shapes with no position
        
        # Distance from midpoint
        dist_mid = ((lx - mid_x) ** 2 + (ly - mid_y) ** 2) ** 0.5
        
        # Distance from start shape (labels tend to be near the source decision)
        dist_start = ((lx - sx) ** 2 + (ly - sy) ** 2) ** 0.5
        
        # Use minimum of midpoint distance and start-proximity
        dist = min(dist_mid, dist_start * 1.2)
        
        if dist < max_dist and dist < best_score:
            best_score = dist
            best_label = (label_shape.text or "").strip()
    
    return best_label


def _infer_edges_from_layout(nodes: list[FlowNode], existing_edges: list[FlowEdge],
                            regions: list[RegionSpec],
                            shapes: list[ExcelShape]) -> list[FlowEdge]:
    """Infer missing edges from spatial layout when connectors are missing.
    
    Strategy: Within each region, if shapes are arranged linearly (left-to-right
    or top-to-bottom) and no explicit connector exists, infer sequential flow.
    """
    inferred = []
    
    # Get set of already-connected node pairs
    connected = set()
    for edge in existing_edges:
        connected.add((edge.from_node_id, edge.to_node_id))
    
    # Get nodes with existing connections
    has_incoming = set(e.to_node_id for e in existing_edges)
    has_outgoing = set(e.from_node_id for e in existing_edges)
    
    # For now, only infer for nodes that have NO connections at all
    # and are spatially adjacent within the same region
    # This is conservative to avoid false positives
    
    # Group nodes by region
    region_nodes = {}
    for node in nodes:
        rid = node.region_id
        if rid not in region_nodes:
            region_nodes[rid] = []
        region_nodes[rid].append(node)
    
    # Within each region, sort by position and connect isolated nodes
    edge_idx = len(existing_edges) + 1
    for rid, rnodes in region_nodes.items():
        if len(rnodes) < 2:
            continue
        
        # Sort by x then y (left-to-right reading)
        rnodes_sorted = sorted(rnodes, key=lambda n: (n.bbox.get("x", 0), n.bbox.get("y", 0)))
        
        for i in range(len(rnodes_sorted) - 1):
            curr = rnodes_sorted[i]
            nxt = rnodes_sorted[i + 1]
            
            # Only infer if both nodes have no connections
            if (curr.node_id in has_outgoing or nxt.node_id in has_incoming):
                continue
            if (curr.node_id, nxt.node_id) in connected:
                continue
            
            # Check spatial proximity
            dx = abs(nxt.bbox.get("x", 0) - curr.bbox.get("x", 0))
            dy = abs(nxt.bbox.get("y", 0) - curr.bbox.get("y", 0))
            
            if dx < 5000000 and dy < 5000000:  # Reasonable proximity
                edge = FlowEdge(
                    edge_id=f"e_infer_{edge_idx:03d}",
                    from_node_id=curr.node_id,
                    to_node_id=nxt.node_id,
                    edge_type=EdgeType.INFERRED,
                    evidence=Evidence(
                        visual_reason=f"Spatial adjacency in region {rid}",
                        position=f"dx={dx}, dy={dy}"
                    ),
                    confidence=0.4,
                    review_status=ReviewStatus.UNCERTAIN,
                    reason=f"Inferred from spatial layout in {rid}"
                )
                inferred.append(edge)
                edge_idx += 1
                connected.add((curr.node_id, nxt.node_id))
    
    if inferred:
        logger.info(f"Inferred {len(inferred)} edges from spatial layout")
    
    return inferred


def _compute_overall_confidence(nodes: list[FlowNode], edges: list[FlowEdge]) -> float:
    """Compute overall flow spec confidence."""
    if not nodes:
        return 0.0
    
    node_conf = sum(n.confidence for n in nodes) / len(nodes) if nodes else 0
    edge_conf = sum(e.confidence for e in edges) / len(edges) if edges else 0
    
    # Weight edges more since they define the flow
    return 0.4 * node_conf + 0.6 * edge_conf if edges else node_conf * 0.5
