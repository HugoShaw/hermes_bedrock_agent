"""Object classifier for Excel shapes.

Classifies shapes into semantic roles:
- process_step: actual flow steps
- decision_point: branching decisions
- edge_label: branch condition text (NOT a node)
- container: grouping boxes (機能No)
- annotation: notes, comments
- start_end: start/end terminators
- data_object: files, DBs
- ignored: decorative elements
"""
import re
import logging
from .models import ExcelShape, ExcelConnector

logger = logging.getLogger(__name__)

# Patterns for edge labels - these should NOT become nodes
EDGE_LABEL_PATTERNS = [
    r"^(Yes|No|YES|NO|OK|NG|はい|いいえ|正常|異常|成功|失敗|エラー|例外|あり|なし|有|無)$",
    r"の場合$",
    r"^[０-９0-9]+（.+?）の場合$",
    r"^正常終了(の場合|ではない場合)$",
    r"^(金額数量|変更事由)による.+の場合$",
    r"^(納期|工期)の場合$",
    r"^その他の場合$",
    r"^[0-9]+ or [0-9]+（.+?）の場合$",
    r"^3 or 4（削除）の場合$",
]

# Patterns for decision nodes
DECISION_PATTERNS = [
    r"判定", r"判断", r"確認", r"チェック", r"分岐",
    r"^条件[：:]", r"OK\?", r"NG\?", r"有無",
    r"トークン分岐",
]

# Long annotation patterns - these look like decisions but are actually notes
ANNOTATION_PATTERNS = [
    r"^・.{20,}",  # Bullet point with 20+ chars = annotation, not decision
    r"^※.{10,}",  # Note prefix with long text
]

# Patterns for container/region titles
CONTAINER_PATTERNS = [
    r"機能No\d+", r"機能Ｎｏ\d+", r"^No\.\d+",
]

# Patterns for start/end
START_END_PATTERNS = [
    r"^開始$", r"^終了$", r"^END$", r"^START$",
    r"^スタート$", r"^エンド$",
]

# Known loop markers
LOOP_PATTERNS = [
    r"ループ", r"繰り返す", r"の数だけ",
]


def classify_shape(shape: ExcelShape, all_shapes: list[ExcelShape],
                   connectors: list[ExcelConnector]) -> dict:
    """Classify a shape into its semantic role.
    
    Returns dict with:
        role: str - semantic role
        node_type: str - flow node type
        is_flow_node: bool - whether this should be a Mermaid node
        confidence: float
        reason: str
    """
    text = (shape.text or "").strip()
    normalized = _normalize_text(text)
    geom = (shape.geometry or "").lower()
    
    result = {
        "role": "unknown",
        "node_type": "unknown",
        "is_flow_node": True,
        "confidence": 0.5,
        "reason": "",
    }
    
    # 1. No text → likely decorative or background
    if not text:
        result["role"] = "ignored"
        result["node_type"] = "unknown"
        result["is_flow_node"] = False
        result["confidence"] = 0.9
        result["reason"] = "No text content"
        return result
    
    # 2. Check if it's a container (機能No pattern + large area)
    for pattern in CONTAINER_PATTERNS:
        if re.search(pattern, text):
            area = (shape.width or 0) * (shape.height or 0)
            if area > 5000000:  # Large shape
                result["role"] = "container"
                result["node_type"] = "container"
                result["is_flow_node"] = False
                result["confidence"] = 0.95
                result["reason"] = f"Container pattern '{pattern}' + large area"
                return result
    
    # 3. Check if it's an edge label
    if _is_edge_label(shape, all_shapes, connectors):
        result["role"] = "edge_label"
        result["node_type"] = "unknown"
        result["is_flow_node"] = False
        result["confidence"] = 0.85
        result["reason"] = "Matches edge label pattern"
        return result
    
    # 4a. Check if it's an annotation (long bullet-point text)
    for pattern in ANNOTATION_PATTERNS:
        if re.search(pattern, text):
            result["role"] = "annotation"
            result["node_type"] = "note"
            result["is_flow_node"] = False
            result["confidence"] = 0.85
            result["reason"] = f"Annotation pattern: {pattern}"
            return result
    
    # 4. Check geometry for decision
    if geom in ("diamond", "flowchartdecision"):
        result["role"] = "condition"
        result["node_type"] = "decision"
        result["is_flow_node"] = True
        result["confidence"] = 0.95
        result["reason"] = f"Diamond geometry: {geom}"
        return result
    
    # 5. Check text for decision patterns
    for pattern in DECISION_PATTERNS:
        if re.search(pattern, text):
            result["role"] = "condition"
            result["node_type"] = "decision"
            result["is_flow_node"] = True
            result["confidence"] = 0.8
            result["reason"] = f"Decision text pattern: {pattern}"
            return result
    
    # 6. Check for start/end
    for pattern in START_END_PATTERNS:
        if re.search(pattern, normalized):
            result["role"] = "business_step"
            result["node_type"] = "start" if "開始" in text or "START" in text else "end"
            result["is_flow_node"] = True
            result["confidence"] = 0.95
            result["reason"] = f"Start/end pattern: {pattern}"
            return result
    
    if geom in ("flowchartterminator", "ellipse"):
        result["role"] = "business_step"
        result["node_type"] = "start"
        result["is_flow_node"] = True
        result["confidence"] = 0.85
        result["reason"] = f"Terminator geometry: {geom}"
        return result
    
    # 7. Check for loop markers
    for pattern in LOOP_PATTERNS:
        if re.search(pattern, text):
            result["role"] = "loop_marker"
            result["node_type"] = "loop"
            result["is_flow_node"] = True
            result["confidence"] = 0.8
            result["reason"] = f"Loop pattern: {pattern}"
            return result
    
    # 8. Check for data objects
    if any(kw in text for kw in ["ファイル書込", "ファイル読込", "ファイルの作成"]):
        result["role"] = "business_step"
        result["node_type"] = "process"
        result["is_flow_node"] = True
        result["confidence"] = 0.85
        result["reason"] = "File operation step"
        return result
    
    # 9. Check for API calls
    if any(kw in text for kw in ["API", "GET：", "POST：", "PUT：", "DELETE：", "【Send】"]):
        result["role"] = "system_action"
        result["node_type"] = "process"
        result["is_flow_node"] = True
        result["confidence"] = 0.9
        result["reason"] = "API call pattern"
        return result
    
    # 10. Default: if it has meaningful text and reasonable size, it's a process step
    if len(text) > 1 and text != "？":
        result["role"] = "business_step"
        result["node_type"] = "process"
        result["is_flow_node"] = True
        result["confidence"] = 0.7
        result["reason"] = "Default: text with process-like content"
        return result
    
    # Fallback
    result["role"] = "annotation"
    result["node_type"] = "note"
    result["is_flow_node"] = False
    result["confidence"] = 0.5
    result["reason"] = "Fallback: short or unclear text"
    return result


def _is_edge_label(shape: ExcelShape, all_shapes: list[ExcelShape],
                   connectors: list[ExcelConnector]) -> bool:
    """Determine if a shape is an edge label rather than a flow node.
    
    Edge labels are characterized by:
    1. Text matches known patterns (～の場合, Yes/No, etc.)
    2. Small area relative to process shapes
    3. Located near decision nodes
    4. Not directly connected as a connector endpoint (or only loosely)
    """
    text = (shape.text or "").strip()
    
    # Check against edge label patterns
    for pattern in EDGE_LABEL_PATTERNS:
        if re.search(pattern, text):
            return True
    
    # Short text that looks like a condition result
    if len(text) <= 15 and text.endswith("の場合"):
        return True
    
    return False


def _normalize_text(text: str) -> str:
    """Normalize text for pattern matching."""
    # Full-width to half-width numbers
    result = text
    for fw, hw in zip("０１２３４５６７８９", "0123456789"):
        result = result.replace(fw, hw)
    return result.strip()


def generate_semantic_id(text: str, existing_ids: set[str]) -> str:
    """Generate a semantic Mermaid-safe ID from Japanese/English text.
    
    Strategy:
    1. Extract key terms
    2. Transliterate to safe ASCII
    3. Ensure uniqueness
    """
    if not text:
        return _unique_id("NODE", existing_ids)
    
    # Known translations for common terms
    translations = {
        "トークン取得": "TOKEN_GET",
        "トークン分岐": "TOKEN_CHECK",
        "開始": "START",
        "終了": "END",
        "税率処理": "TAX_PROCESS",
        "変数初期化処理": "VAR_INIT",
        "処理結果ファイル書込": "RESULT_WRITE",
        "処理結果読込": "RESULT_READ",
        "エラー結果抽出": "ERR_EXTRACT",
        "RETファイル書込": "RET_WRITE",
        "ヘッダ明細マージ": "HD_MERGE",
        "フォルダ圧縮": "FOLDER_ZIP",
        "リターンファイル移動": "RET_MOVE",
    }
    
    # Direct match
    clean_text = text.split("\n")[0].strip()
    if clean_text in translations:
        base = translations[clean_text]
        return _unique_id(base, existing_ids)
    
    # Pattern-based generation
    base = _text_to_id(clean_text)
    return _unique_id(base, existing_ids)


def _text_to_id(text: str) -> str:
    """Convert Japanese text to a safe ID."""
    # Remove special chars, keep alphanumeric and some Japanese
    # Strategy: extract key action words and objects
    
    # API patterns
    m = re.match(r"(GET|POST|PUT|DELETE)[：:](.+?)API", text)
    if m:
        verb = m.group(1)
        obj = m.group(2).strip()
        obj_id = _jp_to_short(obj)
        return f"{verb}_{obj_id}_API"
    
    # File operations
    m = re.match(r"(.+?)ファイル(書込|読込|作成|削除|移動)", text)
    if m:
        obj = _jp_to_short(m.group(1))
        action = {"書込": "WRITE", "読込": "READ", "作成": "CREATE",
                  "削除": "DELETE", "移動": "MOVE"}[m.group(2)]
        return f"{obj}_FILE_{action}"
    
    # Data edit
    if "編集" in text:
        obj = _jp_to_short(text.split("編集")[0])
        return f"{obj}_EDIT"
    
    # Default: truncate and sanitize
    safe = re.sub(r'[^a-zA-Z0-9]', '_', text[:30])
    safe = re.sub(r'_+', '_', safe).strip('_')
    if safe and safe[0].isdigit():
        safe = "N_" + safe
    return safe if safe else "NODE"


def _jp_to_short(text: str) -> str:
    """Convert common Japanese terms to short English."""
    mappings = {
        "中間": "MID",
        "分割": "SPLIT",
        "伝票データ": "SLIP_DATA",
        "納品": "DELIVERY",
        "発注": "ORDER",
        "明細": "DETAIL",
        "入力データ": "INPUT_DATA",
        "処理結果": "RESULT",
        "リターン": "RET",
        "ヘッダ": "HEADER",
        "納品明細": "DELIVERY_DETAIL",
        "発注明細": "ORDER_DETAIL",
        "発注一覧": "ORDER_LIST",
        "納品一覧": "DELIVERY_LIST",
    }
    for jp, en in mappings.items():
        if jp in text:
            return en
    # Fallback: take first few chars
    safe = re.sub(r'[^a-zA-Z0-9]', '', text[:10])
    return safe if safe else "OBJ"


def _unique_id(base: str, existing: set[str]) -> str:
    """Ensure ID is unique."""
    if not base:
        base = "NODE"
    # Sanitize
    base = re.sub(r'[^a-zA-Z0-9_]', '_', base)
    base = re.sub(r'_+', '_', base).strip('_')
    if not base:
        base = "NODE"
    
    if base not in existing:
        existing.add(base)
        return base
    
    i = 2
    while f"{base}_{i}" in existing:
        i += 1
    result = f"{base}_{i}"
    existing.add(result)
    return result
