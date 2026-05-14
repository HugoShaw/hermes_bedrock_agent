from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class SessionLoadError(Exception):
    pass


REQUIRED_TOP_KEYS = {"session_id", "messages"}


def load_session(path: str) -> Dict[str, Any]:
    """Load and validate a Hermes Agent session JSON file."""
    p = Path(path)
    if not p.exists():
        raise SessionLoadError(f"文件不存在: {path}")
    if not p.is_file():
        raise SessionLoadError(f"路径不是文件: {path}")

    try:
        raw = p.read_text(encoding="utf-8")
    except Exception as e:
        raise SessionLoadError(f"读取文件失败: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SessionLoadError(f"JSON 解析失败: {e}") from e

    if not isinstance(data, dict):
        raise SessionLoadError("会话文件顶层必须是 JSON 对象")

    missing = REQUIRED_TOP_KEYS - set(data.keys())
    if missing:
        raise SessionLoadError(f"会话文件缺少必要字段: {missing}")

    if not isinstance(data.get("messages"), list):
        raise SessionLoadError("'messages' 字段必须是数组")

    return data


def extract_session_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract top-level metadata from session data."""
    return {
        "session_id": data.get("session_id", "unknown"),
        "model": data.get("model", "unknown"),
        "base_url": data.get("base_url", ""),
        "platform": data.get("platform", "unknown"),
        "session_start": data.get("session_start"),
        "last_updated": data.get("last_updated"),
        "message_count": data.get("message_count", len(data.get("messages", []))),
        "tools_count": len(data.get("tools", [])),
        "system_prompt_length": len(data.get("system_prompt", "")),
    }
