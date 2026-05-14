"""Load session data from Hermes Agent's internal state.db (SQLite)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hermes_session_viewer.loader import SessionLoadError

# Default path to the Hermes Agent state database
DEFAULT_STATE_DB = Path.home() / ".hermes" / "state.db"


def _epoch_to_iso(epoch: Optional[float]) -> Optional[str]:
    """Convert Unix epoch float to ISO 8601 string."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(epoch).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def _epoch_to_datetime(epoch: Optional[float]) -> Optional[datetime]:
    """Convert Unix epoch float to datetime."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(epoch)
    except (ValueError, OSError, OverflowError):
        return None


def find_session_in_db(
    session_id: str,
    db_path: Optional[str] = None,
) -> bool:
    """Check whether a session_id exists in the database."""
    db = Path(db_path) if db_path else DEFAULT_STATE_DB
    if not db.exists():
        return False
    try:
        conn = sqlite3.connect(str(db))
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,))
        found = cursor.fetchone() is not None
        conn.close()
        return found
    except Exception:
        return False


def list_sessions_in_db(
    db_path: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """List recent sessions from the database (for discovery / UI)."""
    db = Path(db_path) if db_path else DEFAULT_STATE_DB
    if not db.exists():
        return []
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        """SELECT id, source, model, title, started_at, ended_at,
                  message_count, tool_call_count, input_tokens, output_tokens,
                  estimated_cost_usd
           FROM sessions ORDER BY started_at DESC LIMIT ?""",
        (limit,),
    )
    rows = cursor.fetchall()
    conn.close()
    results = []
    for r in rows:
        results.append({
            "session_id": r["id"],
            "source": r["source"],
            "model": r["model"],
            "title": r["title"],
            "started_at": _epoch_to_iso(r["started_at"]),
            "ended_at": _epoch_to_iso(r["ended_at"]),
            "message_count": r["message_count"],
            "tool_call_count": r["tool_call_count"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "estimated_cost_usd": r["estimated_cost_usd"],
        })
    return results


def load_session_from_db(
    session_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Load a complete session from state.db and convert it to the same dict
    structure as the JSON file loader produces:
    {
        "session_id": str,
        "model": str,
        "platform": str,
        "session_start": str (ISO),
        "last_updated": str (ISO),
        "message_count": int,
        "system_prompt": str,
        "tools": [],
        "messages": [
            {"role": ..., "content": ..., "tool_calls": [...], "timestamp": float, ...}
        ],
        "_source": "state_db",
        "_db_metadata": { ... extra fields from sessions table ... }
    }
    """
    db = Path(db_path) if db_path else DEFAULT_STATE_DB
    if not db.exists():
        raise SessionLoadError(f"数据库文件不存在: {db}")

    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ── Load session row ──
    cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    session_row = cursor.fetchone()
    if session_row is None:
        conn.close()
        raise SessionLoadError(f"数据库中未找到 session_id={session_id}")

    # ── Load messages ──
    cursor.execute(
        """SELECT id, role, content, tool_call_id, tool_calls, tool_name,
                  timestamp, token_count, finish_reason,
                  reasoning, reasoning_content
           FROM messages
           WHERE session_id = ?
           ORDER BY timestamp ASC, id ASC""",
        (session_id,),
    )
    msg_rows = cursor.fetchall()
    conn.close()

    # ── Convert messages ──
    messages: List[Dict[str, Any]] = []
    for mrow in msg_rows:
        msg: Dict[str, Any] = {
            "role": mrow["role"],
            "content": mrow["content"] or "",
            "timestamp": mrow["timestamp"],  # epoch float — exact!
        }
        if mrow["tool_call_id"]:
            msg["tool_call_id"] = mrow["tool_call_id"]
        if mrow["tool_name"]:
            msg["tool_name"] = mrow["tool_name"]
        if mrow["tool_calls"]:
            try:
                msg["tool_calls"] = json.loads(mrow["tool_calls"])
            except json.JSONDecodeError:
                msg["tool_calls"] = []
        if mrow["finish_reason"]:
            msg["finish_reason"] = mrow["finish_reason"]
        if mrow["token_count"]:
            msg["token_count"] = mrow["token_count"]
        if mrow["reasoning"]:
            msg["reasoning"] = mrow["reasoning"]
        if mrow["reasoning_content"]:
            msg["reasoning_content"] = mrow["reasoning_content"]
        messages.append(msg)

    # ── Build the normalized data dict ──
    data: Dict[str, Any] = {
        "session_id": session_row["id"],
        "model": session_row["model"] or "unknown",
        "platform": session_row["source"] or "unknown",
        "session_start": _epoch_to_iso(session_row["started_at"]),
        "last_updated": _epoch_to_iso(session_row["ended_at"]) or _epoch_to_iso(session_row["started_at"]),
        "message_count": len(messages),
        "system_prompt": session_row["system_prompt"] or "",
        "tools": [],  # not stored in DB per-session
        "messages": messages,
        "_source": "state_db",
        "_db_metadata": {
            "title": session_row["title"],
            "source": session_row["source"],
            "message_count_db": session_row["message_count"],
            "tool_call_count": session_row["tool_call_count"],
            "input_tokens": session_row["input_tokens"],
            "output_tokens": session_row["output_tokens"],
            "cache_read_tokens": session_row["cache_read_tokens"],
            "cache_write_tokens": session_row["cache_write_tokens"],
            "reasoning_tokens": session_row["reasoning_tokens"],
            "estimated_cost_usd": session_row["estimated_cost_usd"],
            "end_reason": session_row["end_reason"],
            "api_call_count": session_row["api_call_count"],
            "billing_provider": session_row["billing_provider"],
        },
    }

    return data
