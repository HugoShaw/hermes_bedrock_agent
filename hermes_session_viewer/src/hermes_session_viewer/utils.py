from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional


def safe_json_parse(text: str) -> Optional[Any]:
    """Parse JSON string, return None on failure."""
    try:
        return json.loads(text)
    except Exception:
        return None


def truncate(text: str, max_len: int = 200, ellipsis: str = "…") -> str:
    """Truncate text to max_len characters."""
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_len:
        return text
    return text[:max_len] + ellipsis


def extract_paths_from_text(text: str) -> List[str]:
    """Extract file/directory paths from a string using heuristics."""
    if not text:
        return []
    # Match Unix-style paths: start with / or ./ or ../ or ~/, followed by non-whitespace
    pattern = r'(?:^|[\s\'\"(])(/[\w./\-_]+|\.{1,2}/[\w./\-_]+|~/[\w./\-_]+)'
    matches = re.findall(pattern, text)
    paths = []
    for m in matches:
        m = m.strip().strip("'\"(),")
        if m and len(m) > 2:
            paths.append(m)
    return list(dict.fromkeys(paths))  # deduplicate preserving order


def extract_tool_name_from_content(content: str) -> Optional[str]:
    """Extract tool name from tool result content like '[tool_name] ...'."""
    if not content:
        return None
    m = re.match(r'^\[([^\]]+)\]', content.strip())
    if m:
        return m.group(1)
    return None


def sanitize_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def format_json_for_display(obj: Any, indent: int = 2, max_len: int = 50_000) -> str:
    """Format object as pretty JSON, truncating if too large."""
    try:
        text = json.dumps(obj, ensure_ascii=False, indent=indent, default=str)
    except Exception:
        text = str(obj)
    if len(text) > max_len:
        text = text[:max_len] + "\n… (内容过长，已截断)"
    return text


def safe_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely navigate nested dict."""
    current = d
    for k in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(k, default)
        if current is None:
            return default
    return current
