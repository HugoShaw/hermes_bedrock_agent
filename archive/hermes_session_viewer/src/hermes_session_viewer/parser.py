from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from hermes_session_viewer.models import StandardEvent
from hermes_session_viewer.utils import (
    extract_paths_from_text,
    extract_tool_name_from_content,
    safe_json_parse,
    truncate,
)

# Tools that typically read files
_FILE_READ_TOOLS = {
    "read_file", "file_read", "skill_view", "read", "cat", "head", "tail",
    "execute_code", "python", "bash", "terminal",
}
# Tools that typically write files
_FILE_WRITE_TOOLS = {
    "write_file", "file_write", "write", "save_file", "create_file",
    "skill_manage", "memory",
}
# Tools associated with command execution
_EXEC_TOOLS = {
    "execute_code", "bash", "terminal", "shell", "run_command", "python",
}
# Tools associated with errors or quality
_ERROR_KEYWORDS = re.compile(
    r'\b(error|exception|traceback|failed|failure|errno|cannot|unable|invalid)\b',
    re.IGNORECASE,
)


def _make_event_id(session_id: str, raw_index: int, suffix: str = "") -> str:
    return f"{session_id}_msg{raw_index:04d}{suffix}"


def _detect_status(content: str) -> str:
    if _ERROR_KEYWORDS.search(content or ""):
        return "error"
    return "success"


def _parse_tool_call(
    tc: Dict[str, Any],
    session_id: str,
    raw_index: int,
    tc_index: int,
    timestamp: Optional[datetime],
    timestamp_type: str,
    raw_msg: Dict[str, Any],
) -> StandardEvent:
    fn = tc.get("function", {})
    tool_name = fn.get("name", "unknown_tool")
    raw_args = fn.get("arguments", "{}")
    args = safe_json_parse(raw_args) if isinstance(raw_args, str) else raw_args
    if not isinstance(args, dict):
        args = {"raw": raw_args}

    # Detect file paths from arguments
    args_text = json.dumps(args, ensure_ascii=False) if args else ""
    input_files = extract_paths_from_text(args_text)
    output_files: List[str] = []

    # Determine sub-type
    if tool_name in _EXEC_TOOLS:
        event_type = "command_exec"
        command = args.get("command") or args.get("code") or args.get("cmd") or ""
    elif tool_name in _FILE_WRITE_TOOLS:
        event_type = "file_write"
        command = None
        output_files = extract_paths_from_text(args_text)
        input_files = []
    elif tool_name in _FILE_READ_TOOLS:
        event_type = "file_read"
        command = None
    else:
        event_type = "tool_call"
        command = None

    title = f"调用工具: {tool_name}"
    short_args = truncate(args_text, 120)

    return StandardEvent(
        event_id=_make_event_id(session_id, raw_index, f"_tc{tc_index}"),
        session_id=session_id,
        raw_index=raw_index,
        timestamp=timestamp,
        timestamp_type=timestamp_type,
        event_type=event_type,
        actor="agent",
        title=title,
        natural_language_summary="",  # filled later by natural_language module
        details={"tool_name": tool_name, "arguments": args, "call_id": tc.get("id", "")},
        tool_name=tool_name,
        command=command or None,
        input_files=input_files,
        output_files=output_files,
        status="unknown",
        raw_event=raw_msg,
    )


def _parse_tool_result(
    msg: Dict[str, Any],
    session_id: str,
    raw_index: int,
    timestamp: Optional[datetime],
    timestamp_type: str,
) -> StandardEvent:
    content = str(msg.get("content", ""))
    tool_name = extract_tool_name_from_content(content) or "unknown_tool"
    # Strip the [tool_name] prefix for cleaner body
    body = re.sub(r'^\[[^\]]+\]\s*', '', content, count=1)

    output_files = extract_paths_from_text(body)
    status = _detect_status(body)

    title = f"工具结果: {tool_name}"
    return StandardEvent(
        event_id=_make_event_id(session_id, raw_index),
        session_id=session_id,
        raw_index=raw_index,
        timestamp=timestamp,
        timestamp_type=timestamp_type,
        event_type="tool_result",
        actor="tool",
        title=title,
        natural_language_summary="",
        details={"tool_name": tool_name, "content_preview": truncate(body, 300)},
        tool_name=tool_name,
        command=None,
        input_files=[],
        output_files=output_files,
        status=status,
        raw_event=msg,
    )


def _parse_user_message(
    msg: Dict[str, Any],
    session_id: str,
    raw_index: int,
    timestamp: Optional[datetime],
    timestamp_type: str,
) -> StandardEvent:
    content = str(msg.get("content", ""))
    is_compaction = "CONTEXT COMPACTION" in content or "context window" in content.lower()
    event_type = "agent_message" if is_compaction else "user_request"
    actor = "system" if is_compaction else "user"
    title = "上下文压缩摘要" if is_compaction else "用户请求"

    return StandardEvent(
        event_id=_make_event_id(session_id, raw_index),
        session_id=session_id,
        raw_index=raw_index,
        timestamp=timestamp,
        timestamp_type=timestamp_type,
        event_type=event_type,
        actor=actor,
        title=title,
        natural_language_summary="",
        details={"content_preview": truncate(content, 500)},
        tool_name=None,
        command=None,
        input_files=[],
        output_files=[],
        status="success",
        raw_event=msg,
    )


def _parse_assistant_message(
    msg: Dict[str, Any],
    session_id: str,
    raw_index: int,
    timestamp: Optional[datetime],
    timestamp_type: str,
) -> List[StandardEvent]:
    events: List[StandardEvent] = []
    content = str(msg.get("content", ""))
    tool_calls = msg.get("tool_calls", []) or []
    finish_reason = msg.get("finish_reason", "")

    # If the assistant has a text content blob (plan/reasoning), emit it first
    if content.strip():
        is_compaction = "CONTEXT COMPACTION" in content
        is_final = finish_reason == "end_turn" and not tool_calls
        is_error = "error" in content.lower() and not tool_calls

        if is_compaction:
            etype = "agent_message"
            title = "上下文压缩（助手侧）"
        elif is_final:
            etype = "final_answer"
            title = "最终回复"
        elif is_error:
            etype = "error"
            title = "错误信息"
        else:
            etype = "agent_plan"
            title = "助手思考/计划"

        events.append(StandardEvent(
            event_id=_make_event_id(session_id, raw_index, "_text"),
            session_id=session_id,
            raw_index=raw_index,
            timestamp=timestamp,
            timestamp_type=timestamp_type,
            event_type=etype,
            actor="agent",
            title=title,
            natural_language_summary="",
            details={"content_preview": truncate(content, 500)},
            tool_name=None,
            command=None,
            input_files=[],
            output_files=[],
            status="error" if is_error else "success",
            raw_event=msg,
        ))

    # Parse each tool call
    for i, tc in enumerate(tool_calls):
        if not isinstance(tc, dict):
            continue
        events.append(_parse_tool_call(tc, session_id, raw_index, i, timestamp, timestamp_type, msg))

    return events


def parse_messages(
    messages: List[Dict[str, Any]],
    timestamps: List[Optional[datetime]],
    session_id: str,
    timestamp_type: str = "estimated",
) -> List[StandardEvent]:
    """
    Convert raw messages into StandardEvent list.
    
    Args:
        messages: List of message dicts (from JSON or DB).
        timestamps: Per-message datetime objects (same length as messages).
        session_id: The session identifier.
        timestamp_type: "exact" if timestamps came from DB, "estimated" if interpolated.
    """
    events: List[StandardEvent] = []

    for idx, msg in enumerate(messages):
        ts = timestamps[idx] if idx < len(timestamps) else None
        # Per-message timestamp_type: if ts is None, mark as "missing"
        ts_type = "missing" if ts is None else timestamp_type
        role = msg.get("role", "unknown")

        try:
            if role == "user":
                events.append(_parse_user_message(msg, session_id, idx, ts, ts_type))
            elif role == "assistant":
                events.extend(_parse_assistant_message(msg, session_id, idx, ts, ts_type))
            elif role == "tool":
                events.append(_parse_tool_result(msg, session_id, idx, ts, ts_type))
            else:
                events.append(StandardEvent(
                    event_id=_make_event_id(session_id, idx),
                    session_id=session_id,
                    raw_index=idx,
                    timestamp=ts,
                    timestamp_type=ts_type,
                    event_type="unknown",
                    actor="unknown",
                    title=f"未知消息 (role={role})",
                    natural_language_summary="",
                    details={"content_preview": truncate(str(msg.get("content", "")), 200)},
                    tool_name=None,
                    command=None,
                    input_files=[],
                    output_files=[],
                    status="unknown",
                    raw_event=msg,
                ))
        except Exception as e:
            events.append(StandardEvent(
                event_id=_make_event_id(session_id, idx, "_err"),
                session_id=session_id,
                raw_index=idx,
                timestamp=ts,
                timestamp_type=ts_type,
                event_type="error",
                actor="system",
                title=f"解析错误 (msg {idx})",
                natural_language_summary=f"解析消息时发生错误: {e}",
                details={"error": str(e)},
                tool_name=None,
                command=None,
                input_files=[],
                output_files=[],
                status="error",
                raw_event=msg,
            ))

    return events
